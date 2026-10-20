# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Fleet view: many hosts at once, ranked by how close each is to its limits.

Each host (a log, or a series of a multi-source file such as a Prometheus
range query of the exporter) is assessed over its most recent ``window``
seconds against the same thresholds:

``max_offset``
    the largest ``|offset|`` in the window, reference - local;
``max_jitter``
    the standard deviation of the offset in the window (what the exporter
    publishes as ``ntpstats_offset_stddev_seconds``);
``max_bound``
    the largest error bound in the window, ``|offset| + delay/2 +
    root_delay/2 + root_dispersion`` from the columns the log has (the same
    terms as :mod:`ntpstats.audit` and the exporter's
    ``ntpstats_offset_bound_seconds``);
``max_age``
    the time since the last sample, relative to ``now``;
``mask``
    a TDEV or MTIE limit mask (:mod:`ntpstats.masks`) checked on the window.

A host **fails** when a threshold is exceeded, is **stale** when its last
sample is older than ``max_age``, and is **ok** otherwise. Hosts are ranked
by their worst *usage* (value / threshold), so the host closest to a limit
comes first even when every host passes. :func:`alert_rules` writes
Prometheus alerting rules with the same thresholds for the exporter's
metrics, so the fleet report and the alerts agree.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .series import TimeSeries

VERDICT_ORDER = {"fail": 0, "stale": 1, "ok": 2, "unchecked": 3}


@dataclass
class Thresholds:
    """Limits every host is checked against (``None`` skips a check)."""

    max_offset: Optional[float] = 1e-3
    max_jitter: Optional[float] = None
    max_bound: Optional[float] = None
    max_age: Optional[float] = None
    mask: Optional[Any] = None  # masks.Mask
    window: Optional[float] = 86400.0
    limits: Dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.limits = {k: float(v) for k, v in (("offset", self.max_offset), ("jitter", self.max_jitter),
                                                ("bound", self.max_bound), ("age", self.max_age)) if v is not None}


def host_of(s: TimeSeries) -> str:
    """A host name for a series: its Prometheus ``instance`` label, else its file name."""
    labels = s.meta.get("labels")
    if isinstance(labels, str):  # Prometheus range queries: "k=v,k=v"
        labels = dict(kv.split("=", 1) for kv in labels.split(",") if "=" in kv)
    if isinstance(labels, dict):
        for k in ("instance", "host", "hostname", "node"):
            if labels.get(k):
                return str(labels[k])
    return str(s.meta.get("file") or s.name)


def hosts_of_paths(paths: Sequence[str]) -> List[str]:
    """Host names for log files: the file's directory when the files sit in
    different directories (one directory per host), else the file name."""
    dirs = {os.path.dirname(os.path.abspath(p)) for p in paths}
    if len(dirs) > 1:
        return [os.path.basename(os.path.dirname(os.path.abspath(p))) for p in paths]
    return [os.path.basename(p) for p in paths]


def assess(s: TimeSeries, th: Thresholds, now: Optional[float] = None, host: Optional[str] = None) -> Dict[str, Any]:
    """One host against the thresholds; see the module docstring."""
    from .audit import AuditConfig, components

    row: Dict[str, Any] = {"host": host or host_of(s), "source": s.name, "format": s.source_format,
                           "peer": s.meta.get("peer")}
    if len(s) == 0:
        return dict(row, samples=0, verdict="unchecked", reasons=["no samples"], usage=None)
    end = float(s.t[-1])
    w = s.between(end - th.window, None) if th.window else s
    row.update(samples=len(w), start=float(w.t[0]), end=end, span=float(w.t[-1] - w.t[0]))
    off = np.asarray(w.offset, dtype=float)
    fin = np.isfinite(off)
    if not fin.any():
        return dict(row, verdict="unchecked", reasons=["no finite offsets in the window"], usage=None)
    o = off[fin]
    c = components(w, AuditConfig(limit=1.0))
    bound = (c["offset"] + c["path"] + c["upstream"] + c["reference"])[fin]
    has_bound = c["rules"]["path"].startswith("half") or not c["rules"]["upstream"].startswith("none")
    row.update(offset_median=float(np.median(o)), offset_max_abs=float(np.max(np.abs(o))),
               jitter=float(np.std(o)) if o.size > 1 else 0.0,
               bound_max=float(np.max(bound)) if has_bound else None,
               age=(float(now) - end) if now is not None else None)
    values = {"offset": row["offset_max_abs"], "jitter": row["jitter"], "bound": row["bound_max"], "age": row["age"]}
    usage: Dict[str, float] = {}
    reasons: List[str] = []
    for k, lim in th.limits.items():
        v = values[k]
        if v is None:
            continue
        usage[k] = v / lim if lim > 0 else float("inf")
        if v > lim:
            reasons.append(f"{k} {_fmt(v, k)} > {_fmt(lim, k)}")
    if th.mask is not None:
        row["mask"] = _mask(w, th.mask)
        if row["mask"].get("usage") is not None:
            usage["mask"] = row["mask"]["usage"]
        if row["mask"].get("passed") is False:
            reasons.append(f"{th.mask.kind.upper()} mask {th.mask.name} failed")
    stale = "age" in th.limits and row["age"] is not None and row["age"] > th.limits["age"]
    failed = any(not r.startswith("age") for r in reasons)
    row["verdict"] = "fail" if failed else "stale" if stale else "ok" if usage else "unchecked"
    row["reasons"] = reasons
    row["usage_by"] = usage
    row["usage"] = max(usage.values()) if usage else None
    row["worst"] = max(usage, key=lambda k: usage[k]) if usage else None
    return row


