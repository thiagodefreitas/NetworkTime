# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""``ntpstats`` command-line interface."""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
from typing import List, Optional

import numpy as np

from . import __version__
from .analysis import compare, format_seconds, remove_outliers, summary
from .parsers import ParseError, load, load_one
from .series import TimeSeries
from .stability import DESCRIPTIONS, KINDS, NOISE_NAMES, series_stability


# ----------------------------------------------------------------- helpers
def _parse_time(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return float(calendar.timegm(time.strptime(v.rstrip("Z"), fmt)))
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"cannot parse time {v!r} (use POSIX seconds or ISO 8601 UTC)")


def _load_args(args) -> List[TimeSeries]:
    out = []
    for path in args.files:
        if args.peer or not args.all_peers:
            try:
                s = [load_one(path, fmt=args.format, peer=args.peer, tau0=args.tau0)]
            except ParseError as exc:
                raise SystemExit(f"{path}: {exc}") from None
        else:
            s = load(path, fmt=args.format, tau0=args.tau0)
        for x in s:
            if getattr(args, "negate", False):
                x = TimeSeries(t=x.t, offset=-x.offset, name=x.name, source_format=x.source_format,
                               extra=x.extra, meta=dict(x.meta, negated=True))
            if args.start is not None or args.end is not None:
                x = x.between(args.start, args.end)
            if args.outliers:
                x = remove_outliers(x, args.outliers)
            if len(x) < 3:
                raise SystemExit(f"{x.name}: fewer than 3 samples after filtering")
            out.append(x)
    return out


def _family(args) -> int:
    import socket

    return socket.AF_INET if getattr(args, "ipv4", False) else socket.AF_INET6 if getattr(args, "ipv6", False) else 0


def _utc(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


def _fmt(v: str) -> str:
    from .parsers import all_formats

    if v == "auto" or v.startswith("profile:") or v in all_formats():
        return v
    raise argparse.ArgumentTypeError(f"invalid format {v!r}; choose auto, {', '.join(all_formats())} or profile:NAME|FILE")


FORMAT_HELP = "input format (default: auto-detect); profile:NAME or profile:FILE.toml for instrument exports"


def _common(p: argparse.ArgumentParser):
    p.add_argument("files", nargs="+", help="log files (loopstats, peerstats, rawstats, chrony logs, CSV...)")
    p.add_argument("-f", "--format", default="auto", type=_fmt, help=FORMAT_HELP)
    p.add_argument("--negate", action="store_true", help="flip the sign of the offsets (for sources that log "
                                                          "local - reference)")
    p.add_argument("--peer", help="select a peer/source (substring of its address) in multi-peer logs")
    p.add_argument("--all-peers", action="store_true", help="analyse every peer in multi-peer logs")
    p.add_argument("--start", type=_parse_time, help="ignore samples before this time (POSIX s or ISO 8601 UTC)")
    p.add_argument("--end", type=_parse_time, help="ignore samples after this time")
    p.add_argument("--outliers", type=float, metavar="K", help="drop samples more than K*MAD from the detrended median")
    p.add_argument("--tau0", type=float, help="sample interval of single-column files; also the stability grid")


# ---------------------------------------------------------------- commands
def cmd_convert(args):
    from .interop import write_stable32

    series = _load_args(args)
    if args.to == "omnetpp-vec":  # every series in one vector file
        from .simio import write_omnetpp_vec

        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(write_omnetpp_vec(series))
        print(f"{len(series)} series -> {args.output} (OMNeT++ vector file)", file=sys.stderr)
        return
    if len(series) > 1 and "{n}" not in args.output:
        raise SystemExit("several series: put {n} in --output (e.g. out-{n}.dat)")
    for i, s in enumerate(series):
        path = args.output.replace("{n}", str(i))
        if args.to == "csv":
            with open(path, "w", encoding="utf-8") as fh:
                cols = ["unix_time", "offset"] + list(s.extra)
                fh.write(",".join(cols) + "\n")
                for k in range(len(s)):
                    vals = [s.t[k], s.offset[k]] + [s.extra[c][k] for c in s.extra]
                    fh.write(",".join(f"{float(v):.15g}" for v in vals) + "\n")
            rows = len(s)
        elif args.to == "ns3":
            from .simio import write_columns

            with open(path, "w", encoding="utf-8") as fh:
                fh.write(write_columns(s))
            rows = len(s)
        elif args.to == "parquet":
            try:
                s.to_parquet(path)
            except ImportError as exc:
                raise SystemExit(str(exc)) from None
            rows = len(s)
        else:
            rows = write_stable32(s, path, data_type=args.to.split("-")[1], timetags=not args.no_timetags,
                                  tau0=args.resample, max_gap=args.max_gap)
        print(f"{s.name}: {rows} rows -> {path}", file=sys.stderr)


def cmd_info(args):
    rows = [summary(s) for s in _load_args(args)]
    if args.json:
        print(json.dumps(rows, indent=2, default=float))
        return
    for r in rows:
        print(f"== {r['name']}  [{r['format']}]")
        print(f"   samples      {r['samples']}   {_utc(r['start'])} .. {_utc(r['end'])} UTC ({r['span_s'] / 3600:.2f} h)")
        print(f"   interval     median {r.get('median_interval_s', float('nan')):.4g} s, regularity {r.get('regularity', 1):.0%}, "
              f"gaps {r.get('gaps', 0)} (longest {r.get('longest_gap_s', 0):.4g} s)")
        print(f"   offset       mean {format_seconds(r['mean'])}, std {format_seconds(r['std'])}, rms {format_seconds(r['rms'])}")
        p = r["percentiles"]
        print(f"   percentiles  p1 {format_seconds(p['p1'])}  p5 {format_seconds(p['p5'])}  p50 {format_seconds(p['p50'])}  "
              f"p95 {format_seconds(p['p95'])}  p99 {format_seconds(p['p99'])}")
        print(f"   90% range    {format_seconds(r['range_90'])}    98% range {format_seconds(r['range_98'])}")
        if "offset_slope_ppm" in r:
            print(f"   trend        {r['offset_slope_ppm']:+.4f} ppm (LSQ), {r['offset_slope_robust_ppm']:+.4f} ppm (Theil-Sen); "
                  f"detrended rms {format_seconds(r['residual_rms'])}; {r['outliers_5mad']} outliers >5 MAD")
        extras = [k for k in r if k.endswith("_median")]
        if extras:
            print("   columns      " + ", ".join(f"{k[:-7]} {r[k]:.4g}" for k in extras))


def cmd_audit(args):
    from .audit import AuditConfig, audit, public, to_html
    from .timeerror import _value

    def val(v):
        return None if v is None else _value(v)

    cfg = AuditConfig(limit=_value(args.limit), window=_duration(args.window),
                      reference_uncertainty=val(args.reference_uncertainty) or 0.0,
                      asymmetry=val(args.asymmetry), upstream=val(args.upstream),
                      max_gap=args.max_gap, min_coverage=args.min_coverage)
    results = []
    for s in _load_args(args):
        ev = None
        if args.events:
            from .events import detect

            ev = detect(s)
        results.append(audit(s, cfg, ev))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(to_html(results, args.files))
        print(f"wrote {args.html}", file=sys.stderr)
    if args.json:
        from .audit import manifest

        print(json.dumps({"version": __version__, "inputs": manifest(args.files),
                          "audit": [public(r) for r in results]}, indent=2, default=float))
    else:
        for r in results:
            sm = r["summary"]
            print(f"== {r['name']}  [{'PASS' if sm['passed'] else 'FAIL'}]  limit {format_seconds(r['limit'])}")
            print(f"  bound max {format_seconds(sm['max_bound'])}, p99 {format_seconds(sm['p99_bound'])}, "
                  f"median {format_seconds(sm['median_bound'])}")
            print(f"  coverage {sm['coverage']:.2%} (unmonitored {sm['unmonitored_s'] / 3600:.2f} h); within limit "
                  f"{sm['within_limit_fraction_of_period']:.2%} of the period")
            print(f"  windows: {sm['windows']} ({sm['failing_windows']} failing, {sm['insufficient_windows']} "
                  f"insufficient coverage)")
            for k, v in r["rules"].items():
                print(f"  {k:9} {v}")
            for n in r["notes"]:
                print(f"  note: {n}")
    return 0 if all(r["summary"]["passed"] for r in results) else 3


def cmd_events(args):
    from .events import detect, summary

    out = []
    for s in _load_args(args):
        ev = detect(s, step_k=args.step_k, freq_thresh=args.freq_threshold,
                    min_freq_change=args.min_freq_change_ppm * 1e-6, floor_block=args.floor_block)
        out.append({"name": s.name, "events": [e.as_dict() for e in ev], "summary": summary(ev)})
        if args.json:
            continue
        print(f"== {s.name}  ({len(ev)} events)")
        for e in ev:
            if e.unit == "s/s":
                mag = f"{e.magnitude * 1e6:+.3f} ppm"
            else:
                mag = f"{'+' if e.magnitude >= 0 else '-'}{format_seconds(abs(e.magnitude))}"
            end = f" .. {_utc(e.end)}" if e.end else ""
            extra = ""
            if "path_changed" in e.detail:
                extra = "  [path changed]" if e.detail["path_changed"] else "  [path unchanged]"
            if e.kind == "delay_floor_change":
                extra = f"  offset shift {format_seconds(float(e.detail['offset_shift']))} ({e.detail['interpretation']})"
            print(f"  {_utc(e.time)}{end}  {e.kind:19} {mag:>12}  score {e.score:6.1f}{extra}")
    if args.json:
        print(json.dumps(out, indent=2, default=float))


def cmd_prom(args):
    from .sources import prometheus_query_range

    end = args.end if args.end is not None else time.time()
    start = args.start if args.start is not None else end - _duration(args.since)
    from .sources import SourceError

    try:
        doc = prometheus_query_range(args.url, args.query, start, end, args.step, timeout=args.timeout)
    except SourceError as exc:
        raise SystemExit(str(exc)) from None
    n = sum(len(r.get("values", [])) for r in doc["data"]["result"])
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    print(f"{len(doc['data']['result'])} series, {n} samples -> {args.output} "
          f"(analyse with any command, e.g. ntpstats stability {args.output} --all-peers)", file=sys.stderr)


def _duration(v: str) -> float:
    m = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    v = v.strip()
    return float(v[:-1]) * m[v[-1]] if v and v[-1] in m else float(v)


def cmd_bounds(args):
    from .bounds import validate

    try:
        b = load_one(args.bounds, fmt="bounds")
    except ParseError as exc:
        raise SystemExit(f"{args.bounds}: {exc}") from None
    ref = load_one(args.reference, fmt=args.ref_format, peer=args.ref_peer)
    if args.negate_reference:
        ref = TimeSeries(t=ref.t, offset=-ref.offset, name=ref.name, extra=ref.extra, meta=ref.meta)
    r = validate(b, ref, max_gap=args.max_gap, reference_uncertainty=args.ref_uncertainty)
    rc = 3 if (r["compared"] and r["violation_rate"] > args.max_violation_rate) else 0
    if args.json:
        print(json.dumps(r, indent=2, default=float))
        return rc
    print(f"== {b.name} against {ref.name}")
    if not r["compared"]:
        print("  no overlap between the bounds and the reference")
        return 0
    print(f"  compared {r['compared']}: inside {r['inside']}, violated {r['violations']}, "
          f"indeterminate {r['indeterminate']} (reference not good enough to tell)")
    print(f"  violation rate {r['violation_rate']:.3%}; worst excess {format_seconds(r['worst_excess'])}")
    print(f"  median bound {format_seconds(r['median_bound'])}; median |error| {format_seconds(r['median_abs_error'])}"
          f" (tightness {r['tightness']:.2f}); reference uncertainty {format_seconds(r['median_reference_uncertainty'])}")
    print(f"  [{'FAIL' if rc else 'PASS'}] violation rate <= {args.max_violation_rate:.3%}")
    return rc


def cmd_timeerror(args):
    from .masks import load_mask
    from .timeerror import check, load_limits, time_error

    limits = load_limits(args.limits) if args.limits else None
    masks = [load_mask(m) for m in (args.mask or [])]
    scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}[args.units]
    out, rc = [], 0
    for s in _load_args(args):
        if scale != 1.0:
            s = TimeSeries(t=s.t, offset=s.offset * scale, name=s.name, source_format=s.source_format,
                           extra=s.extra, meta=s.meta)
        r = time_error(s, tau0=args.resample, lpf_hz=args.lpf_hz, cte_window=args.cte_window,
                       input_is_te=args.input_is_te, max_gap=args.max_gap)
        c = check(r, limits, masks)
        if c["passed"] is False:
            rc = 3
        out.append({"name": s.name, **r.as_dict(), "check": c})
        if args.json:
            continue
        print(f"== {s.name}  ({r.n} samples, tau0 {format_seconds(r.tau0)}, {args.lpf_hz:g} Hz filter)")
        rows = [("max|TE|", r.max_abs_te), ("cTE (record)", r.cte),
                (f"max |cTE| over {r.cte_window:g} s windows", r.max_abs_cte_window),
                ("max|TEL|", r.max_abs_tel), ("dTE_L peak-to-peak", r.dte_l_pp), ("dTE_H peak-to-peak", r.dte_h_pp)]
        for label, v in rows:
            print(f"  {label:34} {format_seconds(v):>12}")
        if r.mtie is not None and r.mtie.taus.size:
            print("  dTE_L MTIE / TDEV:")
            td = dict(zip(np.round(r.tdev.taus, 9), r.tdev.dev)) if r.tdev is not None else {}
            for tau, v in zip(r.mtie.taus, r.mtie.dev):
                print(f"    tau {tau:>10g} s  MTIE {format_seconds(v):>10}  TDEV "
                      f"{format_seconds(td.get(round(tau, 9), float('nan'))):>10}")
        for w in r.warnings:
            print(f"  note: {w}")
        for row in c["checks"]:
            verdict = {True: "PASS", False: "FAIL", None: "n/a"}[row["passed"]]
            extra = f"  value {format_seconds(row['value'])}  limit {format_seconds(row['limit'])}" if "limit" in row else ""
            print(f"  [{verdict}] {row['label']}{extra}")
    if args.json:
        print(json.dumps(out, indent=2, default=float))
    return rc


