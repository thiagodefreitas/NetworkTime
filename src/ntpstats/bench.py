# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Benchmark synchronisation estimators against simulated ground truth.

    rows = run_bench(load_scenarios(["internet", "examples/scenarios/route-change.toml"]),
                     estimators=["kalman-dw", "regression", "rfc5905"], seeds=range(1, 6))
    table = summarize(rows)

Scenarios are preset names (:data:`ntpstats.simulate.PRESETS`) or TOML/JSON
files (see :func:`ntpstats.simulate.scenario_from_dict`). Single-server
estimators are scored on the first server; multi-server estimators get all.

Metrics of the estimation error ``e = estimate - truth``: RMS, bias (mean),
p95 and max of |e|, MTIE of e over 1 h windows, and wall-clock runtime.
The first ``warmup`` seconds (default 30 min) are excluded, as usual when
comparing synchronisation algorithms, so start-up transients do not dominate.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from . import estimators as est_mod
from .simulate import PRESETS, Scenario, scenario_from_dict, simulate_multi

METRICS = ("rms", "bias", "p95_abs", "max_abs", "mtie_1h", "runtime_s")


def _load_file(path: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read()
    if path.endswith(".json"):
        return json.loads(raw)
    import importlib

    try:
        toml: Any = importlib.import_module("tomllib")  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        try:
            toml = importlib.import_module("tomli")
        except ModuleNotFoundError as exc:
            raise SystemExit("TOML scenarios need Python 3.11+ or `pip install tomli`") from exc
    return toml.loads(raw.decode("utf-8"))


def trace_scenario(path: str, mode: str = "replay") -> Tuple[str, Scenario]:
    """A scenario that replays the delays of a capture or log (``trace:FILE`` on the command line).

    The poll interval and duration are those of the trace; the clock is the
    ``internet`` preset's. For more control write a scenario file with a
    ``[trace]`` table.
    """
    from .trace import TracePath, load_trace

    tr = load_trace(path)
    name = f"trace:{os.path.basename(path)}"
    sc = replace(PRESETS["internet"], name=name, poll=tr.interval, duration=tr.duration,
                 trace=TracePath(tr, mode=mode))
    return name, sc


def load_scenarios(specs: Iterable[str]) -> List[Tuple[str, Scenario]]:
    out = []
    for spec in specs:
        if spec in PRESETS:
            out.append((spec, replace(PRESETS[spec], name=spec)))
        elif spec.startswith("trace:"):
            out.append(trace_scenario(spec[len("trace:"):]))
        elif os.path.exists(spec):
            d = _load_file(spec)
            name = d.get("name") or os.path.splitext(os.path.basename(spec))[0]
            out.append((name, scenario_from_dict(dict(d, name=name), base_dir=os.path.dirname(os.path.abspath(spec)))))
        else:
            raise ValueError(f"unknown scenario {spec!r} (presets: {', '.join(PRESETS)}; trace:FILE replays a capture)")
    return out


def _mtie(t: np.ndarray, e: np.ndarray, window: float) -> float:
    if t.size < 2:
        return float("nan")
    j = np.searchsorted(t, t + window, side="right")
    best = 0.0
    for i in range(t.size):
        seg = e[i: max(j[i], i + 1)]
        best = max(best, float(seg.max() - seg.min()))
        if j[i] >= t.size:
            break
    return best


def score(estimate, truth, warmup: float = 0.0) -> dict:
    t = estimate.t
    ok = (t >= truth.t[0] + warmup) & (t <= truth.t[-1]) & np.isfinite(estimate.offset)
    t = t[ok]
    e = estimate.offset[ok] - np.interp(t, truth.t, truth.offset)
    if e.size == 0:
        return {k: float("nan") for k in METRICS[:-1]}
    return {
        "rms": float(np.sqrt(np.mean(e * e))),
        "bias": float(np.mean(e)),
        "p95_abs": float(np.percentile(np.abs(e), 95)),
        "max_abs": float(np.max(np.abs(e))),
        "mtie_1h": _mtie(t, e, 3600.0),
    }


def run_bench(scenarios: Sequence[Tuple[str, Scenario]], estimators: Optional[Sequence[str]] = None,
              seeds: Iterable[int] = (1, 2, 3), duration: Optional[float] = None, progress=None,
              warmup: float = 1800.0) -> List[dict]:
    names = list(estimators) if estimators else sorted(est_mod.available())
    ests = [est_mod.get(n) for n in names]
    rows = []
    for sc_name, sc in scenarios:
        for seed in seeds:
            s2 = replace(sc, seed=int(seed))
            if duration:
                s2 = replace(s2, duration=float(duration))
            meas, truth = simulate_multi(s2, name=sc_name)
            for e in ests:
                if e.multi is False and not meas:
                    continue
                t0 = time.perf_counter()
                try:
                    out = est_mod.run(e, meas)
                    m = score(out, truth, warmup)
                except Exception as exc:  # a failing plugin must not abort the benchmark
                    m = {k: float("nan") for k in METRICS[:-1]}
                    m["error"] = f"{type(exc).__name__}: {exc}"
                m["runtime_s"] = time.perf_counter() - t0
                row = {"scenario": sc_name, "seed": int(seed), "estimator": e.name, "multi": e.multi,
                       "servers": len(meas), **m}
                rows.append(row)
                if progress:
                    progress(row)
    return rows


def summarize(rows: Sequence[dict]) -> List[dict]:
    """Mean and standard deviation of each metric over seeds."""
    groups: Dict[tuple, List[dict]] = {}
    for r in rows:
        groups.setdefault((r["scenario"], r["estimator"]), []).append(r)
    out = []
    for (sc, est), rs in groups.items():
        d = {"scenario": sc, "estimator": est, "runs": len(rs)}
        for k in METRICS:
            v = np.array([r[k] for r in rs], dtype=float)
            d[k] = float(np.nanmean(v)) if np.isfinite(v).any() else float("nan")
            d[k + "_std"] = float(np.nanstd(v)) if np.isfinite(v).sum() > 1 else 0.0
        out.append(d)
    out.sort(key=lambda d: (d["scenario"], d["rms"] if np.isfinite(d["rms"]) else np.inf))
    return out


def to_csv(rows: Sequence[dict]) -> str:
    if not rows:
        return ""
    keys = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
