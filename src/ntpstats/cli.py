# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""``ntpstats`` command-line interface."""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from typing import List, Optional

import numpy as np

from . import __version__
from .analysis import compare, format_seconds, remove_outliers, summary
from .parsers import FORMATS, ParseError, load, load_one
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
                raise SystemExit(f"{path}: {exc}")
        else:
            s = load(path, fmt=args.format, tau0=args.tau0)
        for x in s:
            if args.start is not None or args.end is not None:
                x = x.between(args.start, args.end)
            if args.outliers:
                x = remove_outliers(x, args.outliers)
            if len(x) < 3:
                raise SystemExit(f"{x.name}: fewer than 3 samples after filtering")
            out.append(x)
    return out


def _utc(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


def _common(p: argparse.ArgumentParser):
    p.add_argument("files", nargs="+", help="log files (loopstats, peerstats, rawstats, chrony logs, CSV...)")
    p.add_argument("-f", "--format", default="auto", choices=("auto",) + FORMATS, help="input format (default: auto-detect)")
    p.add_argument("--peer", help="select a peer/source (substring of its address) in multi-peer logs")
    p.add_argument("--all-peers", action="store_true", help="analyse every peer in multi-peer logs")
    p.add_argument("--start", type=_parse_time, help="ignore samples before this time (POSIX s or ISO 8601 UTC)")
    p.add_argument("--end", type=_parse_time, help="ignore samples after this time")
    p.add_argument("--outliers", type=float, metavar="K", help="drop samples more than K*MAD from the detrended median")
    p.add_argument("--tau0", type=float, help="sample interval for single-column files / resampling grid")


# ---------------------------------------------------------------- commands
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


def cmd_stability(args):
    kinds = args.kinds.split(",")
    for k in kinds:
        if k not in KINDS:
            raise SystemExit(f"unknown statistic {k}; choose from {', '.join(KINDS)}")
    taus = args.taus
    if "," in taus or taus.isdigit():
        taus = [int(v) for v in taus.split(",")]
    all_out = []
    for s in _load_args(args):
        results = series_stability(s, kinds=kinds, taus=taus, tau0=args.resample, max_gap=args.max_gap,
                                   detrend=args.detrend, ci=args.ci)
        if args.json:
            all_out.append({"name": s.name, "results": [r.as_dict() for r in results]})
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
            print(f"   {'tau [s]':>12} {'dev':>12} {'lo':>12} {'hi':>12} {'n':>7}  noise")
            for i in range(r.taus.size):
                lo = f"{r.lo[i]:12.4e}" if r.lo is not None else " " * 12
                hi = f"{r.hi[i]:12.4e}" if r.hi is not None else " " * 12
                nz = NOISE_NAMES.get(int(r.alpha[i]), "") if r.alpha is not None and np.isfinite(r.alpha[i]) else ""
                print(f"   {r.taus[i]:12.6g} {r.dev[i]:12.4e} {lo} {hi} {int(r.n[i]):7d}  {nz}")
    if args.json:
        print(json.dumps(all_out, indent=2))


def cmd_plot(args):
    from .plotting import report_figure

    series = _load_args(args)
    fig = report_figure(series, kinds=args.kinds.split(","), detrend=args.detrend)
    fig.savefig(args.output, dpi=args.dpi)
    print(f"wrote {args.output}")


def cmd_network(args):
    from .network import delay_stats, floor_packet_percentage

    for s in _load_args(args):
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
    from .filters import kalman_series
    from .network import min_delay_filter
    from .simulate import PRESETS, simulate_ntp

    sc = PRESETS[args.preset]
    if args.duration:
        sc.duration = args.duration
    if args.poll:
        sc.poll = args.poll
    sc.seed = args.seed
    meas, truth = simulate_ntp(sc, name=f"sim-{args.preset}")
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
        print(f"Scenario '{args.preset}': {len(meas)} exchanges, poll {sc.poll:g} s, seed {args.seed}")
        print(f"   {'estimator':32} {'rms':>10} {'bias':>10} {'p95 |err|':>10} {'max |err|':>10}")
        for name, s in rows.items():
            c = compare(s, truth)
            print(f"   {name:32} {format_seconds(c['rms']):>10} {format_seconds(c['bias']):>10} "
                  f"{format_seconds(c['p95_abs']):>10} {format_seconds(c['max_abs']):>10}")


def cmd_query(args):
    from .sntp import KissOfDeath, NTPError, query

    rc = 0
    for server in args.servers:
        for i in range(args.count):
            if i:
                time.sleep(args.spacing)
            try:
                r = query(server, timeout=args.timeout)
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
                print(f"{server} ({r.address}) stratum {r.stratum} refid {r.refid}: offset {format_seconds(r.offset)}, "
                      f"delay {format_seconds(r.delay)}, root delay {format_seconds(r.root_delay)}, "
                      f"root disp {format_seconds(r.root_dispersion)}, leap {r.leap}")
    return rc


def cmd_monitor(args):
    from .monitor import MIN_PUBLIC_INTERVAL, Monitor

    if args.interval < MIN_PUBLIC_INTERVAL:
        print(f"note: polling faster than every {MIN_PUBLIC_INTERVAL:g} s is only appropriate for your own servers",
              file=sys.stderr)

    def show(r):
        print(f"{_utc(r.t4)} {r.server:24} offset {format_seconds(r.offset):>10}  delay {format_seconds(r.delay):>10}",
              flush=True)

    def err(server, exc):
        print(f"{_utc(time.time())} {server:24} error: {exc}", file=sys.stderr, flush=True)

    m = Monitor(args.servers, args.interval, out_path=args.output, on_sample=show, on_error=err, count=args.count)
    print(f"logging to {args.output}; Ctrl+C to stop", file=sys.stderr)
    try:
        m.run()
    except KeyboardInterrupt:
        pass


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

    s = sub.add_parser("stability", aliases=["adev"], help="ADEV/MDEV/TDEV/HDEV/MTIE with confidence intervals")
    _common(s)
    s.add_argument("-k", "--kinds", default="oadev,mdev,tdev", help=f"comma list from {','.join(KINDS)}")
    s.add_argument("--taus", default="octave", help="octave|decade|dense|all or comma list of averaging factors")
    s.add_argument("--detrend", choices=("linear", "quadratic"), help="remove frequency offset / drift first")
    s.add_argument("--resample", type=float, metavar="TAU0", help="grid spacing (default: median sample interval)")
    s.add_argument("--max-gap", type=float, default=3.0, help="gaps longer than this many tau0 are not interpolated")
    s.add_argument("--ci", type=float, default=0.683, help="confidence level for intervals (0 disables)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true")
    g.add_argument("--csv", action="store_true")
    s.set_defaults(func=cmd_stability)

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
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_network)

    s = sub.add_parser("filter", help="Kalman / RTS / min-delay filtering, output CSV")
    _common(s)
    s.add_argument("-m", "--method", choices=("kalman", "rts", "mindelay"), default="kalman")
    s.add_argument("--window", type=int, default=8, help="min-delay filter window (samples)")
    s.add_argument("--no-delay-weighting", action="store_true")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_filter)

    s = sub.add_parser("simulate", help="simulate NTP exchanges with ground truth; benchmark filters")
    s.add_argument("--preset", choices=("lan", "internet", "congested"), default="internet")
    s.add_argument("--duration", type=float, help="seconds")
    s.add_argument("--poll", type=float, help="seconds between exchanges")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("-o", "--output", help="write measurements as CSV (with true_offset column)")
    s.add_argument("--benchmark", action="store_true", help="score the built-in estimators against the truth")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("query", help="one-shot SNTP measurement")
    s.add_argument("servers", nargs="+")
    s.add_argument("-c", "--count", type=int, default=1)
    s.add_argument("--spacing", type=float, default=2.0)
    s.add_argument("--timeout", type=float, default=2.0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("monitor", help="poll servers periodically and log offsets to CSV")
    s.add_argument("servers", nargs="+")
    s.add_argument("-o", "--output", default="ntpstats-monitor.csv")
    s.add_argument("-i", "--interval", type=float, default=64.0)
    s.add_argument("-n", "--count", type=int, help="stop after N rounds")
    s.set_defaults(func=cmd_monitor)

    s = sub.add_parser("ui", help="start the local web UI")
    s.add_argument("files", nargs="*")
    s.add_argument("-f", "--format", default="auto", choices=("auto",) + FORMATS)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8123)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_ui)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "ci", None) == 0:
        args.ci = None
    rc = args.func(args)
    return int(rc or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