def cmd_noise(args):
    from .noisefit import ALPHAS, fit_series
    from .stability import NOISE_NAMES

    out = []
    for s in _load_args(args):
        nf = fit_series(s, kinds=args.kinds.split(","), spectrum=args.spectrum, ci=args.ci,
                        bootstrap=args.bootstrap, detrend=args.detrend if args.detrend != "none" else None,
                        drift=args.drift)
        out.append({"name": s.name, **nf.as_dict()})
        if args.scenario:
            with open(args.scenario, "w", encoding="utf-8") as fh:
                fh.write(f"# statistically equivalent clock for {s.name} (ntpstats {__version__})\n[clock]\n"
                         "freq_offset = 0.0\ndrift = 0.0\n[clock.h_alpha]\n")
                for a, v in nf.h.items():
                    if v > 0:
                        fh.write(f'"{a}" = {v:.6e}\n')
        if args.inet:
            from .simio import inet_oscillator

            osc = inet_oscillator(nf.h, drift=nf.drift, change_interval=args.inet_interval, tau0=nf.tau0)
            with open(args.inet, "w", encoding="utf-8") as fh:
                fh.write(f"# INET oscillator for {s.name} (ntpstats {__version__}); include it in omnetpp.ini\n")
                fh.write(osc["ini"])
            out[-1]["inet"] = {k: v for k, v in osc.items() if k != "ini"}
        if args.json:
            continue
        print(f"== {s.name}  (tau0 {format_seconds(nf.tau0)}, {nf.meta['points']} points from "
              f"{', '.join(nf.meta['inputs'])}; intervals: {nf.method}, {args.ci:.0%})")
        print(f"  {'noise':16} {'alpha':>5} {'h_alpha':>12} {'interval':>27}")
        for a in ALPHAS:
            v = nf.h[a]
            ci_txt = f"[{nf.lo[a]:.3e}, {nf.hi[a]:.3e}]" if v > 0 else f"< {nf.hi[a]:.3e}"
            print(f"  {NOISE_NAMES[a]:16} {a:>5} {v:>12.3e} {ci_txt:>27}")
        if nf.drift:
            print(f"  drift {nf.drift:.3e} /s ({nf.drift * 86400:.3e} per day)")
        print(f"  reduced chi2 {nf.reduced_chi2:.2f} ({nf.dof} dof)")
        for c in nf.corners:
            print(f"  corner at tau ~ {c['tau']:g} s: {c['from']} -> {c['to']}")
        if args.scenario:
            print(f"  simulator scenario written to {args.scenario}")
        if args.inet:
            lost = ", ".join(x["noise"] for x in out[-1]["inet"]["lost"]) or "nothing"
            print(f"  INET RandomDriftOscillator written to {args.inet} (random-walk FM kept; not representable: {lost})")
    if args.json:
        print(json.dumps(out, indent=2, default=float))
    return 0


def cmd_spectrum(args):
    from .spectrum import series_spectrum

    out = []
    for s in _load_args(args):
        sp = series_spectrum(s, kind=args.kind, method=args.method,
                             per_decade=None if args.per_decade == 0 else args.per_decade)
        d = {"name": s.name, **sp.as_dict()}
        if args.carrier:
            d["lf_dbc"] = sp.lf_dbc(args.carrier).tolist()
        out.append(d)
        if args.json:
            continue
        unit = "s^2/Hz" if args.kind == "x" else "1/Hz"
        print(f"# {s.name}: S_{args.kind}(f) [{unit}], {sp.meta['method']}, {sp.meta['segments']} segments")
        print("f_hz,psd,dof" + (",L_dbc_hz" if args.carrier else ""))
        lf = d.get("lf_dbc")
        for i, (f, p_, k) in enumerate(zip(sp.f, sp.psd, sp.dof)):
            print(f"{f:.6g},{p_:.6g},{k:.4g}" + (f",{lf[i]:.2f}" if lf else ""))
    if args.json:
        print(json.dumps(out, indent=2, default=float))
    return 0


def cmd_hat(args):
    from .hat import hat_series

    series = _load_args(args)
    if len(series) < 3:
        raise SystemExit("hat: give at least three sources (files, or --all-peers on a multi-peer log)")
    r = hat_series(series, method=args.method, ci=args.ci)
    if args.json:
        print(json.dumps(r.as_dict(), indent=2, default=float))
        return 0
    label = {"gcov": "Groslambert covariance", "3ch": "three-cornered hat", "nch": "N-cornered hat"}[r.method]
    print(f"Individual ADEV by {label} ({r.ci:.0%} intervals; * = negative variance, not resolvable)")
    print(f"{'tau':>10} " + " ".join(f"{n[:22]:>24}" for n in r.names))
    for t in range(r.taus.size):
        cells = []
        for i in range(len(r.names)):
            if r.negative[i, t]:
                cells.append(f"{'*  < ' + format(r.hi[i, t], '.2e'):>24}")
            else:
                cells.append(f"{r.dev[i, t]:.2e} [{r.lo[i, t]:.1e},{r.hi[i, t]:.1e}]".rjust(24))
        print(f"{r.taus[t]:>10g} " + " ".join(cells))
    if r.meta.get("negative_variances"):
        print(f"note: {r.meta['negative_variances']} negative variances (a source much quieter than the others, "
              "or correlated noise between sources)")
    return 0


