# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Anomaly and change-point detection for clock-offset logs.

Stability statistics assume stationarity; real logs contain events. This
module locates and labels them, so they can be reviewed, excluded or
explained before (or instead of) computing ADEV:

``phase_step``
    the offset jumps and stays (daemon step, reference switch, restart).
``spike``
    an isolated outlier that returns to the previous level.
``frequency_change``
    the offset slope (local frequency error) changes; binary segmentation
    of the local frequency with a standardised CUSUM statistic.
``delay_floor_change``
    the minimum round-trip delay moves (route change). The offset shift
    at the same time is reported: a shift of about half the delay change
    means the new path is asymmetric in one direction.
``leap_smear``
    a frequency plateau of about 11.6 ppm (1 s spread over 24 h) lasting
    20-28 h, the signature of a smeared leap second upstream.

Phase steps and frequency changes are also marked ``path_changed`` when a
delay-floor change happens nearby. An offset change **without** a path
change points at the reference or the local clock (daemon behaviour, an
upstream GNSS problem, spoofing), not the network.

All detectors are robust (MAD-scaled) and documented by their parameters;
they return :class:`Event` objects and never modify the data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .series import TimeSeries

LEAP_SMEAR_PPM = 1e6 / 86400.0  # 11.574 ppm


@dataclass
class Event:
    time: float
    kind: str
    magnitude: float  # s for phase/delay events, fractional frequency (s/s) for frequency events
    unit: str
    score: float
    end: Optional[float] = None
    detail: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in d.items()}


def _mad(v: np.ndarray) -> float:
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan")
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def _rolling_median(v: np.ndarray, w: int) -> np.ndarray:
    """Centred rolling median (window ``w``, odd), edges padded with the edge windows."""
    w = max(3, w | 1)
    if v.size < w:
        return np.full(v.shape, float(np.median(v)))
    h = w // 2
    padded = np.concatenate((np.full(h, np.nan), v, np.full(h, np.nan)))
    win = np.lib.stride_tricks.sliding_window_view(padded, w)
    return np.nanmedian(win, axis=1)


def _binseg(z: np.ndarray, sigma: float, thresh: float, min_seg: int) -> List[Tuple[int, float]]:
    """Change points of the mean of ``z`` (index, standardised CUSUM statistic)."""
    out: List[Tuple[int, float]] = []
    stack = [(0, z.size)]
    while stack:
        a, b = stack.pop()
        m = b - a
        if m < 2 * min_seg or sigma <= 0:
            continue
        seg = z[a:b]
        c = np.cumsum(seg - seg.mean())
        k = np.arange(1, m)
        stat = np.abs(c[:-1]) / (sigma * np.sqrt(k * (m - k) / m))
        stat[: min_seg - 1] = 0
        stat[m - min_seg:] = 0
        i = int(np.argmax(stat))
        if stat[i] > thresh:
            cp = a + i + 1
            out.append((cp, float(stat[i])))
            stack += [(a, cp), (cp, b)]
    return sorted(out)


def phase_steps(s: TimeSeries, k: float = 8.0, window: int = 5, trend_window: int = 31) -> List[Event]:
    """Jumps of the offset larger than ``k`` robust sigmas of the sample-to-sample changes.

    Changes are measured against a rolling median of the local slope, so a
    steady frequency error (or a leap smear) is not mistaken for steps.
    """
    x, t = s.offset, s.t
    if x.size < 2 * window + 2:
        return []
    d = np.diff(x)
    slope = _rolling_median(d, trend_window)
    r = d - slope
    sigma = _mad(r)
    if not np.isfinite(sigma) or sigma == 0:
        sigma = float(np.std(r)) or 1e-30
    cand = np.flatnonzero(np.abs(r) > k * sigma) + 1
    events: List[Event] = []
    last = -10 * window
    for i in cand.tolist():  # plain ints
        if i - last < window:
            continue
        sl = float(slope[i - 1])
        jb = np.arange(max(0, i - window), i)
        ja = np.arange(i, min(x.size, i + 1 + window))
        pre = x[jb] + sl * (i - jb)  # extrapolated to sample i
        post = x[ja] - sl * (ja - i)
        jump = float(x[i] - np.median(pre))
        level = float(np.median(post) - np.median(pre))
        if ja.size > 1 and abs(level) > 0.5 * abs(jump):
            events.append(Event(float(t[i]), "phase_step", level, "s", abs(level) / sigma, detail={"sigma": sigma}))
        else:
            events.append(Event(float(t[i]), "spike", jump, "s", abs(jump) / sigma, detail={"sigma": sigma}))
        last = i
    return events


