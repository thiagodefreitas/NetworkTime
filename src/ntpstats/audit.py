# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""UTC traceability evidence: a per-sample error bound, windows, coverage and an archivable report.

Regulated users (e.g. MiFID II RTS 25: 100 us / 1 ms to UTC; DORA and NIS2
for trustworthy logs) need a **bound**, not just an offset. For each sample::

    bound = |offset| + path + upstream + reference

``path``
    how wrong the offset can be because the network path is asymmetric:
    half the round-trip ``delay`` when the log has it (the worst case is all
    delay in one direction), else ``asymmetry`` given by the user, else 0
    (reported as an assumption).
``upstream``
    how far the source itself can be from its reference:
    ``root_delay / 2 + root_dispersion`` when the log has them (chrony, the
    ntpstats monitor, NTP/NTS servers), else the peer ``dispersion`` (ntpd
    peerstats), else ``upstream`` given by the user, else 0.
``reference``
    the uncertainty of the top of the chain against UTC (e.g. of a GNSS
    receiver or UTC(k)), given by the user.

Time is cut into windows (1 h by default). A sample covers the time until
the next sample, but at most ``max_gap`` median intervals; the rest is
**unmonitored** and never counts as compliant. A window fails when any
bound exceeds the limit, and is *insufficient* when its coverage is below
``min_coverage``.