def cmd_holdover(args):
    from .holdover import backtest, holdover_series, phase_from
    from .timeerror import _value

    limits = [_value(v) for v in (args.limit or [])]
    horizon = _duration(args.horizon)
    window = _duration(args.window) if args.window else None
    rc, out = 0, []
    for s in _load_args(args):
        r = holdover_series(s, horizon, source=args.source, model=args.model, window=window, ci=args.ci,
                            limits=limits, uncertainty=args.uncertainty)
        d = {"name": s.name, **r.as_dict()}
        if args.backtest:
            _, x, tau0 = phase_from(s, args.source)
            try:
                d["backtest"] = backtest(x, tau0, horizon, trials=args.backtest, model=args.model, window=window,
                                         ci=args.ci)
            except ValueError as exc:
                d["backtest"] = {"error": str(exc)}
        if args.min_holdover and limits:
            need = _duration(args.min_holdover)
            t = r.time_to(limits[0])["envelope"]
            d["min_holdover_met"] = t is None or t >= need
            rc = 0 if d["min_holdover_met"] else 3
        out.append(d)
        if args.json:
            continue
        print(f"== {s.name}: reference lost at {_utc(r.meta['loss_time'])} UTC; {r.model} holdover "
              f"(frequency {r.frequency * 1e9:+.3f} ppb, drift {r.drift * 86400e9:+.3g} ppb/day, "
              f"window {format_seconds(r.window)})")
        print(f"  {'after':>10} {'mean TIE':>11} {f'{r.ci:.0%} envelope':>28}")
        for i in np.unique(np.linspace(0, r.t.size - 1, 12).astype(int)):
            print(f"  {format_seconds(r.t[i]):>10} {format_seconds(r.mean[i]):>11} "
                  f"[{format_seconds(r.lo[i]):>11}, {format_seconds(r.hi[i]):>11}]")
        for lim, tt in r.limits.items():
            env, mean = tt["envelope"], tt["mean"]
            print(f"  limit {format_seconds(float(lim))}: may be exceeded after "
                  f"{format_seconds(env) if env else f'> {format_seconds(horizon)}'} ({r.ci:.0%} envelope), "
                  f"expected after {format_seconds(mean) if mean else f'> {format_seconds(horizon)}'}")
        if "warning" in r.meta:
            print(f"  note: {r.meta['warning']}")
        if "backtest" in d and "error" in d["backtest"]:
            print(f"  backtest not possible: {d['backtest']['error']}")
        elif "backtest" in d:
            b = d["backtest"]
            print(f"  backtest: real TIE inside the envelope {b['coverage']:.1%} of the time over {b['trials']} "
                  f"simulated losses (target {r.ci:.0%})")
        if "min_holdover_met" in d:
            print(f"  [{'PASS' if d['min_holdover_met'] else 'FAIL'}] holds {format_seconds(limits[0])} for "
                  f"{args.min_holdover}")
    if args.json:
        print(json.dumps(out, indent=2, default=float))
    return rc


def cmd_plugins(args):
    from .plugins import listing

    data = listing()
    if args.json:
        print(json.dumps(data, indent=2))
        return 1 if data.get("errors") else 0
    for kind, rows in data.items():
        print(f"{kind}:")
        ext = [r for r in rows if r["source"] != "built-in"]
        shown = rows if args.all or kind == "errors" else ext
        for r in shown:
            print(f"  {r['name']:24} {r['source']:28} {r['description']}")
        hidden = len(rows) - len(shown)
        if hidden:
            print(f"  ({hidden} built-in; --all to list)")
        if not rows:
            print("  (none)")
    return 1 if data.get("errors") else 0


def cmd_dataset(args):
    import glob

    from .research import interop_summary

    files = sorted(glob.glob(os.path.join(args.path, "**", "*.jsonl"), recursive=True)) \
        if os.path.isdir(args.path) else [args.path]
    lines: List[str] = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            lines += fh.read().splitlines()
    rows = interop_summary(lines)
    if args.test:
        rows = [r for r in rows if r["test"] == args.test]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{len(files)} files, {sum(r['probes'] for r in rows)} probes")
    print(f"{'test':16} {'server':34} {'runs':>4} {'avail':>6} {'median offset':>14} {'median delay':>13}  note")
    for r in rows:
        note = ", ".join(f"{k.replace('_', ' ')} {r[k]:.0%}" for k in ("interleaved", "offers_v5") if k in r)
        if r["last_error"] and r["availability"] < 1:
            note = (note + "; " if note else "") + f"last error: {str(r['last_error'])[:50]}"
        off = format_seconds(r["median_offset"]) if r["median_offset"] is not None else "-"
        dly = format_seconds(r["median_delay"]) if r["median_delay"] is not None else "-"
        print(f"{r['test']:16} {r['server'][:34]:34} {r['runs']:>4} {r['availability']:>6.0%} {off:>14} {dly:>13}  {note}")
    return 0


def cmd_sawtooth(args):
    from .stability import compute
    from .ubx import apply_qerr

    pps = load_one(args.pps, fmt=args.format, peer=args.peer)
    if args.ubx:
        qe = [s for s in load(args.ubx, fmt="ubx") if s.meta.get("message") == "UBX-TIM-TP"]
        if not qe:
            raise ValueError(f"{args.ubx}: no UBX-TIM-TP messages (enable TIM-TP output on the receiver)")
    elif "qerr" in pps.extra:  # e.g. gpsd PPS messages carry the receiver's qErr
        ok = np.isfinite(pps.extra["qerr"])
        qe = [TimeSeries(pps.t[ok], pps.extra["qerr"][ok], name="qErr")]
    else:
        raise ValueError("give the receiver's UBX log (the PPS file has no qErr column)")
    sign = args.sign if args.sign == "auto" else int(args.sign)
    out = apply_qerr(pps, qe[0], sign=sign, max_dt=args.max_dt)
    m = out.meta
    print(f"{out.name}: {m['matched']} PPS samples paired with qErr ({m['unmatched']} without), "
          f"sign {m['qerr_sign']:+d} ({m['sign_choice']})")
    print(f"   sample-to-sample rms  {format_seconds(m['diff_rms_before']):>10} -> {format_seconds(m['diff_rms_after']):>10}")
    tau0 = float(np.median(np.diff(out.t))) if len(out) > 1 else 1.0
    taus = [x for x in (1, 10, 100, 1000) if x * tau0 * 4 <= out.t[-1] - out.t[0]]
    if taus:
        before = compute(out.extra["uncorrected"], tau0, "tdev", taus=[x * tau0 for x in taus])
        after = compute(out.offset, tau0, "tdev", taus=[x * tau0 for x in taus])
        print("   TDEV  " + "  ".join(f"τ={t:g}s {format_seconds(b)} -> {format_seconds(a)}"
                                      for t, b, a in zip(before.taus, before.dev, after.dev)))
    if args.output:
        out.to_csv(args.output)
        print(f"wrote {args.output}")


def cmd_trace(args):
    from .trace import load_trace

    tr = load_trace(args.file, peer=args.peer, fmt=args.format, detrend=args.detrend, window=args.window,
                    asymmetry=args.asymmetry)
    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as fh:
            fh.write(tr.to_csv())
        print(f"wrote {args.csv} (use it as [trace] file in a scenario, or: ntpstats bench trace:{args.csv})",
              file=sys.stderr)
    st = tr.stats()
    if args.json:
        print(json.dumps(st, indent=2, default=float))
        return 0
    dur = st["duration_s"]
    span = f"{dur / 3600:.1f} h" if dur >= 7200 else f"{dur / 60:.0f} min" if dur >= 120 else f"{dur:.0f} s"
    print(f"{st['name']}: {st['exchanges']} exchanges over {span}, "
          f"every {format_seconds(st['interval_s'])}, loss {st['loss']:.1%}")
    print(f"{'direction':>16} {'floor':>10} {'median':>10} {'p99':>10} {'PDV p99':>10}")
    for key, label in (("to_ref", "to reference"), ("from_ref", "from reference")):
        d = st.get(key)
        if d:
            print(f"{label:>16} {format_seconds(d['floor']):>10} {format_seconds(d['median']):>10} "
                  f"{format_seconds(d['p99']):>10} {format_seconds(d['pdv_p99']):>10}")
    if "pdv_correlation" in st:
        print(f"correlation of the two directions: {st['pdv_correlation']:+.2f}")
    print(f"detrend: {st.get('detrend')}; floors assumed equal + asymmetry {format_seconds(st.get('asymmetry', 0.0))}"
          f" (two-way timestamps cannot measure it)")
    if st.get("clipped"):
        print(f"warning: {st['clipped']} delays came out negative and were set to 0 (check --detrend/--window)")
    return 0


def _time_value(v: str) -> float:
    from .timeerror import _value

    return _value(v)