def format_age(v: float) -> str:
    """A duration for people: s, min, h or d."""
    for unit, size in (("y", 31557600.0), ("d", 86400.0), ("h", 3600.0), ("min", 60.0)):
        if abs(v) >= 2 * size:
            return f"{v / size:.3g} {unit}"
    return f"{v:.3g} s"


def _fmt(v: float, kind: str) -> str:
    from .analysis import format_seconds

    return format_age(v) if kind == "age" else format_seconds(v)


def _mask(s: TimeSeries, mask) -> Dict[str, Any]:
    from .masks import check
    from .stability import series_stability

    try:
        (res,) = series_stability(s, kinds=(mask.kind,), ci=0.95)
    except (ValueError, IndexError) as exc:
        return {"name": mask.name, "kind": mask.kind, "passed": None, "error": str(exc), "usage": None}
    r = check(res, mask)
    worst = r.get("worst_margin")
    return {"name": mask.name, "kind": mask.kind, "passed": r.get("passed"),
            "usage": float(1.0 / worst) if worst else None}


def fleet(series: Sequence[TimeSeries], th: Thresholds, now: Optional[float] = None,
          hosts: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Assess every series and rank them: failures first, then stale hosts,
    then by usage of the nearest limit (highest first)."""
    if now is None:
        now = time.time()
    rows = [dict(assess(s, th, now=now, host=hosts[i] if hosts else None), index=i) for i, s in enumerate(series)]
    rows.sort(key=lambda r: (VERDICT_ORDER.get(r["verdict"], 9), -(r["usage"] if r["usage"] is not None else -1.0),
                             r["host"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    out = {k: 0 for k in VERDICT_ORDER}
    for r in rows:
        out[r["verdict"]] = out.get(r["verdict"], 0) + 1
    out["hosts"] = len(rows)
    return out


def alert_rules(th: Thresholds, group: str = "ntpstats-fleet", for_: str = "10m") -> str:
    """Prometheus alerting rules (YAML) for the exporter's metrics
    (:mod:`ntpstats.metrics`) with the same thresholds as the fleet view."""
    from .analysis import format_seconds

    rules = []
    lim = th.limits
    if "offset" in lim:
        rules.append(("NtpstatsFleetOffset", f"abs(ntpstats_offset_seconds) > {lim['offset']:.6g}", for_, "critical",
                      f"|offset| of {{{{ $labels.source }}}} on {{{{ $labels.instance }}}} above "
                      f"{format_seconds(lim['offset'])}"))
    if "jitter" in lim:
        rules.append(("NtpstatsFleetJitter", f"ntpstats_offset_stddev_seconds > {lim['jitter']:.6g}", for_, "warning",
                      f"offset jitter of {{{{ $labels.source }}}} on {{{{ $labels.instance }}}} above "
                      f"{format_seconds(lim['jitter'])}"))
    if "bound" in lim:
        rules.append(("NtpstatsFleetBound", f"ntpstats_offset_bound_seconds > {lim['bound']:.6g}", for_, "critical",
                      f"error bound of {{{{ $labels.source }}}} on {{{{ $labels.instance }}}} above "
                      f"{format_seconds(lim['bound'])}"))
    if "age" in lim:
        rules.append(("NtpstatsFleetStale", f"time() - ntpstats_last_sample_timestamp_seconds > {lim['age']:.6g}",
                      "0m", "warning", f"no sample from {{{{ $labels.source }}}} on {{{{ $labels.instance }}}} "
                      f"for {format_age(lim['age'])}"))
    lines = ["# Prometheus alerting rules written by 'ntpstats fleet --rules' for the ntpstats exporter",
             "# (ntpstats monitor/watch --metrics-port); the thresholds match the fleet report.",
             "groups:", f"  - name: {group}", "    rules:"]
    if not rules:
        lines.append("      []")
    for name, expr, dur, sev, summ in rules:
        lines += [f"      - alert: {name}", f"        expr: {expr}"]
        if dur != "0m":
            lines.append(f"        for: {dur}")
        lines += [f"        labels: {{severity: {sev}}}", "        annotations:", f'          summary: "{summ}"']
    return "\n".join(lines) + "\n"
