# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Descriptive statistics, detrending and outlier handling for offset series."""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from .series import TimeSeries

PERCENTILES = (1, 5, 50, 95, 99)


def detrend(t: np.ndarray, x: np.ndarray, kind: Optional[str] = "linear") -> np.ndarray:
    """Remove a least-squares polynomial trend.

    ``linear`` removes a constant frequency offset; ``quadratic`` also
    removes a linear frequency drift (aging). Time is centred first so the
    fit stays well conditioned with POSIX timestamps.
    """
    if not kind or kind == "none":
        return np.asarray(x, dtype=float)
    deg = {"mean": 0, "linear": 1, "quadratic": 2}[kind]
    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    if t.size <= deg:
        return x - np.mean(x)
    tc = t - t.mean()
    coef = np.polyfit(tc, x, deg)
    return x - np.polyval(coef, tc)


def linear_fit(t, x):
    """Least-squares slope (s/s) and intercept of offset vs time."""
    t = np.asarray(t, dtype=float)
    tc = t - t.mean()
    slope, icpt = np.polyfit(tc, np.asarray(x, dtype=float), 1)
    return float(slope), float(icpt)


def theil_sen_slope(t, x, max_pairs: int = 200_000, seed: int = 0) -> float:
    """Robust (median of pairwise slopes) frequency estimate, s/s.

    Insensitive to up to ~29 % outliers, unlike least squares. Pairs are
    randomly subsampled for long series.
    """
    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    n = t.size
    if n < 2:
        return float("nan")
    if n * (n - 1) // 2 <= max_pairs:
        i, j = np.triu_indices(n, 1)
    else:
        rng = np.random.default_rng(seed)
        i = rng.integers(0, n, max_pairs)
        j = rng.integers(0, n, max_pairs)
    dt = t[j] - t[i]
    ok = dt != 0
    return float(np.median((x[j] - x[i])[ok] / dt[ok]))


def mad_outliers(x: np.ndarray, k: float = 5.0, t: Optional[np.ndarray] = None) -> np.ndarray:
    """Boolean mask of outliers: |x - median| > k * 1.4826 * MAD.

    If ``t`` is given the test is applied to linearly detrended data so a
    frequency offset is not mistaken for outliers.
    """
    x = np.asarray(x, dtype=float)
    r = detrend(t, x, "linear") if t is not None and x.size > 2 else x
    med = np.median(r)
    mad = 1.4826 * np.median(np.abs(r - med))
    if mad == 0:
        return np.zeros(x.shape, dtype=bool)
    return np.abs(r - med) > k * mad


def remove_outliers(series: TimeSeries, k: float = 5.0) -> TimeSeries:
    mask = mad_outliers(series.offset, k, series.t)
    out = series.select(~mask)
    out.meta["outliers_removed"] = int(mask.sum())
    return out


def summary(series: TimeSeries) -> Dict[str, object]:
    """Summary statistics in the spirit of NTPsec's ``ntpviz`` report."""
    x = series.offset
    n = len(series)
    out: Dict[str, object] = {
        "name": series.name,
        "format": series.source_format,
        "samples": n,
    }
    if n == 0:
        return out
    out.update(
        {
            "start": float(series.t[0]),
            "end": float(series.t[-1]),
            "span_s": series.span,
            "mean": float(np.mean(x)),
            "std": float(np.std(x, ddof=1)) if n > 1 else 0.0,
            "rms": float(np.sqrt(np.mean(x * x))),
            "min": float(np.min(x)),
            "max": float(np.max(x)),
            "mean_abs": float(np.mean(np.abs(x))),
        }
    )
    pct = np.percentile(x, PERCENTILES)
    out["percentiles"] = {f"p{p}": float(v) for p, v in zip(PERCENTILES, pct)}
    out["range_90"] = float(pct[3] - pct[1])  # p95 - p5
    out["range_98"] = float(pct[4] - pct[0])  # p99 - p1
    if n > 2:
        out["median_interval_s"] = series.median_interval()
        out["regularity"] = series.regularity()
        slope, _ = linear_fit(series.t, x)
        out["offset_slope_ppm"] = slope * 1e6
        out["offset_slope_robust_ppm"] = theil_sen_slope(series.t, x) * 1e6
        resid = detrend(series.t, x, "linear")
        out["residual_rms"] = float(np.sqrt(np.mean(resid ** 2)))
        out["outliers_5mad"] = int(mad_outliers(x, 5.0, series.t).sum())
        d = series.intervals()
        med = series.median_interval()
        out["gaps"] = int(np.sum(d > 3 * med))
        out["longest_gap_s"] = float(d.max())
    for key, col in series.extra.items():
        if col.size and np.isfinite(col).any():
            out[f"{key}_median"] = float(np.nanmedian(col))
    return out


def format_seconds(v: Optional[float]) -> str:
    """Pretty-print a time value with an SI prefix (e.g. 12.3 µs)."""
    if v is None or not np.isfinite(v):
        return "n/a"
    a = abs(v)
    if a == 0:
        return "0 s"
    for scale, unit in ((1, "s"), (1e-3, "ms"), (1e-6, "µs"), (1e-9, "ns")):
        if a >= scale:
            return f"{v / scale:.3g} {unit}"
    return f"{v / 1e-12:.3g} ps"


def compare(estimate: TimeSeries, reference: TimeSeries) -> Dict[str, float]:
    """Score ``estimate`` against a ``reference`` (e.g. simulated truth, a
    GNSS/PPS-disciplined clock or a better server).

    The reference is linearly interpolated onto the estimate's times over
    their common span. Returns error statistics of ``estimate - reference``.
    """
    r = reference.sorted()
    e = estimate.sorted().between(r.t[0], r.t[-1])
    if len(e) < 2:
        raise ValueError("series do not overlap")
    err = e.offset - np.interp(e.t, r.t, r.offset)
    return {
        "samples": int(err.size),
        "bias": float(np.mean(err)),
        "rms": float(np.sqrt(np.mean(err ** 2))),
        "std": float(np.std(err)),
        "max_abs": float(np.max(np.abs(err))),
        "p95_abs": float(np.percentile(np.abs(err), 95)),
    }
