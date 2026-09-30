# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Frequency/time stability estimators for clock-offset (phase) data.

All estimators take *phase* data ``x`` in seconds (NTP offsets are phase
data) sampled uniformly every ``tau0`` seconds, and follow the definitions
in IEEE Std 1139 / NIST SP 1065 (Riley, "Handbook of Frequency
Stability Analysis"). ``tests/test_stability.py`` validates them against
literal implementations of the textbook sums, analytic power-law slopes
and a frozen table of values from an independent implementation.
No third-party stability library is used or required.

NaN samples are allowed: they mark gaps (see
:meth:`ntpstats.series.TimeSeries.to_uniform`). Every term that touches a
NaN is dropped rather than bridged, so gaps never manufacture data.

Estimators
----------
``adev``   non-overlapping Allan deviation (what the 2012 tool computed)
``oadev``  overlapping Allan deviation (preferred ADEV estimator)
``mdev``   modified Allan deviation (separates white vs flicker PM)
``tdev``   time deviation, tau/sqrt(3) * MDEV (ITU-T G.810 / G.8260 metric)
``hdev``   overlapping Hadamard deviation (insensitive to linear frequency
           drift, useful for NTP-disciplined clocks with aging/thermal drift)
``totdev`` total deviation (reflection-extended ADEV, tighter at long tau)
``mtot``   modified total deviation (long-tau MDEV counterpart, bias-corrected)
``ttot``   time total deviation, tau/sqrt(3) * MTOT
``theo1``  Theo1 (Howe), reaches tau = 0.75 * record length
``theobr`` bias-removed Theo1 (TheoBR)
``theoh``  TheoH (ADEV at short tau, TheoBR at long tau)
``mtie``   maximum time interval error (ITU-T G.810)
``tierms`` RMS time interval error (ITU-T G.810)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Union

import numpy as np

KINDS = ("adev", "oadev", "mdev", "tdev", "hdev", "totdev", "mtot", "ttot", "theo1", "theobr", "theoh", "mtie",
         "tierms")

#: Short description used in the UI / CLI.
DESCRIPTIONS = {
    "adev": "Allan deviation (non-overlapping)",
    "oadev": "Allan deviation (overlapping)",
    "mdev": "Modified Allan deviation",
    "tdev": "Time deviation [s]",
    "hdev": "Hadamard deviation (overlapping)",
    "totdev": "Total deviation",
    "mtot": "Modified total deviation",
    "ttot": "Time total deviation [s]",
    "theo1": "Theo1 deviation (tau = 0.75 m tau0)",
    "theobr": "TheoBR deviation (bias-removed Theo1)",
    "theoh": "TheoH deviation (ADEV + TheoBR)",
    "mtie": "Max. time interval error [s]",
    "tierms": "RMS time interval error [s]",
}

#: Estimators whose value is a time (seconds) rather than a fractional frequency.
TIME_KINDS = {"tdev", "ttot", "mtie", "tierms"}

#: MTOT bias: expected MTOT/MVAR variance ratio per power-law noise type
#: (alpha), as used by Stable32 (W. Riley, "Confidence intervals and bias
#: corrections for the Stable32 variance functions"). Reported MTOT is
#: divided by it so that, like MVAR, it is unbiased; NIST SP 1065 tables
#: 30-31 list bias-corrected values.
MTOT_BIAS = {2: 0.94, 1: 0.83, 0: 0.73, -1: 0.70, -2: 0.69}
#: MTOT EDF ``b * T/tau - c`` (NIST SP 1065 table 8), per alpha.
MTOT_EDF = {2: (1.90, 2.10), 1: (1.20, 1.40), 0: (1.10, 1.20), -1: (0.85, 0.50), -2: (0.75, 0.31)}


@dataclass
class StabilityResult:
    kind: str
    tau0: float
    taus: np.ndarray
    dev: np.ndarray
    err: np.ndarray  # simple 1-sigma estimate: dev / sqrt(n)
    n: np.ndarray  # number of terms that entered each estimate
    lo: Optional[np.ndarray] = None  # chi-squared confidence interval (see ``ci``)
    hi: Optional[np.ndarray] = None
    edf: Optional[np.ndarray] = None  # equivalent degrees of freedom
    alpha: Optional[np.ndarray] = None  # identified power-law noise exponent per tau
    ci: Optional[float] = None
    meta: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        def lst(a, cast=float):
            return None if a is None else [None if not np.isfinite(v) else cast(v) for v in a]

        return {
            "kind": self.kind,
            "tau0": self.tau0,
            "taus": lst(self.taus),
            "dev": lst(self.dev),
            "err": lst(self.err),
            "n": lst(self.n, int),
            "lo": lst(self.lo),
            "hi": lst(self.hi),
            "edf": lst(self.edf),
            "alpha": lst(self.alpha, int),
            "ci": self.ci,
        }

    def to_csv(self, fh) -> None:
        fh.write("tau,%s,err,n,lo,hi,edf,alpha\n" % self.kind)
        nan = np.full(self.taus.shape, np.nan)
        cols = zip(self.taus, self.dev, self.err, self.n,
                   *(v if v is not None else nan for v in (self.lo, self.hi, self.edf, self.alpha)))
        for t, d, e, n, lo, hi, edf, al in cols:
            fh.write(f"{t:.9g},{d:.9g},{e:.9g},{int(n)},{lo:.9g},{hi:.9g},{edf:.6g},{al:g}\n")


# --------------------------------------------------------------- tau grids
def tau_multipliers(n: int, spacing: Union[str, Sequence[int]] = "octave", max_m: Optional[int] = None) -> np.ndarray:
    """Averaging factors ``m`` (tau = m * tau0).

    ``spacing``: ``"octave"`` (1, 2, 4, ...), ``"decade"`` (1, 2, 5, 10, 20,
    50, ...), ``"dense"`` (~10 log-spaced points per decade) or ``"all"``.
    A sequence of integers is used verbatim.
    """
    limit = max_m if max_m is not None else max(1, (n - 1) // 2)
    if not isinstance(spacing, str):
        m = np.unique(np.asarray(spacing, dtype=int))
    elif spacing == "octave":
        m = 2 ** np.arange(0, int(np.log2(max(limit, 1))) + 1)
    elif spacing == "decade":
        dec = int(np.log10(max(limit, 1))) + 1
        m = np.array([b * 10 ** k for k in range(dec + 1) for b in (1, 2, 5)])
    elif spacing == "dense":
        m = np.unique(np.round(np.logspace(0, np.log10(max(limit, 1)), 10 * (int(np.log10(max(limit, 1))) + 1))).astype(int))
    elif spacing == "all":
        m = np.arange(1, limit + 1)
    else:
        raise ValueError(f"unknown tau spacing {spacing!r}")
    return m[(m >= 1) & (m <= limit)]


# ---------------------------------------------------------------- helpers
def _nan_meansq(d: np.ndarray):
    ok = np.isfinite(d)
    n = int(ok.sum())
    if n == 0:
        return np.nan, 0
    return float(np.mean(d[ok] ** 2)), n


def _window_sums(d: np.ndarray, m: int):
    """Sums of ``m`` consecutive values; windows containing NaN yield NaN."""
    bad = ~np.isfinite(d)
    c = np.concatenate(([0.0], np.cumsum(np.where(bad, 0.0, d))))
    cb = np.concatenate(([0], np.cumsum(bad)))
    s = c[m:] - c[:-m]
    s[(cb[m:] - cb[:-m]) > 0] = np.nan
    return s


# ------------------------------------------------------------- estimators
def _adev(x, m, tau0):
    xd = x[::m]
    d = xd[2:] - 2 * xd[1:-1] + xd[:-2]
    ms, n = _nan_meansq(d)
    tau = m * tau0
    return np.sqrt(ms / (2 * tau * tau)), n


def _oadev(x, m, tau0):
    d = x[2 * m:] - 2 * x[m:-m] + x[:-2 * m]
    ms, n = _nan_meansq(d)
    tau = m * tau0
    return np.sqrt(ms / (2 * tau * tau)), n


def _mdev(x, m, tau0):
    d = x[2 * m:] - 2 * x[m:-m] + x[:-2 * m]
    if d.size < m:
        return np.nan, 0
    s = _window_sums(d, m)
    ms, n = _nan_meansq(s)
    tau = m * tau0
    return np.sqrt(ms / (2 * m * m * tau * tau)), n


def _tdev(x, m, tau0):
    md, n = _mdev(x, m, tau0)
    return m * tau0 / np.sqrt(3.0) * md, n


def _hdev(x, m, tau0):
    d = x[3 * m:] - 3 * x[2 * m:-m] + 3 * x[m:-2 * m] - x[:-3 * m]
    ms, n = _nan_meansq(d)
    tau = m * tau0
    return np.sqrt(ms / (6 * tau * tau)), n


class _RangeQuery:
    """Sparse table for O(1) sliding-window max/min (NaN-aware)."""

    def __init__(self, x):
        hi = np.where(np.isfinite(x), x, -np.inf)
        lo = np.where(np.isfinite(x), x, np.inf)
        self.hi, self.lo = [hi], [lo]
        w = 1
        while 2 * w <= x.size:
            self.hi.append(np.maximum(self.hi[-1][:-w], self.hi[-1][w:]))
            self.lo.append(np.minimum(self.lo[-1][:-w], self.lo[-1][w:]))
            w *= 2

    def span(self, length):
        k = int(np.floor(np.log2(length)))
        w = 1 << k
        n = self.hi[0].size - length + 1
        hi = np.maximum(self.hi[k][:n], self.hi[k][length - w: length - w + n])
        lo = np.minimum(self.lo[k][:n], self.lo[k][length - w: length - w + n])
        return hi - lo


def _mtie_all(x, ms, tau0):
    rq = _RangeQuery(x)
    out = []
    for m in ms:
        r = rq.span(int(m) + 1)
        r = r[np.isfinite(r)]
        out.append((float(r.max()) if r.size else np.nan, int(r.size)))
    return out


def _totdev(x, m, tau0):
    """Total deviation, NIST SP 1065 eq. (25): phase reflected about both ends."""
    N = x.size
    if N < 3:
        return np.nan, 0
    j = np.arange(1, N - 1)
    left = (2 * x[0] - x[j])[::-1]  # positions -(N-2) .. -1
    right = 2 * x[-1] - x[N - 1 - j]  # positions N .. 2N-3
    ext = np.concatenate([left, x, right])
    o = N - 2  # offset of x[0] inside ext
    i = np.arange(1, N - 1) + o
    d = ext[i - m] - 2 * ext[i] + ext[i + m]
    ms, n = _nan_meansq(d)
    tau = m * tau0
    return np.sqrt(ms / (2 * tau * tau)), n


#: Upper bound on the element operations one tau of MTOT or Theo1 may spend
#: (see :func:`compute`, ``max_work``). Above it, subsequences are sampled
#: with a stride of at most ``m``.
MAX_WORK = 1 << 22
#: TheoBR bias ratio: at most this many terms of the average are evaluated
#: (evenly spaced) when ``max_work`` is not 0.
THEOBR_RATIO_TERMS = 64
_CHUNK = 1 << 21  # elements per block in the vectorised loops


def _valid_starts(x, span):
    """Start indices of the length-``span`` windows of ``x`` without NaN."""
    bad = np.concatenate(([0], np.cumsum(~np.isfinite(x))))
    return np.flatnonzero(bad[span:] - bad[:-span] == 0)


def _sample(starts, cost, m, opts):
    """Evenly strided subset of ``starts`` keeping about ``max_work`` element operations.

    The stride never exceeds ``m``: consecutive subsequences overlap by
    all but one sample, so the estimate barely changes, and every sample
    still falls inside some used subsequence.
    """
    budget = MAX_WORK if opts is None else opts.get("max_work", MAX_WORK)
    stride = 1
    if budget and starts.size * cost > budget:
        stride = int(min(max(m, 1), -(-starts.size * cost // budget)))
    if opts is not None:
        opts["stride"] = stride
    return starts[::stride]


def _mtot(x, m, tau0, opts=None):
    """Modified total deviation (NIST SP 1065 eq. (27), phase form).

    Vectorised over subsequences: each block of subsequences is detrended
    with its half-average slope, reflection-extended to ``9m`` samples and
    reduced with row-wise cumulative sums, the same arithmetic as the
    literal per-subsequence definition.
    """
    L = 3 * m
    if x.size - L + 1 < 1:
        return np.nan, 0
    starts = _sample(_valid_starts(x, L), 9 * m, m, opts)
    if starts.size == 0:
        return np.nan, 0
    h1 = L // 2
    h2 = L - h1
    denom = (0.5 * (L - 1) + 1.0) * tau0 if L % 2 else 0.5 * L * tau0
    t = np.arange(L, dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(x, L)
    total = 0.0
    step = max(1, _CHUNK // (9 * m))
    for b in range(0, starts.size, step):
        xs = windows[starts[b: b + step]]
        slope = (xs[:, h2:].mean(axis=1) - xs[:, :h1].mean(axis=1)) / denom
        x0 = xs - slope[:, None] * t * tau0
        xstar = np.concatenate((x0[:, ::-1], x0, x0[:, ::-1]), axis=1)
        c = np.zeros((xstar.shape[0], 9 * m + 1))
        np.cumsum(xstar, axis=1, out=c[:, 1:])
        w = c[:, m:] - c[:, :-m]
        d2 = (w[:, 2 * m: 8 * m] - 2.0 * w[:, m: 7 * m] + w[:, : 6 * m]) / float(m)
        total += float(np.sum(np.mean(d2 * d2, axis=1)))
    var = total / starts.size / (2.0 * (m * tau0) ** 2)
    return np.sqrt(var), int(starts.size)


def _theo1(x, m, tau0, opts=None):
    """Theo1 (NIST SP 1065 eq. (31)); m even, result belongs to tau = 0.75 m tau0."""
    N = x.size
    if m % 2 or m < 2 or m > N - 1:
        return np.nan, 0
    h = m // 2
    starts = _sample(_valid_starts(x, m + 1)[: N - m], h, m, opts)
    if starts.size == 0:
        return np.nan, 0
    weight = 1.0 / (h - np.arange(h))
    windows = np.lib.stride_tricks.sliding_window_view(x, m + 1)
    total = 0.0
    step = max(1, _CHUNK // (m + 1))
    for b in range(0, starts.size, step):
        r = windows[starts[b: b + step]]
        # delta = 0..h-1: x[i+h-delta] are columns h..1, x[i+h+delta] columns h..m-1
        term = (r[:, :1] - r[:, h:0:-1]) + (r[:, m:] - r[:, h:m])
        total += float(np.sum((term * term) @ weight))
    var = total / (0.75 * starts.size * (m * tau0) ** 2)
    return np.sqrt(var), int(starts.size)


def _theobr_ratio(x, tau0, opts=None):
    """TheoBR bias-removal factor kf (average AVAR/THEO1 variance ratio).

    Cached in ``opts`` so a whole tau grid pays for it once. With more than
    :data:`THEOBR_RATIO_TERMS` terms (records longer than about 400
    samples) and ``max_work`` not 0, an evenly spaced subset of the terms is
    averaged.
    """
    if opts is not None and "kf" in opts:
        return opts["kf"]
    N = x.size
    n = N // 6 - 3
    kf = np.nan
    if n >= 0:
        idx = np.arange(n + 1)
        exact = opts is not None and opts.get("max_work", MAX_WORK) == 0
        if idx.size > THEOBR_RATIO_TERMS and not exact:
            idx = np.unique(np.round(np.linspace(0, n, THEOBR_RATIO_TERMS)).astype(int))
        # each ratio term is one of many averaged: give it a smaller share
        budget = MAX_WORK if opts is None else opts.get("max_work", MAX_WORK)
        sub = {"max_work": budget // 8 if budget else 0}
        total, cnt = 0.0, 0
        for i in idx:
            da, _ = _oadev(x, 9 + 3 * int(i), tau0)
            dt, _ = _theo1(x, 12 + 4 * int(i), tau0, sub)
            if np.isfinite(da) and np.isfinite(dt) and dt > 0:
                total += (da * da) / (dt * dt)
                cnt += 1
        kf = np.nan if cnt == 0 else total / cnt
        if opts is not None:
            opts["kf_terms"] = int(idx.size)
            opts["kf_total_terms"] = int(n + 1)
    if opts is not None:
        opts["kf"] = kf
    return kf


def _theobr(x, m, tau0, opts=None):
    d, n = _theo1(x, m, tau0, opts)
    kf = _theobr_ratio(x, tau0, opts)
    return d * np.sqrt(kf), n


def _theoh_theo_m(m: int) -> int:
    return int(2 * max(1, round(m / 1.5)))


def _theoh_tau(m: int, n_phase: int, tau0: float) -> float:
    if m <= 0.2 * (n_phase - 1):
        return float(m) * tau0
    return 0.75 * _theoh_theo_m(m) * tau0


def _theoh(x, m, tau0, opts=None):
    N = x.size
    if m <= 0.2 * (N - 1):
        d, n = _adev(x, m, tau0)
        if opts is not None:
            opts["stride"] = 1
    else:
        d, n = _theobr(x, _theoh_theo_m(m), tau0, opts)
    return d, n, _theoh_tau(m, N, tau0)


def _tierms(x, m, tau0):
    """RMS time interval error, sqrt(mean((x[i+m] - x[i])^2)) (ITU-T G.810)."""
    d = x[m:] - x[:-m]
    ms, n = _nan_meansq(d)
    return np.sqrt(ms), n


_SAMPLED: Dict[str, Callable[..., tuple]] = {"mtot": _mtot, "theo1": _theo1, "theobr": _theobr, "theoh": _theoh}
_ESTIMATORS: Dict[str, Callable[..., tuple]] = {"adev": _adev, "oadev": _oadev, "mdev": _mdev, "tdev": _tdev, "hdev": _hdev,
               "totdev": _totdev, "mtot": _mtot, "theo1": _theo1, "theobr": _theobr, "tierms": _tierms}

_MAX_M = {
    "adev": lambda n: (n - 1) // 2,
    "oadev": lambda n: (n - 1) // 2,
    "mdev": lambda n: (n - 1) // 3,
    "tdev": lambda n: (n - 1) // 3,
    "hdev": lambda n: (n - 1) // 3,
    "totdev": lambda n: (n - 1) // 2,
    "mtot": lambda n: (n - 1) // 3,
    "ttot": lambda n: (n - 1) // 3,
    "theo1": lambda n: n - 1,
    "theobr": lambda n: n - 1,
    "theoh": lambda n: (3 * (n - 1)) // 4,
    "mtie": lambda n: n - 1,
    "tierms": lambda n: n - 1,
}


def compute(
    x: np.ndarray,
    tau0: float,
    kind: str = "oadev",
    taus: Union[str, Sequence[int]] = "octave",
    min_terms: int = 2,
    ci: Optional[float] = 0.683,
    max_work: Optional[int] = None,
    bias_correction: bool = True,
) -> StabilityResult:
    """Compute one stability statistic of phase data ``x`` (seconds).

    ``taus`` is a spacing name or a list of averaging factors ``m``.
    Points supported by fewer than ``min_terms`` terms are dropped.
    With ``ci`` (e.g. 0.683 or 0.95) the dominant noise type is identified
    at every tau (lag-1 autocorrelation) and a chi-squared confidence
    interval is attached using the equivalent degrees of freedom.

    MTOT and Theo1/TheoBR/TheoH cost O(N·m) per tau (TheoBR's bias ratio
    even more). ``max_work`` bounds the element operations per tau
    (default :data:`MAX_WORK`); above it the subsequences are sampled with
    an even stride of at most ``m`` and the TheoBR ratio averages
    :data:`THEOBR_RATIO_TERMS` evenly spaced terms. ``max_work=0`` always
    computes the full definitions. What was sampled is reported in
    ``meta["stride"]`` (per tau, 1 = every subsequence) and
    ``meta["theobr_ratio_terms"]``.

    MTOT and TTOT are divided by the MTOT bias factor of the noise type
    identified at each tau (:data:`MTOT_BIAS`), which is what Stable32 and
    NIST SP 1065 report; ``bias_correction=False`` returns the raw eq. (27)
    value. The factors used are in ``meta["bias_factor"]``.
    """
    kind = kind.lower()
    if kind not in KINDS:
        raise ValueError(f"unknown statistic {kind!r}; choose from {', '.join(KINDS)}")
    x = np.asarray(x, dtype=float)
    if x.size < 3:
        raise ValueError("need at least 3 samples")
    ms = tau_multipliers(x.size, taus, max_m=_MAX_M[kind](x.size))
    if kind in ("theo1", "theobr"):
        ms = ms[(ms % 2 == 0)]
    taus_out = None
    opts: Dict[str, object] = {"max_work": MAX_WORK if max_work is None else int(max_work)}
    strides = []
    if kind == "mtie":
        vals = _mtie_all(x, ms, tau0)
    elif kind in _SAMPLED or kind == "ttot":
        fn_s = _SAMPLED["mtot" if kind == "ttot" else kind]
        vals = []
        for m in ms:
            opts["stride"] = 1
            vals.append(fn_s(x, int(m), tau0, opts))
            strides.append(int(opts["stride"]))  # type: ignore[call-overload]
        if kind == "theoh":
            taus_out = np.array([v[2] for v in vals], dtype=float)
    else:
        fn = _ESTIMATORS[kind]
        vals = [fn(x, int(m), tau0) for m in ms]
    dev = np.array([v[0] for v in vals], dtype=float)
    n = np.array([v[1] for v in vals], dtype=float)
    keep = np.isfinite(dev) & (n >= min_terms)
    ms, dev, n = ms[keep], dev[keep], n[keep]
    if taus_out is not None:
        taus_out = taus_out[keep]
    err = np.where(n > 0, dev / np.sqrt(np.maximum(n, 1)), np.nan) if kind != "mtie" else np.zeros_like(dev)
    tau_scale = 0.75 if kind in ("theo1", "theobr") else 1.0
    taus_final = taus_out if taus_out is not None else (ms * float(tau0) * tau_scale)
    res = StabilityResult(kind=kind, tau0=float(tau0), taus=taus_final, dev=dev, err=err, n=n)
    if strides:
        res.meta["stride"] = [s for s, k in zip(strides, keep) if k]
    if "kf_terms" in opts:
        res.meta["theobr_ratio_terms"] = [opts["kf_terms"], opts["kf_total_terms"]]
    if kind in ("mtot", "ttot") and dev.size:
        return _finish_mtot(res, x, ms, ci, bias_correction)
    if ci and kind not in ("mtie", "tierms", "theo1", "theobr", "theoh") and dev.size:
        n_phase = int(np.isfinite(x).sum())
        alpha = np.array([noise_alpha(x, int(m)) for m in ms], dtype=float)
        # Where identification fails (too few points) inherit the neighbour's value.
        alpha = _fill_nan(alpha)
        edf = np.array([edf_for_result(kind, a, int(m), int(k), n_phase) for m, a, k in zip(ms, alpha, n)])
        res.lo, res.hi = chi2_interval(dev, edf, ci)
        res.edf, res.alpha, res.ci = edf, alpha, float(ci)
    elif kind in ("theo1", "theobr", "theoh", "tierms") and dev.size:
        res.alpha = _fill_nan(np.array([noise_alpha(x, max(int(m), 1)) for m in ms], dtype=float))
    return res


def _finish_mtot(res: StabilityResult, x: np.ndarray, ms: np.ndarray, ci: Optional[float],
                 bias_correction: bool) -> StabilityResult:
    """Bias correction, TTOT scaling and SP 1065 EDF-based CIs for MTOT/TTOT."""
    alpha = _fill_nan(np.array([noise_alpha(x, max(int(m), 1)) for m in ms], dtype=float))
    res.alpha = alpha
    key = [int(np.clip(round(a), -2, 2)) if np.isfinite(a) else 0 for a in alpha]
    if bias_correction:
        factor = np.array([MTOT_BIAS[k] for k in key])
        res.dev = res.dev / np.sqrt(factor)
        res.err = res.err / np.sqrt(factor)
        res.meta["bias_factor"] = factor.tolist()
    if res.kind == "ttot":
        scale = res.taus / np.sqrt(3.0)
        res.dev, res.err = res.dev * scale, res.err * scale
    if ci:
        record = float(np.isfinite(x).sum() - 1)  # T / tau0
        edf = np.array([max(MTOT_EDF[k][0] * record / m - MTOT_EDF[k][1], 1.0) for k, m in zip(key, ms)])
        res.lo, res.hi = chi2_interval(res.dev, edf, ci)
        res.edf, res.ci = edf, float(ci)
    return res


def edf_for_result(kind: str, alpha: float, m: int, terms: int, n_phase: int) -> float:
    """EDF used for confidence intervals.

    ADEV/OADEV/MDEV/TDEV/HDEV: exact discrete power-law EDF
    (:func:`ntpstats.edf.edf`). TOTDEV: NIST SP 1065 table 12 for FM noise
    (``b * T/tau - c``), OADEV EDF for PM noise.
    """
    from .edf import edf as _edf

    if kind == "totdev":
        a = int(round(alpha)) if np.isfinite(alpha) else 0
        table = {0: (1.500, 0.0), -1: (1.168, 0.222), -2: (0.927, 0.358)}
        if a in table:
            b, c = table[a]
            return float(max(b * n_phase / m - c, 1.0))
        return _edf("oadev", alpha, m, terms)
    return _edf(kind, alpha, m, terms)


def compute_many(x, tau0, kinds: Iterable[str] = ("oadev", "mdev", "tdev"), taus="octave") -> List[StabilityResult]:
    return [compute(x, tau0, k, taus) for k in kinds]


def series_stability(series, kinds=("oadev",), taus="octave", tau0=None, max_gap=3.0, detrend=None, ci=0.683,
                     max_work=None, bias_correction=True):
    """Convenience wrapper: resample a :class:`TimeSeries` and compute.

    ``detrend`` may be ``None``, ``"linear"`` (remove constant frequency
    offset, which ADEV is blind to anyway but TDEV/MTIE are not) or
    ``"quadratic"`` (also remove linear frequency drift). ``max_work`` is
    passed to :func:`compute` (0: never sample MTOT/Theo subsequences), as is
    ``bias_correction`` (MTOT/TTOT).
    """
    from .analysis import detrend as _detrend

    grid, x, tau0 = series.to_uniform(tau0=tau0, max_gap=max_gap)
    if detrend:
        ok = np.isfinite(x)
        x = x.copy()
        x[ok] = _detrend(grid[ok], x[ok], detrend)
    results = [compute(x, tau0, k, taus, ci=ci, max_work=max_work, bias_correction=bias_correction) for k in kinds]
    gaps = int(np.sum(~np.isfinite(x)))
    for r in results:
        r.meta.update({"grid_points": int(x.size), "gap_points": gaps, "regularity": series.regularity()})
    return results


# ------------------------------------------------------ noise identification
#: Log-log slope of ADEV/MDEV vs tau for the classic power-law noise types.
NOISE_SLOPES = {
    "oadev": {"white PM / flicker PM": -1.0, "white FM": -0.5, "flicker FM": 0.0, "random-walk FM": 0.5, "drift": 1.0},
    "mdev": {"white PM": -1.5, "flicker PM": -1.0, "white FM": -0.5, "flicker FM": 0.0, "random-walk FM": 0.5},
}


def slopes(result: StabilityResult) -> np.ndarray:
    """Local log-log slope between consecutive tau points."""
    if result.taus.size < 2:
        return np.array([])
    return np.diff(np.log10(result.dev)) / np.diff(np.log10(result.taus))


def identify_noise(result: StabilityResult) -> List[str]:
    """Rough dominant-noise label for each tau interval, from the local slope."""
    table = NOISE_SLOPES["mdev" if result.kind in ("mdev", "tdev") else "oadev"]
    labels = []
    for s in slopes(result):
        if result.kind == "tdev":
            s -= 1.0  # TDEV = tau * MDEV / sqrt(3)
        labels.append(min(table, key=lambda k: abs(table[k] - s)))
    return labels


# ------------------------------------------------ noise ID & confidence
def _lag1(z: np.ndarray) -> float:
    """Lag-1 autocorrelation using only pairs of adjacent finite samples."""
    ok = np.isfinite(z)
    if ok.sum() < 4:
        return np.nan
    zc = np.where(ok, z - z[ok].mean(), 0.0)
    pair = ok[:-1] & ok[1:]
    den = np.dot(zc, zc) / ok.sum()
    if den <= 0 or pair.sum() < 3:
        return np.nan
    return float(np.dot(zc[:-1][pair], zc[1:][pair]) / pair.sum() / den)


def noise_alpha(x: np.ndarray, m: int = 1, dmax: int = 2, min_points: int = 30) -> float:
    """Dominant power-law noise exponent ``alpha`` of phase data at averaging factor ``m``.

    Lag-1 autocorrelation method (W. Riley & C. Greenhall, "Power law noise
    identification using the lag 1 autocorrelation", EFTF 2004)::

        alpha =  2  white PM        alpha = -1  flicker FM
        alpha =  1  flicker PM      alpha = -2  random-walk FM
        alpha =  0  white FM

    Returns NaN if fewer than ``min_points`` decimated samples remain.
    """
    z = np.asarray(x, dtype=float)[:: max(1, int(m))]
    if np.isfinite(z).sum() < min_points:
        return np.nan
    d = 0
    while True:
        r1 = _lag1(z)
        if not np.isfinite(r1):
            return np.nan
        delta = r1 / (1 + r1)
        if delta < 0.25 or d >= dmax:
            p = -2 * (delta + d)
            return float(np.clip(np.round(p + 2), -2, 2)) + 0.0  # avoid -0.0
        z = np.diff(z)
        d += 1


def _fill_nan(a: np.ndarray) -> np.ndarray:
    a = a.copy()
    ok = np.isfinite(a)
    if not ok.any():
        a[:] = 0.0  # assume white FM
        return a
    idx = np.arange(a.size)
    a[~ok] = a[ok][np.clip(np.searchsorted(idx[ok], idx[~ok]) - 1, 0, ok.sum() - 1)]
    return a


def edf_approx(kind: str, N: int, m: int, alpha: float, terms: int) -> float:
    """Deprecated since 2.1: kept for API compatibility, now returns the
    exact EDF from :func:`edf_for_result`."""
    return edf_for_result(kind, alpha, m, terms, N)


def _chi2_ppf(p: float, k: np.ndarray) -> np.ndarray:
    """Chi-squared quantile, Wilson-Hilferty approximation (stdlib only)."""
    z = NormalDist().inv_cdf(p)
    k = np.asarray(k, dtype=float)
    c = 2.0 / (9.0 * k)
    return k * np.maximum(1 - c + z * np.sqrt(c), 1e-6) ** 3


def chi2_interval(dev: np.ndarray, edf: np.ndarray, ci: float = 0.683):
    """Two-sided confidence interval of a deviation given its EDF."""
    a = (1 - ci) / 2
    lo = dev * np.sqrt(edf / _chi2_ppf(1 - a, edf))
    hi = dev * np.sqrt(edf / _chi2_ppf(a, edf))
    return lo, hi


NOISE_NAMES = {2: "white PM", 1: "flicker PM", 0: "white FM", -1: "flicker FM", -2: "random-walk FM"}


# ------------------------------------------------------------ dynamic ADEV
@dataclass
class DynamicResult:
    kind: str
    tau0: float
    times: np.ndarray  # window centre times (POSIX s)
    taus: np.ndarray
    dev: np.ndarray  # shape (len(times), len(taus)); NaN where not computable
    window: float
    step: float

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "tau0": self.tau0,
            "times": self.times.tolist(),
            "taus": self.taus.tolist(),
            "dev": [[None if not np.isfinite(v) else float(v) for v in row] for row in self.dev],
            "window": self.window,
            "step": self.step,
        }


def dynamic(series, kind: str = "oadev", window: Optional[float] = None, step: Optional[float] = None,
            taus="octave", tau0=None, max_gap=3.0, detrend=None) -> DynamicResult:
    """Sliding-window stability ("dynamic ADEV") to expose non-stationarity.

    ``window`` and ``step`` are in seconds (defaults: 1/8 of the record and
    a quarter window). The tau grid is fixed by the window length so every
    column is comparable.
    """
    from .analysis import detrend as _detrend

    grid, x, tau0 = series.to_uniform(tau0=tau0, max_gap=max_gap)
    if detrend:
        ok = np.isfinite(x)
        x = x.copy()
        x[ok] = _detrend(grid[ok], x[ok], detrend)
    n = x.size
    span = grid[-1] - grid[0]
    window = float(window or max(span / 8, 32 * tau0))
    step = float(step or window / 4)
    wn = max(int(round(window / tau0)), 8)
    sn = max(int(round(step / tau0)), 1)
    if wn > n:
        raise ValueError("window longer than the record")
    ms = tau_multipliers(wn, taus, max_m=_MAX_M[kind](wn))
    if kind in ("theo1", "theobr"):
        ms = ms[ms % 2 == 0]
    starts = np.arange(0, n - wn + 1, sn)
    dev = np.full((starts.size, ms.size), np.nan)
    for r, a in enumerate(starts):
        seg = x[a: a + wn]
        if np.isfinite(seg).sum() < wn // 2:
            continue
        res = compute(seg, tau0, kind, [int(m) for m in ms], ci=None, min_terms=2)
        if kind == "theoh":
            taus_target = np.array([_theoh_tau(int(m), wn, tau0) for m in ms], dtype=float)
        else:
            taus_target = ms * tau0 * (0.75 if kind in ("theo1", "theobr") else 1.0)
        idx = np.searchsorted(taus_target, res.taus)
        dev[r, idx] = res.dev
    if kind == "theoh":
        taus_out = np.array([_theoh_tau(int(m), wn, tau0) for m in ms], dtype=float)
    else:
        taus_out = ms * tau0 * (0.75 if kind in ("theo1", "theobr") else 1.0)
    return DynamicResult(kind, tau0, grid[starts] + wn * tau0 / 2, taus_out, dev, window, step)
