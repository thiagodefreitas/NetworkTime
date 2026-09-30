# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Packet-network timing metrics: delay floor, asymmetry wedge, FPP, clock filter.

NTP (and PTP without on-path support) measures offset through a packet
network whose queueing delay is variable and generally asymmetric. For a
single exchange the true offset theta satisfies::

    |measured_offset - theta| <= (delay - delay_asym_free) / 2

so samples whose round-trip delay is close to the *floor* (minimum) delay
carry the least error. These helpers quantify that; they need a ``delay``
column (peerstats, rawstats, chrony measurements, ``ntpstats monitor`` CSV
or simulated data).
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from .series import TimeSeries


def _delay(series: TimeSeries) -> np.ndarray:
    if "delay" not in series.extra:
        raise ValueError(f"{series.name}: no 'delay' column (use peerstats, rawstats, chrony measurements or monitor logs)")
    return series.extra["delay"]


def delay_stats(series: TimeSeries, cluster: Optional[float] = None) -> Dict[str, float]:
    """Round-trip delay distribution and the offset/delay relationship.

    ``cluster`` is the width above the floor delay used for the "floor
    fraction" (default: 10 % of the median queueing delay, min 50 µs).
    """
    d = _delay(series)
    ok = np.isfinite(d)
    d, x = d[ok], series.offset[ok]
    if d.size < 3:
        raise ValueError("need at least 3 delay samples")
    floor = float(d.min())
    q = d - floor
    if cluster is None:
        cluster = max(0.1 * float(np.median(q)), 50e-6)
    near = q <= cluster
    corr = float(np.corrcoef(q, x)[0, 1]) if np.std(q) > 0 and np.std(x) > 0 else float("nan")
    pct = np.percentile(d, (1, 5, 50, 95, 99))
    return {
        "delay_min": floor,
        "delay_median": float(pct[2]),
        "delay_p95": float(pct[3]),
        "delay_p99": float(pct[4]),
        "delay_max": float(d.max()),
        "queueing_median": float(np.median(q)),
        "cluster_width": float(cluster),
        "floor_fraction": float(near.mean()),
        "offset_at_floor_mean": float(x[near].mean()),
        "offset_at_floor_std": float(x[near].std()),
        "offset_all_std": float(x.std()),
        "offset_delay_correlation": corr,
        # Mean offset of floor packets minus mean offset of all packets: a
        # non-zero value indicates queueing that is asymmetric on average.
        "asymmetry_indicator": float(x[near].mean() - x.mean()),
    }


def wedge(series: TimeSeries):
    """Data for the classic Mills offset-vs-delay "wedge" scatter plot.

    Returns ``(queueing_delay, offset, bound)`` where ``bound = queueing/2``
    is the maximum offset error the extra delay could have introduced.
    """
    d = _delay(series)
    q = d - np.nanmin(d)
    return q, series.offset, q / 2


def floor_packet_percentage(
    series: TimeSeries, window: float = 200.0, cluster: float = 150e-6, floor: Optional[float] = None
):
    """Floor Packet Percentage in the style of ITU-T G.8260 (Appendix I).

    For consecutive windows of ``window`` seconds, the percentage of
    packets whose delay lies within ``cluster`` seconds of the floor delay
    (the minimum over the whole record unless ``floor`` is given). Returns
    ``(window_start_times, fpp_percent)``. G.8260 evaluates the two
    directions separately with one-way delays; NTP logs only give round
    trip delay, so this is the round-trip analogue.
    """
    d = _delay(series)
    t = series.t
    ok = np.isfinite(d)
    t, d = t[ok], d[ok]
    fl = float(d.min()) if floor is None else float(floor)
    nwin = int(np.floor((t[-1] - t[0]) / window)) + 1  # last window contains t[-1]
    edges = t[0] + window * np.arange(nwin + 1)
    idx = np.searchsorted(t, edges)
    starts, pct = [], []
    for a, b, e in zip(idx[:-1], idx[1:], edges[:-1]):
        if b > a:
            starts.append(e)
            pct.append(100.0 * np.mean(d[a:b] <= fl + cluster))
    return np.array(starts), np.array(pct)


def min_delay_filter(series: TimeSeries, window: int = 8) -> TimeSeries:
    """NTP-style clock filter: from each sliding window of ``window``
    samples keep the one with the smallest round-trip delay (RFC 5905
    section 10 uses an 8-stage shift register). Duplicates are removed."""
    d = _delay(series)
    n = len(series)
    if n == 0:
        return series
    w = max(1, int(window))
    picks = set()
    for i in range(n):
        a = max(0, i - w + 1)
        seg = d[a: i + 1]
        if np.isfinite(seg).any():
            picks.add(a + int(np.nanargmin(seg)))
    out = series.select(np.array(sorted(picks), dtype=int))
    out.name = f"{series.name} (min-delay/{w})"
    out.meta["derived_from"] = series.name
    return out