The report states every assumption it applied, and carries the tool version
and SHA-256 hashes of the inputs, so it can be archived and reproduced. It
describes measurements; interpreting a regulation is up to its user.
"""

from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from . import __version__
from .analysis import format_seconds
from .series import TimeSeries


@dataclass
class AuditConfig:
    limit: float
    window: float = 3600.0
    reference_uncertainty: float = 0.0
    asymmetry: Optional[float] = None
    upstream: Optional[float] = None
    max_gap: float = 3.0
    min_coverage: float = 0.9


def components(s: TimeSeries, cfg: AuditConfig) -> Dict[str, Any]:
    """Per-sample bound terms and the rules that produced them."""
    n = len(s)
    ex = s.extra
    notes: List[str] = []
    if "delay" in ex and np.isfinite(ex["delay"]).any():
        path = np.abs(ex["delay"]) / 2
        path_rule = "half the round-trip delay (log column 'delay')"
    elif cfg.asymmetry is not None:
        path = np.full(n, float(cfg.asymmetry))
        path_rule = f"user-supplied asymmetry allowance {format_seconds(cfg.asymmetry)}"
    else:
        path = np.zeros(n)
        path_rule = "none: the log has no delay and no --asymmetry was given"
        if s.source_format != "chrony-tracking":
            notes.append("No path-asymmetry term: the bound assumes a symmetric path.")
    if "root_delay" in ex or "root_dispersion" in ex:
        rd = np.abs(ex.get("root_delay", np.zeros(n)))
        rdisp = np.abs(ex.get("root_dispersion", np.zeros(n)))
        upstream = rd / 2 + rdisp
        up_rule = "root_delay/2 + root_dispersion (log columns)"
    elif "dispersion" in ex:
        upstream = np.abs(ex["dispersion"])
        up_rule = "peer dispersion (log column); the peer's own root distance is not in the log"
        if cfg.upstream is not None:
            upstream = upstream + float(cfg.upstream)
            up_rule += f" + user-supplied upstream {format_seconds(cfg.upstream)}"
    elif cfg.upstream is not None:
        upstream = np.full(n, float(cfg.upstream))
        up_rule = f"user-supplied upstream allowance {format_seconds(cfg.upstream)}"
    else:
        upstream = np.zeros(n)
        up_rule = "none: the log has no root delay/dispersion and no --upstream was given"
        notes.append("No upstream term: the source is assumed to be exactly on UTC.")
    ref = np.full(n, float(cfg.reference_uncertainty))
    if not cfg.reference_uncertainty:
        notes.append("Reference uncertainty is 0: set --reference-uncertainty for the top of the chain.")
    return {"offset": np.abs(s.offset), "path": np.nan_to_num(path), "upstream": np.nan_to_num(upstream),
            "reference": ref,
            "rules": {"path": path_rule, "upstream": up_rule,
                      "reference": f"{format_seconds(cfg.reference_uncertainty)} (user-supplied)"},
            "notes": notes}


def audit(s: TimeSeries, cfg: AuditConfig, events: Optional[list] = None) -> Dict[str, Any]:
    """Audit one series; returns a JSON-serialisable dict."""
    s = s.sorted()
    if len(s) < 2:
        raise ValueError("need at least 2 samples")
    c = components(s, cfg)
    bound = c["offset"] + c["path"] + c["upstream"] + c["reference"]
    t = s.t
    med = float(np.median(np.diff(t)))
    gapmax = cfg.max_gap * med
    cover = np.minimum(np.append(np.diff(t), med), gapmax)  # time each sample vouches for
    ok = bound <= cfg.limit
    w0 = np.floor(t[0] / cfg.window) * cfg.window
    nwin = int(np.ceil((t[-1] + cover[-1] - w0) / cfg.window))
    windows = []
    for k in range(nwin):
        a, b = w0 + k * cfg.window, w0 + (k + 1) * cfg.window
        span_a, span_b = max(a, t[0]), min(b, t[-1] + cover[-1])
        length = max(span_b - span_a, 0.0)
        inw = (t >= a) & (t < b)
        # clip each sample's coverage to the window
        cov = float(np.sum(np.clip(np.minimum(t[inw] + cover[inw], b) - t[inw], 0, None)))
        coverage = cov / length if length > 0 else 0.0
        if inw.any() and np.any(~ok[inw]):
            status = "fail"
        elif coverage >= cfg.min_coverage and inw.any():
            status = "pass"
        else:
            status = "insufficient"
        windows.append({"start": a, "end": b, "samples": int(inw.sum()), "coverage": coverage,
                        "max_bound": float(bound[inw].max()) if inw.any() else None,
                        "max_abs_offset": float(c["offset"][inw].max()) if inw.any() else None,
                        "status": status})
    total = t[-1] + cover[-1] - t[0]
    monitored = float(cover.sum())
    within = float(cover[ok].sum())
    worst = np.argsort(bound)[::-1][:10]
    fails = sum(w["status"] == "fail" for w in windows)
    insufficient = sum(w["status"] == "insufficient" for w in windows)
    coverage = monitored / total if total > 0 else 0.0
    passed = fails == 0 and coverage >= cfg.min_coverage
    return {
        "name": s.name, "source_format": s.source_format, "samples": len(s),
        "start": float(t[0]), "end": float(t[-1]), "median_interval": med,
        "limit": cfg.limit, "window": cfg.window, "min_coverage": cfg.min_coverage, "max_gap_intervals": cfg.max_gap,
        "rules": c["rules"], "notes": c["notes"],
        "summary": {
            "passed": bool(passed), "coverage": coverage, "unmonitored_s": float(total - monitored),
            "within_limit_fraction_of_period": within / total if total > 0 else 0.0,
            "within_limit_fraction_of_monitored": within / monitored if monitored > 0 else 0.0,
            "max_bound": float(bound.max()), "median_bound": float(np.median(bound)),
            "p99_bound": float(np.percentile(bound, 99)),
            "windows": len(windows), "failing_windows": int(fails), "insufficient_windows": int(insufficient),
        },
        "worst": [{"time": float(t[i]), "bound": float(bound[i]), "offset": float(s.offset[i]),
                   "path": float(c["path"][i]), "upstream": float(c["upstream"][i]),
                   "reference": float(c["reference"][i])} for i in worst],
        "windows": windows,
        "events": [e.as_dict() for e in events] if events else [],
        "_t": t, "_bound": bound,
    }


def _sha256(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(paths: Sequence[str]) -> List[Dict[str, Any]]:
    return [{"path": os.path.basename(p), "sha256": _sha256(p), "bytes": os.path.getsize(p)}
            for p in paths if os.path.isfile(p)]


def public(result: Dict[str, Any]) -> Dict[str, Any]:
    """The result without the plotting arrays."""
    return {k: v for k, v in result.items() if not k.startswith("_")}


def to_html(results: List[Dict[str, Any]], inputs: Sequence[str], title: str = "ntpstats UTC traceability audit") -> str:
    from .report import PALETTE, _cards, _decimate, _f, _shell, _table

    charts: List[dict] = []
    utc = lambda v: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(v))  # noqa: E731
    overall = all(r["summary"]["passed"] for r in results)
    body = [f"<h1>{html.escape(title)}</h1>",
            f'<div class="meta">Verdict: <b>{"PASS" if overall else "FAIL"}</b> · limit {format_seconds(results[0]["limit"])}'
            f' · window {results[0]["window"] / 3600:g} h · min coverage {results[0]["min_coverage"]:.0%}</div>',
            "<p class='meta'>This report describes measurements and the assumptions listed below. "
            "Interpreting a regulation (e.g. MiFID II RTS 25, DORA, NIS2) is up to its reader.</p>"]
    for i, r in enumerate(results):
        sm = r["summary"]
        body.append(f"<h2>{html.escape(r['name'])} <span class=meta>({html.escape(r['source_format'])}, "
                    f"{utc(r['start'])} .. {utc(r['end'])} UTC)</span></h2>")
        body.append(_cards([
            ("Result", "PASS" if sm["passed"] else "FAIL"), ("Max bound", format_seconds(sm["max_bound"])),
            ("p99 bound", format_seconds(sm["p99_bound"])), ("Median bound", format_seconds(sm["median_bound"])),
            ("Coverage", f"{sm['coverage']:.2%}"), ("Unmonitored", f"{sm['unmonitored_s'] / 3600:.2f} h"),
            ("Within limit (of period)", f"{sm['within_limit_fraction_of_period']:.2%}"),
            ("Failing windows", f"{sm['failing_windows']} / {sm['windows']}"),
        ]))
        idx = _decimate(r["_t"], r["_bound"])
        charts.append({"id": f"b{i}", "kind": "time", "x": _f(r["_t"][idx]), "xlabel": "time", "ylabel": "bound",
                       "yfmt": "sec", "series": [
                           {"label": "error bound", "y": _f(r["_bound"][idx]), "color": PALETTE[0], "width": 1},
                           {"label": "limit", "y": [r["limit"]] * int(idx.size), "color": PALETTE[3], "width": 1.5}]})
        body.append(f'<div class="chart" id="b{i}"></div>')
        body.append("<h3>Assumptions applied</h3>" + _table(["term", "rule"], [[k, v] for k, v in r["rules"].items()]))
        for n in r["notes"]:
            body.append(f"<p class='meta'>Note: {html.escape(n)}</p>")
        body.append("<h3>Windows</h3>" + _table(
            ["start (UTC)", "samples", "coverage", "max bound", "status"],
            [[utc(w["start"]), w["samples"], f"{w['coverage']:.1%}",
              format_seconds(w["max_bound"]) if w["max_bound"] is not None else "–", w["status"].upper()]
             for w in r["windows"]]))
        body.append("<h3>Largest bounds</h3>" + _table(
            ["time (UTC)", "bound", "offset", "path", "upstream", "reference"],
            [[utc(x["time"]), format_seconds(x["bound"]), format_seconds(x["offset"]), format_seconds(x["path"]),
              format_seconds(x["upstream"]), format_seconds(x["reference"])] for x in r["worst"]]))
        if r["events"]:
            body.append("<h3>Events in the period</h3>" + _table(
                ["time (UTC)", "event", "size"],
                [[utc(e["time"]), e["kind"], f"{e['magnitude']:.3g} {e['unit']}"] for e in r["events"]]))
    man = manifest(inputs)
    if man:
        body.append("<h2>Inputs</h2>" + _table(["file", "bytes", "sha256"], [[m["path"], m["bytes"], m["sha256"]] for m in man]))
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "version": __version__,
            "inputs": man, "audit": [public(r) for r in results]}
    return _shell(title, "\n".join(body), charts, meta)