def frequency_changes(s: TimeSeries, thresh: float = 5.0, min_seg: int = 16,
                      min_change: float = 1e-7) -> List[Event]:
    """Changes of the local frequency error (slope of the offset).

    Binary segmentation on ``y = diff(offset) / diff(t)`` with a MAD-based
    sigma; changes smaller than ``min_change`` (fractional frequency, 0.1 ppm
    by default) are not reported. Phase steps are excluded from ``y`` first.
    """
    x, t = s.offset, s.t
    if x.size < 2 * min_seg + 2:
        return []
    dt = np.diff(t)
    ok = dt > 0
    y = np.diff(x)[ok] / dt[ok]
    ty = (t[1:][ok] + t[:-1][ok]) / 2
    sig = _mad(y)
    if not np.isfinite(sig) or sig == 0:
        return []
    ymed = _rolling_median(y, 31)
    loc = _mad(y - ymed)
    if np.isfinite(loc) and loc > 0:
        sig = loc
    y = np.where(np.abs(y - ymed) > 8 * sig, np.nan, y)  # drop steps/spikes, keep slope changes
    keep = np.isfinite(y)
    y, ty = y[keep], ty[keep]
    events = []
    cps = _binseg(y, sig, thresh, min_seg)
    bounds = [0] + [c for c, _ in cps] + [y.size]
    means = [float(np.mean(y[a:b])) for a, b in zip(bounds[:-1], bounds[1:])]
    for j, (cp, stat) in enumerate(cps):
        delta = means[j + 1] - means[j]
        if abs(delta) >= min_change:
            events.append(Event(float(ty[cp]), "frequency_change", delta, "s/s", stat,
                                detail={"before_ppm": means[j] * 1e6, "after_ppm": means[j + 1] * 1e6}))
    return events


def delay_floor_changes(s: TimeSeries, block: int = 16, thresh: float = 5.0, min_blocks: int = 3,
                        min_change: Optional[float] = None) -> List[Event]:
    """Steps of the minimum delay (route changes), from per-block minima."""
    if "delay" not in s.extra:
        return []
    dl, x, t = s.extra["delay"], s.offset, s.t
    nb = dl.size // block
    if nb < 2 * min_blocks:
        return []
    idx = np.arange(nb * block).reshape(nb, block)
    with np.errstate(all="ignore"):
        mins = np.nanmin(dl[idx], axis=1)
        offs = np.nanmedian(x[idx], axis=1)
    tb = t[idx[:, 0]]
    sig = _mad(np.diff(mins)) / np.sqrt(2)
    floor = float(np.nanmedian(mins))
    if not np.isfinite(sig) or sig == 0:
        sig = max(1e-9, 1e-3 * abs(floor))
    thr = min_change if min_change is not None else max(3 * sig, 0.05 * abs(floor))
    events = []
    cps = _binseg(mins, sig, thresh, min_blocks)
    bounds = [0] + [c for c, _ in cps] + [nb]
    lvl = [float(np.median(mins[a:b])) for a, b in zip(bounds[:-1], bounds[1:])]
    olv = [float(np.median(offs[a:b])) for a, b in zip(bounds[:-1], bounds[1:])]
    for j, (cp, stat) in enumerate(cps):
        delta = lvl[j + 1] - lvl[j]
        if abs(delta) < thr:
            continue
        shift = olv[j + 1] - olv[j]
        ratio = shift / (delta / 2) if delta else float("nan")
        events.append(Event(float(tb[cp]), "delay_floor_change", delta, "s", stat, detail={
            "floor_before": lvl[j], "floor_after": lvl[j + 1], "offset_shift": shift,
            "asymmetry_ratio": ratio,
            "interpretation": ("one-direction path change (offset moved by about half the delay change)"
                               if np.isfinite(ratio) and 0.5 < abs(ratio) < 1.5 else
                               "symmetric path change or unclear")}))
    return events


def leap_smears(freq_events: List[Event], tolerance_ppm: float = 1.5,
                min_hours: float = 20.0, max_hours: float = 28.0) -> List[Event]:
    """Pairs of opposite frequency changes of about 11.6 ppm, 20-28 h apart."""
    out = []
    fe = sorted(freq_events, key=lambda e: e.time)
    for i, a in enumerate(fe):
        for b in fe[i + 1:]:
            h = (b.time - a.time) / 3600.0
            if h > max_hours:
                break
            if (h >= min_hours and abs(abs(a.magnitude) * 1e6 - LEAP_SMEAR_PPM) < tolerance_ppm
                    and abs(a.magnitude + b.magnitude) * 1e6 < tolerance_ppm):
                out.append(Event(a.time, "leap_smear", a.magnitude, "s/s", min(a.score, b.score), end=b.time,
                                 detail={"hours": h, "rate_ppm": a.magnitude * 1e6}))
    return out


def detect(s: TimeSeries, step_k: float = 8.0, freq_thresh: float = 5.0, min_freq_change: float = 1e-7,
           floor_block: int = 16, path_window: Optional[float] = None) -> List[Event]:
    """Run all detectors on one series; events sorted by time.

    ``path_window`` (s) is how close a delay-floor change must be to a phase
    or frequency event to count as its cause (default: 2 floor blocks).
    """
    s = s.sorted()
    ev = phase_steps(s, k=step_k)
    fq = frequency_changes(s, thresh=freq_thresh, min_change=min_freq_change)
    fl = delay_floor_changes(s, block=floor_block)
    ev += fq + fl + leap_smears(fq)
    from .plugins import detectors

    for d in detectors().values():  # installed detector plugins; a failing one is skipped
        try:
            ev += [e for e in d.detect(s) if isinstance(e, Event)]
        except Exception:
            continue
    if "delay" in s.extra:
        win = path_window if path_window is not None else 2 * floor_block * s.median_interval()
        for e in ev:
            if e.kind in ("phase_step", "frequency_change"):
                e.detail["path_changed"] = any(abs(f.time - e.time) <= win for f in fl)
                if not e.detail["path_changed"]:
                    e.detail["hint"] = ("offset changed while the network path did not: look at the reference "
                                        "or the local clock (daemon step, upstream GNSS problem, spoofing)")
    return sorted(ev, key=lambda e: e.time)


def summary(events: List[Event]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in events:
        out[e.kind] = out.get(e.kind, 0) + 1
    return out