def cmd_chain(args):
    from dataclasses import replace

    from . import ptpsim as P
    from .simulate import PathModel

    if args.scenario:
        from .bench import _load_file

        sc = P.chain_from_dict(_load_file(args.scenario), base_dir=os.path.dirname(os.path.abspath(args.scenario)))
    else:
        sc = P.ChainScenario()
    link = sc.link
    if args.asymmetry is not None:
        link = replace(link, asymmetry=args.asymmetry)
    if args.timestamp_noise is not None:
        link = replace(link, timestamp_noise=args.timestamp_noise)
    if args.pdv is not None:
        link = replace(link, pdv=PathModel(base=link.delay, queue_mean=args.pdv, load=0.5))
    if args.trace:
        from .trace import TracePath, load_trace

        link = replace(link, trace=TracePath(load_trace(args.trace), mode="bootstrap"))
    kw = {k: v for k, v in (("hops", args.hops), ("servo", args.servo), ("duration", args.duration),
                            ("sync_rate", args.sync_rate), ("delay_rate", args.delay_rate),
                            ("asymmetry_spread", args.asymmetry_spread), ("warmup", args.warmup),
                            ("seed", args.seed)) if v is not None}
    opts = dict(sc.servo_options)
    opts.update({k: v for k, v in (("kp", args.kp), ("ki", args.ki)) if v is not None})
    sc = replace(sc, link=link, servo_options=opts, **kw)
    res = P.simulate_chain(sc)
    limits = None
    if args.limits:
        from .timeerror import load_limits

        limits = load_limits(args.limits)
    verdict = res.check(limits=limits, cls=None if limits else args.cls, budget=args.budget)
    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as fh:
            fh.write("t," + ",".join(f"te_node{i}" for i in range(1, len(res.te))) + "\n")
            for k in range(0, res.t.size, max(1, int(round(sc.sync_rate)))):  # 1 row per second
                fh.write(f"{res.t[k]:.6f}," + ",".join(f"{x[k]:.6e}" for x in res.te[1:]) + "\n")
        print(f"wrote {args.csv} (time error of each node, local - grandmaster, s)", file=sys.stderr)
    if args.json:
        print(json.dumps({**res.as_dict(), "verdict": verdict}, indent=2, default=float))
        return 0 if verdict["passed"] else 3
    print(f"{sc.hops} boundary clocks, {sc.servo} servo, {sc.sync_rate:g} Sync/s, "
          f"{sc.delay_rate or sc.sync_rate:g} Delay_Req/s, "
          f"{sc.duration / 60:.0f} min (first {res.warmup:.0f} s excluded)")
    lt = P.lock_time(sc)
    if lt > res.warmup:
        print(f"note: these servo settings take about {lt:.0f} s to settle along a chain; run longer "
              f"(--duration {2 * lt:.0f}) or the numbers include locking")
    lim = verdict["limits"]
    bad = {(r["hop"], r["metric"]) for r in verdict["checks"] if not r["passed"]}
    print(f"{'node':>4} {'asym':>8} | {'max|TE|':>9} {'|cTE|':>9} {'dTE_L MTIE':>10} {'dTE_H pp':>9} | "
          f"{'hop adds max|TE|':>16} {'|cTE|':>9}  {'hop vs ' + (('class ' + args.cls) if not limits else 'limits')}")
    for n, h in zip(res.nodes, res.hops):
        flags = sorted(m for (hop, m) in bad if hop == h["hop"])
        mark = "ok" if not flags and lim else ("FAIL " + ",".join(flags) if flags else "-")
        print(f"{n['node']:>4} {format_seconds(h['asymmetry']):>8} | {format_seconds(n['max_te']):>9} "
              f"{format_seconds(n['cte']):>9} {format_seconds(n.get('dte_l_mtie', float('nan'))):>10} "
              f"{format_seconds(n['dte_h_pp']):>9} | {format_seconds(h['max_te']):>16} {format_seconds(h['cte']):>9}  {mark}")
    if "budget" in verdict:
        b = verdict["budget"]
        print(f"end of chain max|TE| {format_seconds(b['value'])} vs budget {format_seconds(b['limit'])}: "
              f"{'PASS' if b['passed'] else 'FAIL'} (margin {format_seconds(b['margin'])})")
    print("overall:", "PASS" if verdict["passed"] else "FAIL")
    return 0 if verdict["passed"] else 3


def cmd_cv(args):
    from .research import common_view

    def lines(p):
        import gzip

        op = gzip.open if p.endswith(".gz") else open
        with op(p, "rt", encoding="latin-1") as fh:
            return fh.read().splitlines()

    s = common_view(lines(args.a), lines(args.b), mode=args.mode, min_sats=args.min_sats)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(f"# {s.name}: {s.meta['quantity']} (ntpstats {__version__})\nunix_time,offset,satellites\n")
        for t, v, n in zip(s.t, s.offset, s.extra["satellites"]):
            fh.write(f"{t:.1f},{v:.12e},{int(n)}\n")
    print(f"{s.name}: {len(s)} epochs, mean {format_seconds(float(np.mean(s.offset)))}, "
          f"std {format_seconds(float(np.std(s.offset)))} -> {args.output}")
    return 0


def cmd_stability(args):
    kinds = args.kinds.split(",")
    for k in kinds:
        if k not in KINDS:
            raise SystemExit(f"unknown statistic {k}; choose from {', '.join(KINDS)}")
    taus = args.taus
    if "," in taus or taus.isdigit():
        taus = [int(v) for v in taus.split(",")]
    mask = None
    if args.mask:
        from .masks import load_mask

        mask = load_mask(args.mask, kind=args.mask_kind)
    all_out = []
    rc = 0
    for s in _load_args(args):
        results = series_stability(s, kinds=kinds, taus=taus, tau0=args.resample or args.tau0, max_gap=args.max_gap,
                                   detrend=args.detrend, ci=args.ci, max_work=0 if args.exact else None,
                                   bias_correction=not args.raw_mtot)
        for r in results:
            terms = r.meta.get("theobr_ratio_terms", [0, 0])
            if max(r.meta.get("stride") or [1]) > 1 or terms[0] < terms[1]:
                print(f"note: {r.kind} was sampled for speed (subsequence stride per tau {r.meta.get('stride')}"
                      f"{', TheoBR ratio terms %d of %d' % tuple(terms) if terms[0] < terms[1] else ''}); "
                      "--exact computes the full definition", file=sys.stderr)
        checks = {}
        if mask is not None:
            from .masks import check

            checks = {r.kind: check(r, mask) for r in results if r.kind == mask.kind}
            if not checks:
                print(f"note: mask {mask.name} is for {mask.kind.upper()}, which was not computed (-k)", file=sys.stderr)
            if any(c["passed"] is False for c in checks.values()):
                rc = 3
        if args.json:
            all_out.append({"name": s.name, "results": [dict(r.as_dict(), mask=checks.get(r.kind)) for r in results]})
            continue
        if args.csv:
            for r in results:
                r.to_csv(sys.stdout)
            continue
        meta = results[0].meta
        print(f"== {s.name}: tau0 = {results[0].tau0:.6g} s, grid {meta['grid_points']} points, "
              f"{meta['gap_points']} in gaps, regularity {meta['regularity']:.0%}")
        for r in results:
            print(f"-- {DESCRIPTIONS[r.kind]}" + (f"  ({r.ci:.1%} CI)" if r.ci else ""))
            c = checks.get(r.kind)
            head = f"   {'tau [s]':>12} {'dev':>12} {'lo':>12} {'hi':>12} {'n':>7}"
            print(head + (f" {'limit':>11} {'margin':>7}" if c else "") + "  noise")
            for i in range(r.taus.size):
                lo = f"{r.lo[i]:12.4e}" if r.lo is not None else " " * 12
                hi = f"{r.hi[i]:12.4e}" if r.hi is not None else " " * 12
                nz = NOISE_NAMES.get(int(r.alpha[i]), "") if r.alpha is not None and np.isfinite(r.alpha[i]) else ""
                extra = ""
                if c:
                    lim, mar = c["limit"][i], c["margin"][i]
                    extra = (f" {lim:11.3e} {mar:7.2f}" + ("" if mar >= 1 else " FAIL")) if lim else " " * 20
                print(f"   {r.taus[i]:12.6g} {r.dev[i]:12.4e} {lo} {hi} {int(r.n[i]):7d}{extra}  {nz}")
            if c:
                verdict = "n/a" if c["passed"] is None else ("PASS" if c["passed"] else "FAIL")
                print(f"   mask {c['mask']}: {verdict} (worst margin {c['worst_margin']})")
    if args.json:
        print(json.dumps(all_out, indent=2))
    return rc


def cmd_dynamic(args):
    from .stability import dynamic

    for s in _load_args(args):
        d = dynamic(s, kind=args.kind, window=args.window, step=args.step, detrend=args.detrend)
        if args.json:
            print(json.dumps(dict(d.as_dict(), name=s.name)))
            continue
        print("# " + s.name + f": {args.kind} window {d.window:g} s step {d.step:g} s")
        print("time," + ",".join(f"{t:g}" for t in d.taus))
        for t, row in zip(d.times, d.dev):
            print(f"{t:.3f}," + ",".join("" if not np.isfinite(v) else f"{v:.6e}" for v in row))


def cmd_plot(args):
    from .plotting import report_figure

    series = _load_args(args)
    fig = report_figure(series, kinds=args.kinds.split(","), detrend=args.detrend)
    fig.savefig(args.output, dpi=args.dpi)
    print(f"wrote {args.output}")


def cmd_network(args):
    from .analysis import detrend as _detrend
    from .network import delay_stats, floor_packet_percentage

    for s in _load_args(args):
        # offset statistics are meaningless while a frequency offset dominates
        s = TimeSeries(s.t, _detrend(s.t, s.offset, args.detrend or "linear"), s.name, s.source_format,
                       dict(s.extra), dict(s.meta))
        try:
            d = delay_stats(s, cluster=args.cluster)
        except ValueError as exc:
            print(f"{s.name}: {exc}", file=sys.stderr)
            continue
        if args.json:
            print(json.dumps({"name": s.name, **d}, indent=2))
            continue
        print(f"== {s.name}")
        print(f"   delay        min {format_seconds(d['delay_min'])}, median {format_seconds(d['delay_median'])}, "
              f"p95 {format_seconds(d['delay_p95'])}, max {format_seconds(d['delay_max'])}")
        print(f"   floor        {d['floor_fraction']:.1%} of packets within {format_seconds(d['cluster_width'])} of the floor")
        print(f"   offset std   all {format_seconds(d['offset_all_std'])}, floor packets {format_seconds(d['offset_at_floor_std'])}")
        print(f"   asymmetry    indicator {format_seconds(d['asymmetry_indicator'])}, "
              f"offset/delay correlation {d['offset_delay_correlation']:+.3f}")
        _, fpp = floor_packet_percentage(s, window=args.window, cluster=args.cluster or 150e-6)
        if fpp.size:
            print(f"   FPP          window {args.window:g} s: min {fpp.min():.1f}%, median {np.median(fpp):.1f}% "
                  f"({fpp.size} windows)")


def cmd_filter(args):
    from .filters import kalman_series
    from .network import min_delay_filter

    for s in _load_args(args):
        if args.method == "mindelay":
            out = min_delay_filter(s, args.window)
        else:
            out = kalman_series(s, smooth=args.method == "rts", delay_weighting=not args.no_delay_weighting)
        out.to_csv(args.output if args.output else sys.stdout)
        if args.output:
            print(f"wrote {args.output}", file=sys.stderr)


