# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Separate the stability of each clock (or server) from pairwise differences.

With three or more sources and no better reference, only differences are
observable. A client that measures several NTP servers gets
``o_i = x_i - x_client``; in ``o_i - o_j`` the client's own noise cancels,
so the same methods apply to ``ntpstats monitor`` logs.

* **Three-cornered hat** (Gray & Allan 1974): ``σ²_A = (σ²_AB + σ²_AC - σ²_BC) / 2``.
  Negative results are possible when the sources' noise levels differ a lot
  or are correlated; they are flagged, not hidden.
* **N-cornered hat**: least squares over all pairs (σ²_ij = σ²_i + σ²_j).
* **Groslambert covariance** (Vernotte, Lantz et al.): ``σ²_A`` is the
  cross-covariance of the Allan-filtered differences AB and AC, averaged
  over all pairs of other sources. For three sources and the same terms the
  estimate equals the three-cornered hat exactly (polarisation identity; see
  Vernotte, Calosso & Rubiola, IFCS 2016). What differs is the uncertainty:
  the covariance view gives an interval that holds its coverage when one
  source dominates, where propagating pairwise variances does not.

Confidence intervals propagate the variance of each pairwise estimate
(2σ⁴/EDF, EDF as in :mod:`ntpstats.edf`) or, for the covariance,
``Var(z₁z₂) = E[z₁²]E[z₂²] + E[z₁z₂]²`` with the same effective number of
terms; correlation between pairs is neglected, so they are approximate.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .series import TimeSeries
from .stability import compute, tau_multipliers

METHODS = ("gcov", "3ch", "nch")


@dataclass
class HatResult:
    method: str
    names: List[str]
    tau0: float
    taus: np.ndarray
    var: np.ndarray  # (sources, taus) individual Allan variances, may be negative
    lo: np.ndarray  # deviation CI; lo = 0 when the variance is not significantly positive
    hi: np.ndarray
    ci: float
    pairs: Dict[str, np.ndarray] = field(default_factory=dict)  # pairwise ADEV
    meta: Dict[str, object] = field(default_factory=dict)

    @property
    def dev(self) -> np.ndarray:
        """Individual ADEV; NaN where the variance estimate is negative."""
        with np.errstate(invalid="ignore"):
            return np.where(self.var > 0, np.sqrt(np.abs(self.var)), np.nan)

    @property
    def negative(self) -> np.ndarray:
        return self.var <= 0

    def as_dict(self) -> dict:
        def lst(a):
            return [None if not np.isfinite(v) else float(v) for v in a]

        return {"method": self.method, "names": self.names, "tau0": self.tau0, "taus": lst(self.taus),
                "ci": self.ci, "sources": {n: {"adev": lst(self.dev[i]), "var": lst(self.var[i]),
                                               "lo": lst(self.lo[i]), "hi": lst(self.hi[i]),
                                               "negative": [bool(b) for b in self.negative[i]]}
                                           for i, n in enumerate(self.names)},
                "pairs": {k: lst(v) for k, v in self.pairs.items()}, "meta": self.meta}


def align(series: Sequence[TimeSeries], tau0: Optional[float] = None, max_gap: float = 3.0
          ) -> Tuple[np.ndarray, np.ndarray, float]:
    """Common uniform grid over the overlap; NaN where a source has no sample within ``max_gap`` intervals."""
    if len(series) < 3:
        raise ValueError("need at least three sources")
    ss = [s.sorted() for s in series]
    if tau0 is None:
        tau0 = max(s.median_interval() for s in ss)
    start, end = max(s.t[0] for s in ss), min(s.t[-1] for s in ss)
    if end - start < 8 * tau0:
        raise ValueError("the sources do not overlap long enough")
    grid = start + tau0 * np.arange(int(np.floor((end - start) / tau0)) + 1)
    X = np.empty((len(ss), grid.size))
    for i, s in enumerate(ss):
        X[i] = np.interp(grid, s.t, s.offset)
        k = np.clip(np.searchsorted(s.t, grid), 1, s.t.size - 1)
        span = s.t[k] - s.t[k - 1]
        X[i, span > max_gap * tau0] = np.nan
    return grid, X, float(tau0)


def _d2(x: np.ndarray, m: int) -> np.ndarray:
    return x[2 * m:] - 2 * x[m:-m] + x[: -2 * m]


