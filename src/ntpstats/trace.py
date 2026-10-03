# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Delay traces: real per-direction network delays that drive the simulator.

The synthetic paths of :mod:`ntpstats.simulate` (a floor plus exponential
queueing) are a model. A *trace* is the delay a real network imposed:
extract it from a capture or a log, then replay it under a simulated clock
whose true offset is known, so that estimators are scored on real network
behaviour (#29).

Extraction
----------
Every two-way exchange (NTP or PTP, from a capture or a daemon log) gives the
measured offset ``θm`` (reference − local) and the round-trip delay ``δ``. The
raw one-way delays are ``δ/2 + θm`` (local to reference) and ``δ/2 − θm``
(reference to local). They still contain the true offset ``θ`` between the
two clocks, which moves as the clocks wander, so ``θ`` is estimated and
removed ("detrended"):

* ``floor`` (default): in each window, the exchange with the smallest round
  trip is taken as symmetric, its offset is ``θ``; ``θ`` is interpolated
  between windows. This follows the clock's wander and is how the NTP clock
  filter and Huygens-style estimators reason.
* ``linear``: one straight line (Theil–Sen) through those minimum-delay
  offsets, for clocks with a steady frequency offset.
* ``none``: ``θ = 0``, for captures where both ends were synchronised (for
  example a capture host disciplined by PTP or GNSS).

The absolute asymmetry of a path cannot be measured from two-way timestamps
alone; the trace assumes equal floor delays unless ``asymmetry`` (forward
floor − backward floor) is given. The queueing variation (PDV) and its
correlation between directions are kept.

Replay
------
:class:`TracePath` feeds a trace to the simulator, either in time order
(``replay``, looping if the run is longer) or as a moving-block bootstrap
(``bootstrap``) that draws random blocks of ``block`` seconds, keeping the
short-term correlation and both directions together, so every seed sees a
different but statistically similar network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .series import TimeSeries

DETRENDS = ("floor", "linear", "none")
MODES = ("replay", "bootstrap")


@dataclass
class DelayTrace:
    """One-way delays of a path, seconds; NaN marks a lost exchange.

    ``to_ref`` is local → reference (the client → server direction of NTP,
    slave → master of PTP); ``from_ref`` is the other direction. ``t`` is
    seconds from the start of the trace.
    """

    t: np.ndarray
    to_ref: np.ndarray
    from_ref: np.ndarray
    name: str = "trace"
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.t = np.asarray(self.t, dtype=float)
        self.to_ref = np.asarray(self.to_ref, dtype=float)
        self.from_ref = np.asarray(self.from_ref, dtype=float)
        if not (self.t.shape == self.to_ref.shape == self.from_ref.shape) or self.t.ndim != 1:
            raise ValueError("t, to_ref and from_ref must be 1-D arrays of equal length")
        if self.t.size < 2:
            raise ValueError("a delay trace needs at least 2 exchanges")
        order = np.argsort(self.t, kind="stable")
        self.t, self.to_ref, self.from_ref = self.t[order] - self.t[order][0], self.to_ref[order], self.from_ref[order]

    def __len__(self) -> int:
        return int(self.t.size)

    @property
    def interval(self) -> float:
        return float(np.median(np.diff(self.t)))

    @property
    def duration(self) -> float:
        return float(self.t[-1] + self.interval)

    def stats(self) -> Dict[str, Any]:
        """Floors, percentiles and PDV of both directions, loss and the assumptions made."""
        out: Dict[str, Any] = {"name": self.name, "exchanges": len(self), "duration_s": self.duration,
                               "interval_s": self.interval}
        ok = np.isfinite(self.to_ref) & np.isfinite(self.from_ref)
        out["loss"] = float(1.0 - ok.mean())
        for label, d in (("to_ref", self.to_ref[ok]), ("from_ref", self.from_ref[ok])):
            if d.size:
                p = np.percentile(d, [1, 50, 99])
                out[label] = {"floor": float(d.min()), "p1": float(p[0]), "median": float(p[1]), "p99": float(p[2]),
                              "pdv_p99": float(p[2] - d.min()), "mean": float(d.mean())}
        if ok.sum() > 2:
            out["pdv_correlation"] = float(np.corrcoef(self.to_ref[ok], self.from_ref[ok])[0, 1])
        out.update({k: v for k, v in self.meta.items() if k in ("detrend", "window_s", "asymmetry", "source",
                                                                  "clipped", "theta_range")})
        return out

    def to_series(self, epoch: float = 0.0) -> TimeSeries:
        """As a series: offset (reference − local) is what a perfect clock would have measured."""
        return TimeSeries(self.t + epoch, (self.to_ref - self.from_ref) / 2, name=self.name, source_format="trace",
                          extra={"delay": self.to_ref + self.from_ref, "to_ref": self.to_ref,
                                 "from_ref": self.from_ref}, meta=dict(self.meta))

    def to_csv(self) -> str:
        """CSV (``unix_time,offset,delay,to_ref,from_ref``) that :func:`load_trace` reads back."""
        s = self.to_series()
        lines = [f"# ntpstats delay trace: {self.name}", "unix_time,offset,delay,to_ref,from_ref"]
        for row in zip(s.t, s.offset, s.extra["delay"], self.to_ref, self.from_ref):
            lines.append(",".join(repr(float(v)) for v in row))
        return "\n".join(lines) + "\n"


def _theil_sen(t: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    if t.size < 2:
        return 0.0, float(y[0]) if y.size else 0.0
    i, j = np.triu_indices(t.size, 1)
    dt = t[j] - t[i]
    keep = dt > 0
    slope = float(np.median((y[j] - y[i])[keep] / dt[keep])) if keep.any() else 0.0
    return slope, float(np.median(y - slope * t))


def from_series(series: TimeSeries, detrend: str = "floor", window: Optional[float] = None,
                asymmetry: float = 0.0, name: Optional[str] = None) -> DelayTrace:
    """Extract a :class:`DelayTrace` from any series with an offset and a round-trip ``delay`` column.

    Works for NTP and PTP captures, chrony ``measurements.log``, ntpd
    ``peerstats``/``rawstats`` and simulator output. A series that already has
    ``to_ref``/``from_ref`` columns (an exported trace) is taken as is.
    """
    if detrend not in DETRENDS:
        raise ValueError(f"detrend must be one of {', '.join(DETRENDS)}")
    label = name or series.name
    if "to_ref" in series.extra and "from_ref" in series.extra:
        return DelayTrace(series.t, series.extra["to_ref"], series.extra["from_ref"], name=label,
                          meta={"source": series.source_format, "detrend": "as exported"})
    if "delay" not in series.extra:
        raise ValueError(f"{label}: no round-trip delay column; a trace needs two-way exchanges (NTP or PTP)")
    t = series.t - series.t[0]
    theta_m = np.asarray(series.offset, dtype=float)
    delay = np.asarray(series.extra["delay"], dtype=float)
    ok = np.isfinite(theta_m) & np.isfinite(delay)
    if ok.sum() < 2:
        raise ValueError(f"{label}: fewer than 2 complete exchanges")
    interval = float(np.median(np.diff(t[ok])))
    win = float(window) if window else max(16 * interval, 900.0)
    theta = np.zeros_like(t)
    if detrend != "none":
        idx = np.flatnonzero(ok)
        # equal windows of about `win` seconds (no short window at the end, whose minimum may not be symmetric)
        span = t[idx[-1]] - t[idx[0]]
        # at least 4 windows of 16+ exchanges when the trace allows, so a short capture still gets a slope
        nwin = max(1, int(round(span / win)), min(4, idx.size // 16))
        width = span / nwin
        anchors = []
        for j in range(nwin):
            a = t[idx[0]] + j * width
            last = j == nwin - 1
            sel = idx[(t[idx] >= a) & ((t[idx] <= a + width) if last else (t[idx] < a + width))]
            if sel.size:
                k = sel[np.argmin(delay[sel])]
                anchors.append((t[k], theta_m[k]))
        at = np.array(anchors, dtype=float).reshape(-1, 2)
        if detrend == "linear" or len(at) < 2:
            slope, icpt = _theil_sen(at[:, 0], at[:, 1])
            theta = icpt + slope * t
        else:
            # interpolate between anchors; extrapolate the end slopes beyond the first and last anchor
            x, y = at[:, 0], at[:, 1]
            # (robust slopes over the first/last few anchors: a short end window may give a poor anchor)
            s0, c0 = _theil_sen(x[:5], y[:5])
            s1, c1 = _theil_sen(x[-5:], y[-5:])
            theta = np.interp(t, x, y)
            theta = np.where(t < x[0], c0 + s0 * t, theta)
            theta = np.where(t > x[-1], c1 + s1 * t, theta)
    resid = theta_m - theta
    to_ref = delay / 2 + resid + asymmetry / 2
    from_ref = delay / 2 - resid - asymmetry / 2
    clipped = int(np.sum((to_ref < 0) | (from_ref < 0)))
    to_ref, from_ref = np.maximum(to_ref, 0.0), np.maximum(from_ref, 0.0)
    to_ref[~ok], from_ref[~ok] = np.nan, np.nan
    meta = {"source": series.source_format, "detrend": detrend, "window_s": win if detrend == "floor" else None,
            "asymmetry": float(asymmetry), "clipped": clipped,
            "theta_range": float(np.ptp(theta)) if theta.size else 0.0, "file": series.meta.get("file")}
    return DelayTrace(t, to_ref, from_ref, name=label, meta=meta)


def load_trace(path, peer: Optional[str] = None, fmt: str = "auto", detrend: str = "floor",
               window: Optional[float] = None, asymmetry: float = 0.0) -> DelayTrace:
    """Load a capture or log (any format with two-way exchanges) and extract its delay trace."""
    from .parsers import load_one

    s = load_one(os.fspath(path), fmt=fmt, peer=peer)
    return from_series(s, detrend=detrend, window=window, asymmetry=asymmetry)


@dataclass
class TracePath:
    """A :class:`DelayTrace` as the network of a simulated scenario (both directions together).

    ``mode="replay"`` plays the trace in time order (looping); ``bootstrap``
    concatenates random blocks of ``block`` seconds (default: 64 exchanges or
    the trace duration / 8, whichever is shorter), a moving-block bootstrap
    that keeps short-term correlation. ``scale`` multiplies the queueing part
    (delay above each direction's floor), to ask "what if the network were
    twice as loaded?".
    """

    trace: DelayTrace
    mode: str = "replay"
    block: Optional[float] = None
    scale: float = 1.0

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")

    def _source_times(self, rel: np.ndarray, rng) -> np.ndarray:
        dur = self.trace.duration
        rel = np.asarray(rel, dtype=float) - (rel[0] if len(rel) else 0.0)
        if self.mode == "replay":
            return np.mod(rel, dur)
        block = float(self.block) if self.block else min(64 * self.trace.interval, dur / 8)
        block = min(max(block, self.trace.interval), dur)
        nblk = np.floor(rel / block).astype(int)
        starts = rng.uniform(0.0, max(dur - block, 0.0), int(nblk.max()) + 1 if nblk.size else 0)
        return starts[nblk] + (rel - nblk * block)

    def delays(self, rel: np.ndarray, rng) -> Tuple[np.ndarray, np.ndarray]:
        """One-way delays (to_ref, from_ref) at simulation times ``rel`` (s from the start); NaN = lost."""
        src = self._source_times(rel, rng)
        tt = self.trace.t
        i = np.clip(np.searchsorted(tt, src), 1, tt.size - 1)
        i = np.where(np.abs(tt[i - 1] - src) <= np.abs(tt[i] - src), i - 1, i)
        fwd, bwd = self.trace.to_ref[i].copy(), self.trace.from_ref[i].copy()
        if self.scale != 1.0:
            ff, fb = np.nanmin(self.trace.to_ref), np.nanmin(self.trace.from_ref)
            fwd, bwd = ff + self.scale * (fwd - ff), fb + self.scale * (bwd - fb)
        return fwd, bwd


def trace_path_from_dict(d: dict, base_dir: str = ".") -> TracePath:
    """``[trace]`` table of a scenario file: ``file``, ``peer``, ``mode``, ``block``, ``scale``,
    ``detrend``, ``window``, ``asymmetry`` (a relative ``file`` is relative to the scenario file)."""
    d = dict(d)
    path = d.pop("file", None)
    if not path:
        raise ValueError("[trace] needs file = \"capture.pcap\" (or a log with two-way exchanges)")
    if not os.path.isabs(path):
        path = os.path.join(base_dir, path)
    tr = load_trace(path, peer=d.pop("peer", None), fmt=d.pop("format", "auto"), detrend=d.pop("detrend", "floor"),
                    window=d.pop("window", None), asymmetry=float(d.pop("asymmetry", 0.0)))
    tp = TracePath(tr, mode=d.pop("mode", "replay"), block=d.pop("block", None), scale=float(d.pop("scale", 1.0)))
    if d:
        raise ValueError(f"unknown [trace] keys: {', '.join(d)}")
    return tp