def cmd_simulate(args):
    from dataclasses import replace

    from .filters import kalman_series
    from .network import min_delay_filter
    from .simulate import PRESETS, simulate_ntp

    if args.scenario:
        from .bench import load_scenarios

        (_, sc), = load_scenarios([args.scenario])
        sc = replace(sc, seed=args.seed)
    else:
        sc = replace(PRESETS[args.preset], seed=args.seed)  # never mutate the shared presets
    if args.duration:
        sc = replace(sc, duration=args.duration)
    if args.poll:
        sc = replace(sc, poll=args.poll)
    meas, truth = simulate_ntp(sc, name=f"sim-{sc.name if args.scenario else args.preset}")
    if args.output:
        meas.to_csv(args.output)
        print(f"wrote {args.output} ({len(meas)} samples)")
    if args.benchmark:
        rows = {
            "raw measurements": meas,
            "Kalman": kalman_series(meas, delay_weighting=False),
            "Kalman + delay weighting": kalman_series(meas),
            "RTS smoother + delay weighting": kalman_series(meas, smooth=True),
            "min-delay filter (8)": min_delay_filter(meas),
        }
        if sc.protocol == "ptp":
            from .estimators import ptp4l, sptp

            rows["ptp4l (moving median, PI)"] = ptp4l(meas)
            rows["SPTP-style client (PI)"] = sptp(meas)
        what = "Syncs" if sc.protocol == "ptp" else "exchanges"
        print(f"Scenario '{args.preset}': {len(meas)} {what}, {'Sync interval' if sc.protocol == 'ptp' else 'poll'} "
              f"{sc.poll:g} s, seed {args.seed}")
        warm = min(300.0, sc.duration / 4) if sc.protocol == "ptp" else 0.0
        if warm:
            print(f"   (the first {warm:g} s, while the servos lock, are not scored)")
        print(f"   {'estimator':32} {'rms':>10} {'bias':>10} {'p95 |err|':>10} {'max |err|':>10}")
        for name, s in rows.items():
            c = compare(s.between(s.t[0] + warm, s.t[-1]) if warm else s, truth)
            print(f"   {name:32} {format_seconds(c['rms']):>10} {format_seconds(c['bias']):>10} "
                  f"{format_seconds(c['p95_abs']):>10} {format_seconds(c['max_abs']):>10}")


def cmd_query(args):
    from .sntp import KissOfDeath, NTPError, query

    rc = 0
    nts_sessions = {}
    if args.probe_v5:
        from .sntp import supports_v5

        for server in args.servers:
            try:
                ok = supports_v5(server, timeout=args.timeout, family=_family(args))
                print(f"{server}: NTPv5 ({'draft-09 upgrade supported' if ok else 'not offered'})")
            except (NTPError, OSError) as exc:
                print(f"{server}: {exc}")
                rc = 1
        return rc
    if args.pool:
        from .nts import NTSError, pool_sessions

        for server in args.servers:
            try:
                sessions = pool_sessions(server, n=args.pool, timeout=args.timeout, family=_family(args))
                for sess in sessions:
                    r = sess.query()
                    print(f"{server} -> {sess.keys.server}:{sess.keys.port} (denied: {', '.join(sess.deny) or '-'}): "
                          f"offset {format_seconds(r.offset)}, delay {format_seconds(r.delay)} [NTS authenticated]")
            except (NTSError, NTPError, OSError) as exc:
                print(f"{server}: {exc}")
                rc = 1
        return rc
    for server in args.servers:
        for i in range(args.count):
            if i:
                time.sleep(args.spacing)
            try:
                if args.nts:
                    from .nts import NTSSession

                    if server not in nts_sessions:
                        nts_sessions[server] = NTSSession(server, timeout=args.timeout, family=_family(args))
                    r = nts_sessions[server].query()
                elif args.interleaved:
                    from .sntp import query_interleaved

                    r = query_interleaved(server, timeout=args.timeout, family=_family(args))
                else:
                    r = query(server, timeout=args.timeout, version=5 if args.ntpv5 else 4, family=_family(args))
            except KissOfDeath as exc:
                print(f"{server}: {exc}")
                return 2
            except (NTPError, OSError) as exc:
                print(f"{server}: {exc}")
                rc = 1
                continue
            if args.json:
                print(json.dumps(r.as_dict()))
            else:
                v5 = f" NTPv5 {r.timescale} era {r.era} ({r.draft or 'no draft id'})" if r.version == 5 else ""
                v5 += " [NTS authenticated]" if r.auth == "nts" else ""
                if args.interleaved:
                    v5 += " [interleaved, RFC 9769]" if r.interleaved else " [server answered in basic mode]"
                print(f"{server} ({r.address}) stratum {r.stratum} refid {r.refid}: offset {format_seconds(r.offset)}, "
                      f"delay {format_seconds(r.delay)}, root delay {format_seconds(r.root_delay)}, "
                      f"root disp {format_seconds(r.root_dispersion)}, leap {r.leap}{v5}")
    return rc


def cmd_roughtime(args):
    from . import roughtime as rt

    if args.verify_report:
        with open(args.verify_report, encoding="utf-8") as fh:
            try:
                chain = rt.verify_report(json.load(fh))
            except (rt.RoughtimeError, KeyError, ValueError) as exc:
                print(f"invalid report: {exc}")
                return 1
        bad = rt.causal_violations(chain)
        print(f"{len(chain)} signed responses, chained in order; "
              + (f"{len(bad)} causal violations: malfeasance proven" if bad else "times consistent"))
        return 3 if bad else 0
    try:
        known = rt.load_servers(args.list)
        servers = [rt.Server.parse(x, known) for x in args.servers] if args.servers else known
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"roughtime: {exc}") from None
    m = rt.measure(servers, rounds=args.rounds, timeout=args.timeout, tcp=args.tcp, retries=args.retries,
                   family=_family(args))
    doc = m.as_dict()
    b = m.local_bound()
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        for r in m.responses:
            print(f"{r.server:28s} {_utc(r.midp)} UTC +- {r.radi:g} s  offset {r.offset:+.3f} s  "
                  f"(bound {r.bound:.3f} s, rtt {format_seconds(r.rtt)}, version {r.version:#x})")
        for name, err in m.errors:
            print(f"{name:28s} error: {err}")
        if m.responses:
            print(f"{len(m.responses)} signed responses: "
                  + ("consistent" if m.consistent else f"{len(m.violations)} CAUSAL VIOLATIONS (malfeasance)"))
            if b:
                print(f"local clock: true - local within [{b[0]:+.3f}, {b[1]:+.3f}] s")
    if not m.responses:
        return 1
    if not m.consistent and args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(m.malfeasance_report(), fh, indent=2)
        if not args.json:
            print(f"malfeasance report written to {args.report}")
    if not m.consistent or (args.check_local and (b is None or not b[0] <= 0 <= b[1])):
        return 3
    return 0


def cmd_monitor(args):
    from .monitor import MIN_PUBLIC_INTERVAL, Monitor

    if args.interval < MIN_PUBLIC_INTERVAL:
        print(f"note: polling faster than every {MIN_PUBLIC_INTERVAL:g} s is only appropriate for your own servers",
              file=sys.stderr)

    reg = _metrics(args)

    def show(r):
        if reg is not None:
            reg.observe_ntp(r)
        print(f"{_utc(r.t4)} {r.server:24} offset {format_seconds(r.offset):>10}  delay {format_seconds(r.delay):>10}",
              flush=True)

    def err(server, exc):
        if reg is not None:
            from .metrics import error_kind

            reg.error(server, error_kind(exc))
        print(f"{_utc(time.time())} {server:24} error: {exc}", file=sys.stderr, flush=True)

    m = Monitor(args.servers, args.interval, out_path=args.output, on_sample=show, on_error=err, count=args.count,
                version=5 if args.ntpv5 else 4, nts=args.nts)
    print(f"logging to {args.output}; Ctrl+C to stop", file=sys.stderr)
    try:
        m.run()
    except KeyboardInterrupt:
        pass


def _metrics(args):
    """Start the OpenMetrics endpoint (--metrics-port) and/or OTLP push (--otlp); returns the registry."""
    port, otlp = getattr(args, "metrics_port", None), getattr(args, "otlp", None)
    if not port and not otlp:
        return None
    from .metrics import Registry, serve

    reg = Registry(window=args.metrics_window)
    if port:
        serve(reg, args.metrics_host, port)
        print(f"metrics on http://{args.metrics_host}:{port}/metrics", file=sys.stderr)
    if otlp:
        import atexit

        from .otlp import Pusher

        pusher = Pusher(reg, None if otlp == "env" else otlp, interval=args.otlp_interval)
        pusher.start()
        atexit.register(pusher.stop)
        print(f"OpenTelemetry metrics to {pusher.url} every {args.otlp_interval:g} s", file=sys.stderr)
    return reg


def _metrics_args(s) -> None:
    s.add_argument("--metrics-port", type=int, metavar="PORT", help="serve OpenMetrics/Prometheus metrics on this port")
    s.add_argument("--metrics-host", default="127.0.0.1", help="address for --metrics-port (default 127.0.0.1)")
    s.add_argument("--metrics-window", type=int, default=1024, help="samples kept per source for rolling TDEV/stddev")
    s.add_argument("--otlp", nargs="?", const="env", metavar="URL",
                   help="push metrics to an OpenTelemetry collector over OTLP/HTTP (default: OTEL_EXPORTER_OTLP_* "
                        "environment, else http://localhost:4318)")
    s.add_argument("--otlp-interval", type=float, default=60.0, help="seconds between OTLP pushes (default 60)")