def _pair_avar(X, i, j, tau0, ms):
    r = compute(X[i] - X[j], tau0, "oadev", list(ms), ci=0.683)
    return r


def hat(X: np.ndarray, tau0: float, names: Optional[Sequence[str]] = None, method: str = "gcov",
        taus="octave", ci: float = 0.683) -> HatResult:
    """Individual Allan variances of the N sources in the rows of ``X`` (phase, s; NaN = gap)."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    X = np.asarray(X, dtype=float)
    n = X.shape[0]
    if n < 3:
        raise ValueError("need at least three sources")
    if method == "3ch" and n != 3:
        raise ValueError("the three-cornered hat takes exactly three sources; use nch or gcov")
    names = list(names or [f"s{i + 1}" for i in range(n)])
    ms = tau_multipliers(X.shape[1], taus, max_m=X.shape[1] // 4)
    pairs = list(itertools.combinations(range(n), 2))
    pr = {p: _pair_avar(X, p[0], p[1], tau0, ms) for p in pairs}
    ms = np.round(pr[pairs[0]].taus / tau0).astype(int)
    for p in pairs:  # keep taus every pair supports
        ms = ms[np.isin(ms, np.round(pr[p].taus / tau0).astype(int))]
    T = ms.size
    pv, pe = {}, {}  # pair variance and equivalent terms (EDF/2) at the kept taus
    for p, r in pr.items():
        sel = np.isin(np.round(r.taus / tau0).astype(int), ms)
        pv[p] = r.dev[sel] ** 2
        e = r.edf[sel] if r.edf is not None else r.n[sel]
        pe[p] = np.maximum(np.asarray(e, dtype=float) / 2, 1.0)
    var = np.zeros((n, T))
    sd = np.zeros((n, T))  # standard error of each variance estimate
    if method in ("3ch", "nch"):
        A = np.zeros((len(pairs), n))
        for k, (i, j) in enumerate(pairs):
            A[k, i] = A[k, j] = 1.0
        P = np.linalg.pinv(A)  # n x pairs
        Y = np.array([pv[p] for p in pairs])  # pairs x T
        V = np.array([2 * pv[p] ** 2 / (2 * pe[p]) for p in pairs])  # Var of each pair variance
        var = P @ Y
        sd = np.sqrt((P ** 2) @ V)
    else:
        for i in range(n):
            others = [j for j in range(n) if j != i]
            for t, m in enumerate(ms):
                est, v = [], []
                for j, k in itertools.combinations(others, 2):
                    a, b = _d2(X[i] - X[j], m), _d2(X[i] - X[k], m)
                    ok = np.isfinite(a) & np.isfinite(b)
                    if ok.sum() < 2:
                        continue
                    g = float(np.mean(a[ok] * b[ok])) / (2 * (m * tau0) ** 2)
                    s_ij = pv[(min(i, j), max(i, j))][t]
                    s_ik = pv[(min(i, k), max(i, k))][t]
                    terms = min(pe[(min(i, j), max(i, j))][t], pe[(min(i, k), max(i, k))][t])
                    est.append(g)
                    v.append((s_ij * s_ik + g * g) / terms)
                var[i, t] = np.mean(est) if est else np.nan
                sd[i, t] = np.sqrt(np.mean(v) / max(len(v), 1)) if v else np.nan
    z = NormalDist().inv_cdf(0.5 + ci / 2)
    lo_v, hi_v = var - z * sd, var + z * sd
    lo = np.sqrt(np.clip(lo_v, 0, None))
    hi = np.sqrt(np.clip(hi_v, 0, None))
    out = HatResult(method, names, tau0, ms * tau0, var, lo, hi, ci,
                    {f"{names[i]}-{names[j]}": np.sqrt(pv[(i, j)]) for i, j in pairs},
                    {"samples": int(X.shape[1])})
    neg = out.negative & np.isfinite(var)
    if neg.any():
        out.meta["negative_variances"] = int(neg.sum())
    return out


def hat_series(series: Sequence[TimeSeries], method: str = "gcov", tau0: Optional[float] = None,
               max_gap: float = 3.0, taus="octave", ci: float = 0.683) -> HatResult:
    """:func:`hat` on offset series measured by one client (or against one reference)."""
    grid, X, tau0 = align(series, tau0, max_gap)
    r = hat(X, tau0, [s.name for s in series], method, taus, ci)
    r.meta.update(start=float(grid[0]), end=float(grid[-1]))
    return r