def cmd_watch(args):
    from .sources import LocalWatch

    reg = _metrics(args)

    def show(d):
        if reg is not None:
            reg.observe_watch(args.daemon, d)
        if "frequency_ppm" in d:
            tail = f"freq {d['frequency_ppm']:+.3f} ppm"
        elif d.get("source") in ("PPS", "TOFF"):
            tail = f"{d['source']} {d['device']}" + ("" if d.get("qerr") != d.get("qerr") else
                                                     f", qErr {format_seconds(d['qerr'])}")
        elif "min_uncertainty" in d:
            tail = f"{int(d['sources'])} sources, best ±{format_seconds(d['min_uncertainty'])}"
        else:
            tail = f"path delay {format_seconds(d.get('mean_path_delay', float('nan')))}"
        print(f"{_utc(d['time'])} {args.daemon:8} offset {format_seconds(d['offset']):>10}  {tail}", flush=True)

    def err(src, exc):
        if reg is not None:
            from .metrics import error_kind

            reg.error(args.daemon, error_kind(exc))
        print(f"{_utc(time.time())} {src}: {exc}", file=sys.stderr, flush=True)

    cmd = args.command_override.split() if args.command_override else None
    w = LocalWatch(args.daemon, args.interval, out_path=args.output, on_sample=show, on_error=err,
                   count=args.count, cmd=cmd)
    print(f"watching local {args.daemon}, logging to {args.output}; Ctrl+C to stop", file=sys.stderr)
    try:
        w.run()
    except KeyboardInterrupt:
        pass


def cmd_bench(args):
    from . import estimators as E
    from .bench import load_scenarios, run_bench, summarize, to_csv

    if args.list:
        print("estimators:")
        for name, e in sorted(E.available().items()):
            print(f"  {name:12} {'multi ' if e.multi else '      '}{e.description}")
        from .simulate import PRESETS

        print("preset scenarios: " + ", ".join(PRESETS))
        return 0
    seeds = []
    for part in args.seeds.split(","):
        a, _, b = part.partition("-")
        seeds += list(range(int(a), int(b) + 1)) if b else [int(a)]
    scen = load_scenarios(args.scenarios or ["internet"])
    names = args.estimators.split(",") if args.estimators else None
    rows = run_bench(scen, names, seeds, duration=args.duration, warmup=args.warmup,
                     progress=(lambda r: print(f"  {r['scenario']:>16} seed {r['seed']:<3} {r['estimator']:12} "
                                              f"rms {format_seconds(r['rms'])}", file=sys.stderr)) if args.verbose else None)
    table = summarize(rows)
    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as fh:
            fh.write(to_csv(rows))
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.html:
        from .report import bench_report

        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(bench_report(rows, table, params={"seeds": seeds, "scenarios": [n for n, _ in scen],
                                                       "duration": args.duration, "warmup": args.warmup}))
        print(f"wrote {args.html}", file=sys.stderr)
    if args.json:
        print(json.dumps(table, indent=2, default=float))
        return 0
    cur = None
    for r in table:
        if r["scenario"] != cur:
            cur = r["scenario"]
            print(f"\n== {cur}  ({r['runs']} seed(s))")
            print(f"   {'estimator':14} {'rms':>10} {'± seeds':>10} {'bias':>10} {'p95 |e|':>10} {'MTIE 1h':>10} {'time':>8}")
        print(f"   {r['estimator']:14} {format_seconds(r['rms']):>10} {format_seconds(r['rms_std']):>10} "
              f"{format_seconds(r['bias']):>10} {format_seconds(r['p95_abs']):>10} {format_seconds(r['mtie_1h']):>10} "
              f"{r['runtime_s'] * 1e3:>6.0f}ms")
    return 0


def cmd_report(args):
    from .report import dataset_report

    series = _load_args(args)
    doc = dataset_report(series, kinds=args.kinds.split(","), detrend=args.detrend, ci=args.ci, inputs=args.files,
                         title=args.title, time_error_section=args.time_error)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {args.output} ({len(doc) / 1024:.0f} kB, self-contained)")


def cmd_compare(args):
    """Error of one source against a reference (both from any supported log)."""
    from .analysis import compare as _compare
    from .stability import compute

    est = load_one(args.estimate, fmt=args.format, peer=args.peer)
    ref = load_one(args.reference, fmt=args.ref_format, peer=args.ref_peer)
    c = _compare(est, ref)
    r = ref.sorted()
    e = est.sorted().between(r.t[0], r.t[-1])
    err = TimeSeries(e.t, e.offset - np.interp(e.t, r.t, r.offset), name=f"{e.name} - {r.name}")
    _, x, tau0 = err.to_uniform()
    stats = {k: compute(x, tau0, k, "octave", ci=None) for k in ("tdev", "mtie")}
    if args.json:
        print(json.dumps({"estimate": est.name, "reference": ref.name, **c,
                          **{k: v.as_dict() for k, v in stats.items()}}, indent=2))
        return 0
    print(f"== {est.name}\n   vs reference {ref.name}  ({c['samples']} overlapping samples)")
    print(f"   error        bias {format_seconds(c['bias'])}, rms {format_seconds(c['rms'])}, std {format_seconds(c['std'])}, "
          f"p95 |e| {format_seconds(c['p95_abs'])}, max |e| {format_seconds(c['max_abs'])}")
    print(f"   {'tau [s]':>12} {'TDEV':>12} {'MTIE':>12}")
    mt = dict(zip(np.round(stats["mtie"].taus, 6), stats["mtie"].dev))
    for t, v in zip(stats["tdev"].taus, stats["tdev"].dev):
        print(f"   {t:12.6g} {format_seconds(v):>12} {format_seconds(mt.get(round(t, 6), float('nan'))):>12}")
    if args.output:
        err.to_csv(args.output)
        print(f"wrote error series to {args.output}")
    return 0


def cmd_ui(args):
    from .web.server import serve

    serve(args.files, host=args.host, port=args.port, open_browser=not args.no_browser, fmt=args.format)


# -------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ntpstats", description="NTP / network time offset and stability analysis toolkit")
    p.add_argument("--version", action="version", version=f"ntpstats {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="summary statistics of offset logs")
    _common(s)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("timeerror", aliases=["te"],
                       help="time-error metrics: max|TE|, cTE, dTE_L/dTE_H, max|TEL|, MTIE/TDEV of dTE_L")
    _common(s)
    s.add_argument("--limits", help="file of 'metric,value' limits (max_te, cte, cte_window, max_tel, dte_l_pp, "
                                    "dte_h_pp; e.g. '30ns'); exit code 3 on failure")
    s.add_argument("--mask", action="append", help="MTIE or TDEV mask CSV for dTE_L (repeatable)")
    s.add_argument("--lpf-hz", type=float, default=0.1, help="low-pass bandwidth for TEL/dTE_L (default 0.1 Hz)")
    s.add_argument("--cte-window", type=float, default=1000.0, help="cTE averaging window, s (default 1000)")
    s.add_argument("--input-is-te", action="store_true",
                   help="values are already TE = local - reference (e.g. a TIC measuring DUT - REF)")
    s.add_argument("--units", choices=("s", "ms", "us", "ns"), default="s", help="units of the input values")
    s.add_argument("--resample", type=float, metavar="TAU0", help="grid spacing (default: median sample interval)")
    s.add_argument("--max-gap", type=float, default=3.0, help="gaps longer than this many tau0 are not bridged")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_timeerror)

    s = sub.add_parser("audit", help="UTC traceability evidence: per-sample error bound, windows, coverage, "
                                     "HTML/JSON report with input hashes")
    _common(s)
    s.add_argument("--limit", required=True, help="maximum allowed error to UTC, e.g. 100us or 1ms")
    s.add_argument("--window", default="1h", help="evaluation window (default 1h)")
    s.add_argument("--reference-uncertainty", help="uncertainty of the top of the chain against UTC, e.g. 100ns")
    s.add_argument("--asymmetry", help="path-asymmetry allowance when the log has no delay column")
    s.add_argument("--upstream", help="source-to-UTC allowance when the log has no root delay/dispersion")
    s.add_argument("--max-gap", type=float, default=3.0, help="a sample covers at most this many median intervals")
    s.add_argument("--min-coverage", type=float, default=0.9, help="required monitored fraction (default 0.9)")
    s.add_argument("--events", action="store_true", help="list detected events (steps, route changes, ...)")
    s.add_argument("--html", help="write the report as a self-contained HTML file")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("events", help="detect phase steps, spikes, frequency changes, route changes and leap smears")
    _common(s)
    s.add_argument("--step-k", type=float, default=8.0, help="phase-step threshold in robust sigmas (default 8)")
    s.add_argument("--freq-threshold", type=float, default=5.0, help="CUSUM threshold for frequency changes")
    s.add_argument("--min-freq-change-ppm", type=float, default=0.1, help="smallest frequency change reported, ppm")
    s.add_argument("--floor-block", type=int, default=16, help="samples per block for delay-floor tracking")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_events)

    s = sub.add_parser("prom", help="fetch a Prometheus range query (e.g. ntpd-rs or chrony_exporter offsets) "
                                    "to a JSON file any command can read")
    s.add_argument("url", help="Prometheus base URL, e.g. http://localhost:9090")
    s.add_argument("query", help="PromQL, e.g. ntp_source_offset_seconds")
    s.add_argument("--since", default="24h", help="how far back when --start is not given (e.g. 6h, 7d)")
    s.add_argument("--start", type=_parse_time)
    s.add_argument("--end", type=_parse_time)
    s.add_argument("--step", default="60", help="resolution in seconds (default 60)")
    s.add_argument("--timeout", type=float, default=30.0)
    s.add_argument("-o", "--output", default="prometheus.json")
    s.set_defaults(func=cmd_prom)

    s = sub.add_parser("bounds", help="validate clock-error bounds (ClockBound, fbclock, CSV) against a reference")
    s.add_argument("bounds", help="ClockBound output lines, or CSV with earliest,latest[,unix_time,status]")
    s.add_argument("reference", help="better reference for the same host (PTP/PPS log, NTS monitor CSV, ...)")
    s.add_argument("--ref-format", default="auto", type=_fmt)
    s.add_argument("--ref-peer", help="select a source in a multi-peer reference log")
    s.add_argument("--negate-reference", action="store_true", help="the reference logs local - reference")
    s.add_argument("--ref-uncertainty", type=float, metavar="S",
                   help="reference uncertainty in s (default: half its round-trip delay, else 0)")
    s.add_argument("--max-gap", type=float, metavar="S", help="largest reference gap to interpolate across, s")
    s.add_argument("--max-violation-rate", type=float, default=0.0, help="exit code 3 above this rate (default 0)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_bounds)

    s = sub.add_parser("convert", help="write a log as a Stable32 data file (phase or frequency), plain CSV or Parquet")
    _common(s)
    s.add_argument("-o", "--output", required=True, help="output path; {n} is replaced by the series index")
    s.add_argument("--to", choices=("stable32-phase", "stable32-freq", "csv", "parquet", "omnetpp-vec", "ns3"),
                   default="stable32-phase")
    s.add_argument("--no-timetags", action="store_true", help="Stable32: values only, no MJD column")
    s.add_argument("--resample", type=float, metavar="TAU0", help="grid spacing (default: median sample interval)")
    s.add_argument("--max-gap", type=float, default=3.0, help="gaps longer than this many tau0 are marked as gaps")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("noise", help="fit the power-law noise model h_-2..h_2 (with intervals, corner taus); "
                       "--scenario writes an equivalent simulator clock")
    _common(s)
    s.add_argument("--kinds", default="oadev", help="statistics to fit (oadev, mdev, hdev, ...; default oadev)")
    s.add_argument("--spectrum", action="store_true", help="also fit the frequency spectrum S_y(f)")
    s.add_argument("--ci", type=float, default=0.95)
    s.add_argument("--bootstrap", type=int, default=100, help="bootstrap refits for the intervals (0: analytic, fast)")
    s.add_argument("--detrend", choices=("none", "linear", "quadratic"), default="linear")
    s.add_argument("--drift", action="store_true", help="also fit a linear frequency drift (so it is not taken for RW FM)")
    s.add_argument("--scenario", metavar="TOML", help="write a [clock] table with these h_alpha for 'simulate'")
    s.add_argument("--inet", metavar="INI", help="write omnetpp.ini lines for an INET RandomDriftOscillator with this "
                                                "random-walk FM (other noise types are listed as not representable)")
    s.add_argument("--inet-interval", type=float, default=1.0, help="changeInterval of the INET oscillator, s")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_noise)

    s = sub.add_parser("spectrum", aliases=["psd"], help="phase or frequency PSD (Welch or multitaper), L(f)")
    _common(s)
    s.add_argument("--kind", choices=("x", "y"), default="y", help="x: phase S_x(f); y: frequency S_y(f)")
    s.add_argument("--method", choices=("welch", "multitaper"), default="welch")
    s.add_argument("--per-decade", type=int, default=10, help="log-spaced bins per decade (0: raw ordinates)")
    s.add_argument("--carrier", type=float, metavar="HZ", help="with --kind x: also L(f) in dBc/Hz for this carrier")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_spectrum)

    s = sub.add_parser("hat", help="separate each source's stability from pairwise differences "
                       "(three-cornered hat, N-cornered hat, Groslambert covariance)")
    _common(s)
    s.add_argument("--method", choices=("gcov", "3ch", "nch"), default="gcov")
    s.add_argument("--ci", type=float, default=0.95)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_hat)

    s = sub.add_parser("holdover", help="predicted time error if the reference were lost now; time to violate limits")
    _common(s)
    s.add_argument("--limit", action="append", help="TIE limit, e.g. 1.1us (repeatable)")
    s.add_argument("--horizon", default="1d", help="how far to predict (e.g. 4h, 1d; default 1d)")
    s.add_argument("--window", help="fit frequency (and drift) over this much recent data (default: all)")
    s.add_argument("--model", choices=("frequency", "drift"), default="frequency",
                   help="what the clock applies in holdover: last frequency, or frequency and drift")
    s.add_argument("--source", choices=("offset", "frequency"), default="offset",
                   help="phase from the offset column, or integrate a frequency column (chrony tracking, ppm)")
    s.add_argument("--ci", type=float, default=0.95)
    s.add_argument("--uncertainty", type=int, default=40,
                   help="bootstrap noise models mixed into the envelope (0: point estimate only)")
    s.add_argument("--backtest", type=int, metavar="N", help="check calibration on N simulated losses in the log")
    s.add_argument("--min-holdover", metavar="DURATION", help="exit 3 unless the first limit holds this long")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_holdover)

    s = sub.add_parser("plugins", help="list installed plugins (parsers, estimators, detectors, masks, profiles)")
    s.add_argument("--all", action="store_true", help="also list the built-ins")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_plugins)

    s = sub.add_parser("dataset", help="summarise the open interop dataset (data/interop): availability, "
                       "offsets, protocol support per server")
    s.add_argument("path", nargs="?", default="data/interop")
    s.add_argument("--test", help="only this test (ntp4, nts, ntpv5, interleaved, nts-pool, roughtime)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_dataset)

    s = sub.add_parser("chain", help="simulate a PTP grandmaster and N boundary clocks (servo, sync rate, "
                       "asymmetry, PDV) and check the time error per hop and at the end; exit code 3 on failure")
    s.add_argument("--hops", type=int, help="number of boundary clocks (default 10)")
    s.add_argument("--servo", choices=("pi", "linreg"), help="slave servo (default pi, as linuxptp)")
    s.add_argument("--kp", type=float, help="PI proportional gain (1/s; default linuxptp's, ~1.6 at 16 Sync/s)")
    s.add_argument("--ki", type=float, help="PI integral gain per sample (default linuxptp's, ~0.1 at 16 Sync/s)")
    s.add_argument("--duration", type=_duration, help="simulated time, e.g. 3600 or 1h (default 1h)")
    s.add_argument("--sync-rate", type=float, help="Sync messages per second (default 16)")
    s.add_argument("--delay-rate", type=float, help="Delay_Req per second (default: the Sync rate)")
    s.add_argument("--asymmetry", type=_time_value, help="link asymmetry per hop, e.g. 10ns (master->slave longer)")
    s.add_argument("--asymmetry-spread", type=_time_value, help="random per-hop asymmetry within +-this, e.g. 20ns")
    s.add_argument("--timestamp-noise", type=_time_value, help="rms per timestamp, e.g. 4ns (default 4 ns)")
    s.add_argument("--pdv", type=_time_value, help="mean queueing delay between boundary clocks (switches without "
                                                  "PTP support), e.g. 2us")
    s.add_argument("--trace", help="replay the delays of a capture or log on every link (bootstrap)")
    s.add_argument("--class", dest="cls", choices=("A", "B", "C"), default="B",
                   help="per-hop limits of a G.8273.2 T-BC class (default B)")
    s.add_argument("--limits", help="file of per-hop 'metric,value' limits instead of a class "
                                    "(max_te, cte, dte_l_mtie, dte_h_pp, ...)")
    s.add_argument("--budget", type=_time_value, default=1.1e-6,
                   help="end-of-chain max|TE| budget (default 1.1us, the G.8271.1 network limit)")
    s.add_argument("--warmup", type=float, help="seconds excluded from the metrics (default: from the servo's "
                                                "lock time, at least 300 s)")
    s.add_argument("--scenario", help="TOML/JSON chain scenario ([chain], [chain.link], [chain.oscillator])")
    s.add_argument("--seed", type=int)
    s.add_argument("--csv", help="write the time error of every node (1 row per second)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_chain)

    s = sub.add_parser("sawtooth", help="remove the GNSS PPS quantization sawtooth with the receiver's qErr (u-blox TIM-TP)")
    s.add_argument("pps", help="time-interval-counter measurements of the receiver's PPS (any supported format)")
    s.add_argument("ubx", nargs="?", help="u-blox UBX log of the same period with UBX-TIM-TP messages "
                                           "(not needed when the PPS file has a qErr column, e.g. gpsd PPS)")
    s.add_argument("-f", "--format", default="auto", type=_fmt, help="format of the PPS file")
    s.add_argument("--peer", help="select a series of the PPS file")
    s.add_argument("--sign", choices=("auto", "+1", "-1"), default="auto",
                   help="sign with which qErr is applied (default: the one that removes the sawtooth)")
    s.add_argument("--max-dt", type=float, default=0.5, help="max time between a PPS sample and its qErr, s")
    s.add_argument("-o", "--output", help="write the corrected series as CSV (with qerr and uncorrected columns)")
    s.set_defaults(func=cmd_sawtooth)

    s = sub.add_parser("trace", help="extract per-direction network delays from a capture or log, to replay in "
                       "the bench (ntpstats bench trace:FILE)")
    s.add_argument("file", help="NTP/PTP capture, chrony measurements.log, peerstats, rawstats, or an exported trace")
    s.add_argument("-f", "--format", default="auto", type=_fmt, help=FORMAT_HELP)
    s.add_argument("--peer", help="select a peer/flow (substring of its address)")
    s.add_argument("--detrend", choices=("floor", "linear", "none"), default="floor",
                   help="how the clock offset between the two ends is removed (default floor: minimum-delay "
                        "exchanges per window)")
    s.add_argument("--window", type=float, help="detrend window, s (default max(16 exchanges, 900 s))")
    s.add_argument("--asymmetry", type=float, default=0.0,
                   help="known floor asymmetry, s (to-reference floor - from-reference floor)")
    s.add_argument("--csv", help="write the trace (unix_time,offset,delay,to_ref,from_ref)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_trace)

    s = sub.add_parser("cv", help="GNSS time transfer: REF(A) - REF(B) from two CGGTTS files (common view or all in view)")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--mode", choices=("cv", "aiv"), default="cv")
    s.add_argument("--min-sats", type=int, default=1, help="minimum common satellites per epoch (cv)")
    s.add_argument("-o", "--output", default="timetransfer.csv")
    s.set_defaults(func=cmd_cv)

    s = sub.add_parser("stability", aliases=["adev"], help="ADEV/MDEV/TDEV/HDEV/MTIE with confidence intervals")
    _common(s)
    s.add_argument("-k", "--kinds", default="oadev,mdev,tdev", help=f"comma list from {','.join(KINDS)}")
    s.add_argument("--taus", default="octave", help="octave|decade|dense|all or comma list of averaging factors")
    s.add_argument("--detrend", choices=("linear", "quadratic"), help="remove frequency offset / drift first")
    s.add_argument("--resample", type=float, metavar="TAU0", help="grid spacing (default: median sample interval)")
    s.add_argument("--max-gap", type=float, default=3.0, help="gaps longer than this many tau0 are not interpolated")
    s.add_argument("--ci", type=float, default=0.683, help="confidence level for intervals (0 disables)")
    s.add_argument("--mask", help="CSV of tau,limit to check against (exit code 3 on failure)")
    s.add_argument("--mask-kind", choices=KINDS, help="statistic the mask applies to (default: header, else tdev)")
    s.add_argument("--exact", action="store_true",
                   help="MTOT/Theo1/TheoBR/TheoH: use every subsequence and ratio term, however long it takes")
    s.add_argument("--raw-mtot", action="store_true",
                   help="MTOT/TTOT without the noise-type bias correction that Stable32 and NIST SP 1065 apply")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true")
    g.add_argument("--csv", action="store_true")
    s.set_defaults(func=cmd_stability)

    s = sub.add_parser("dynamic", help="sliding-window (dynamic) stability, CSV matrix time x tau")
    _common(s)
    s.add_argument("-k", "--kind", default="oadev", choices=[k for k in KINDS if k != "mtie"])
    s.add_argument("--window", type=float, help="window length, s (default: 1/8 of the record)")
    s.add_argument("--step", type=float, help="step, s (default: window/4)")
    s.add_argument("--detrend", choices=("linear", "quadratic"))
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_dynamic)

    s = sub.add_parser("plot", help="write a static report figure (PNG/PDF/SVG; needs matplotlib)")
    _common(s)
    s.add_argument("-o", "--output", default="ntpstats-report.png")
    s.add_argument("-k", "--kinds", default="oadev,mdev")
    s.add_argument("--detrend", choices=("linear", "quadratic"))
    s.add_argument("--dpi", type=int, default=150)
    s.set_defaults(func=cmd_plot)

    s = sub.add_parser("network", help="delay floor, asymmetry and floor-packet-percentage metrics")
    _common(s)
    s.add_argument("--cluster", type=float, help="cluster width above floor delay, s")
    s.add_argument("--window", type=float, default=200.0, help="FPP window, s (G.8260 uses 200 s)")
    s.add_argument("--detrend", choices=("linear", "quadratic"), help="trend removed before offset stats (default linear)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_network)

    s = sub.add_parser("filter", help="Kalman / RTS / min-delay filtering, output CSV")
    _common(s)
    s.add_argument("-m", "--method", choices=("kalman", "rts", "mindelay"), default="kalman")
    s.add_argument("--window", type=int, default=8, help="min-delay filter window (samples)")
    s.add_argument("--no-delay-weighting", action="store_true")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_filter)

    s = sub.add_parser("simulate", help="simulate NTP or PTP exchanges with ground truth; benchmark filters")
    s.add_argument("--preset", choices=("lan", "internet", "congested", "route-change", "falseticker", "ptp-lan", "ptp-tc"),
                   default="internet", help="ptp-* presets simulate PTP Sync/Delay_Req exchanges")
    s.add_argument("--scenario", metavar="TOML", help="scenario file (e.g. a [clock] with h_alpha from 'ntpstats noise')")
    s.add_argument("--duration", type=float, help="seconds")
    s.add_argument("--poll", type=float, help="seconds between exchanges")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("-o", "--output", help="write measurements as CSV (with true_offset column)")
    s.add_argument("--benchmark", action="store_true", help="score the built-in estimators against the truth")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("bench", help="benchmark estimators on simulated scenarios with ground truth")
    s.add_argument("scenarios", nargs="*", help="preset names or TOML/JSON scenario files (default: internet)")
    s.add_argument("-e", "--estimators", help="comma list (default: all registered, see --list)")
    s.add_argument("--seeds", default="1-3", help="e.g. 1-10 or 1,4,7")
    s.add_argument("--duration", type=float, help="override scenario duration, s")
    s.add_argument("--warmup", type=float, default=1800.0, help="seconds excluded from scoring (default 1800)")
    s.add_argument("--csv", help="write per-run rows")
    s.add_argument("--html", help="write a self-contained HTML report")
    s.add_argument("--json", action="store_true")
    s.add_argument("--list", action="store_true", help="list estimators and preset scenarios")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_bench)

    s = sub.add_parser("report", help="write a self-contained HTML report (offset, stability with CIs, network)")
    _common(s)
    s.add_argument("-o", "--output", default="ntpstats-report.html")
    s.add_argument("-k", "--kinds", default="oadev,mdev,tdev")
    s.add_argument("--detrend", choices=("linear", "quadratic"))
    s.add_argument("--ci", type=float, default=0.683)
    s.add_argument("--title", default="ntpstats report")
    s.add_argument("--time-error", action="store_true", help="add time-error metrics and a TE/TEL chart per dataset")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("compare", help="error of a source against a reference (e.g. NTP client vs PPS/GNSS)")
    s.add_argument("estimate", help="log with the offsets to evaluate")
    s.add_argument("reference", help="log with the reference offsets (same sign convention, overlapping time)")
    s.add_argument("-f", "--format", default="auto", type=_fmt)
    s.add_argument("--ref-format", default="auto", type=_fmt)
    s.add_argument("--peer")
    s.add_argument("--ref-peer")
    s.add_argument("-o", "--output", help="write the error series as CSV")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser("query", help="one-shot SNTP measurement")
    s.add_argument("servers", nargs="+")
    s.add_argument("-c", "--count", type=int, default=1)
    s.add_argument("--spacing", type=float, default=2.0)
    s.add_argument("--timeout", type=float, default=2.0)
    s.add_argument("--json", action="store_true")
    s.add_argument("--ntpv5", action="store_true", help="use the experimental NTPv5 draft-09 format")
    s.add_argument("--probe-v5", action="store_true", help="only test whether servers offer NTPv5 (upgrade probe)")
    s.add_argument("--pool", type=int, metavar="N",
                   help="NTS pool: N sessions with different servers, using NTS-KE server deny records")
    s.add_argument("--interleaved", action="store_true",
                   help="RFC 9769 interleaved mode (two exchanges; precise server transmit time when supported)")
    s.add_argument("--nts", action="store_true", help="authenticate with NTS, RFC 8915 (pip install 'ntpstats[nts]')")
    fam = s.add_mutually_exclusive_group()
    fam.add_argument("-4", dest="ipv4", action="store_true", help="IPv4 only")
    fam.add_argument("-6", dest="ipv6", action="store_true", help="IPv6 only")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("roughtime", help="signed coarse time from several Roughtime servers, "
                       "with chained nonces and malfeasance reports (draft-ietf-ntp-roughtime-19)")
    s.add_argument("servers", nargs="*", help="names from the list, or host:port=BASE64KEY (default: all listed)")
    s.add_argument("--list", metavar="JSON", help="server list (draft-19 format; default: bundled list)")
    s.add_argument("--rounds", type=int, default=2, help="query sequence repetitions (default 2, per the draft)")
    s.add_argument("--timeout", type=float, default=3.0)
    s.add_argument("--retries", type=int, default=0, help="retries with exponential backoff (1.5^n s)")
    s.add_argument("--tcp", action="store_true", help="use TCP (paths that drop 1 KiB datagrams)")
    s.add_argument("--report", metavar="FILE", help="write a malfeasance report here if servers disagree")
    s.add_argument("--verify-report", metavar="FILE", help="only verify a malfeasance report")
    s.add_argument("--check-local", action="store_true",
                   help="exit 3 if the local clock is outside what the signed responses allow")
    s.add_argument("--json", action="store_true")
    fam = s.add_mutually_exclusive_group()
    fam.add_argument("-4", dest="ipv4", action="store_true", help="IPv4 only")
    fam.add_argument("-6", dest="ipv6", action="store_true", help="IPv6 only")
    s.set_defaults(func=cmd_roughtime)

    s = sub.add_parser("monitor", help="poll servers periodically and log offsets to CSV")
    s.add_argument("servers", nargs="+")
    s.add_argument("-o", "--output", default="ntpstats-monitor.csv")
    s.add_argument("-i", "--interval", type=float, default=64.0)
    s.add_argument("-n", "--count", type=int, help="stop after N rounds")
    s.add_argument("--ntpv5", action="store_true", help="use the experimental NTPv5 draft-09 format")
    s.add_argument("--nts", action="store_true", help="authenticate with NTS, RFC 8915 (pip install 'ntpstats[nts]')")
    _metrics_args(s)
    s.set_defaults(func=cmd_monitor)

    s = sub.add_parser("watch", help="log the local chrony, ntpd/NTPsec, ntpd-rs, ptp4l or ptpcheck (no log files needed)")
    s.add_argument("daemon", choices=("chrony", "ntpd", "ntpd-rs", "ptp4l", "ptpcheck", "gpsd"),
                   help="chrony (chronyc), ntpd/NTPsec (ntpq), ntpd-rs (ntp-ctl, or --command-override URL of "
                        "its metrics exporter), ptp4l (linuxptp pmc), ptpcheck (facebook/time) or gpsd (PPS; "
                        "--command-override host:port)")
    s.add_argument("-o", "--output", default="ntpstats-watch.csv")
    s.add_argument("-i", "--interval", type=float, default=16.0)
    s.add_argument("-n", "--count", type=int, help="stop after N samples")
    s.add_argument("--command-override", metavar="CMD", help="e.g. 'ssh host chronyc' to watch a remote host")
    _metrics_args(s)
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("ui", help="start the local web UI")
    s.add_argument("files", nargs="*")
    s.add_argument("-f", "--format", default="auto", type=_fmt)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8123)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_ui)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "ci", None) == 0:
        args.ci = None
    try:
        rc = args.func(args)
    except BrokenPipeError:  # output piped into head & co.: stop quietly, like other Unix tools
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:  # a usage error, not a crash
        print(f"ntpstats: error: {exc.strerror or exc}: {exc.filename}", file=sys.stderr)
        return 2
    except (ParseError, ValueError) as exc:  # bad input or options: a message, not a traceback
        if os.environ.get("NTPSTATS_DEBUG"):
            raise
        print(f"ntpstats: error: {exc}", file=sys.stderr)
        return 2
    return int(rc or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
