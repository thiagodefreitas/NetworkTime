# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Power-law noise model: fit h_α (S_y(f) = Σ h_α f^α) to stability curves and spectra.

The five coefficients h₂ (white PM), h₁ (flicker PM), h₀ (white FM), h₋₁
(flicker FM) and h₋₂ (random-walk FM) summarise a clock, and are what the
simulator, Kalman filters and holdover prediction need.

**Model.** Sampled phase with power-law noise is the Kasdin–Walter process
``x = h_α * w`` (``w`` white, variance Q), whose discrete spectrum is
``S_x(f) = 2 Q τ0 / (2 sin πfτ0)^(2-α)``. For ``f ≪ 1/τ0`` this is
``h_α f^α / (2πf)²`` with ``h_α = 2 Q (2π)^α τ0^(α-1)``. The expected value
of every estimator (ADEV, OADEV, MDEV, TDEV, HDEV) is then an exact linear
function of the h_α (the same filter algebra as :mod:`ntpstats.edf`), so no
continuous-time bandwidth assumption is needed for white and flicker PM.

**Fit.** Non-negative weighted least squares on the variances, with weights
from the equivalent degrees of freedom (Var σ̂² ≈ 2σ⁴/EDF, iterated with the
model values), over every subset of noise types; the subset with the lowest
BIC (χ² + k ln n) wins, so a noise type is only reported when the data need it. Confidence intervals come from the covariance of the active
coefficients (log-normal, so they stay positive; approximate, because points
of a stability curve are correlated) or, by default in :func:`fit_series`,
from a parametric bootstrap that re-simulates the fitted model with the same
length.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .edf import _autocov
from .spectrum import Spectrum
from .stability import NOISE_NAMES, StabilityResult

ALPHAS = (2, 1, 0, -1, -2)
FIT_KINDS = ("adev", "oadev", "mdev", "tdev", "hdev")


def q_from_h(h: float, alpha: int, tau0: float) -> float:
    """Innovation variance Q of the Kasdin–Walter phase filter giving coefficient ``h``."""
    return h / (2.0 * (2 * np.pi) ** alpha * tau0 ** (alpha - 1))


def h_from_q(q: float, alpha: int, tau0: float) -> float:
    return 2.0 * q * (2 * np.pi) ** alpha * tau0 ** (alpha - 1)


def simulate(h: Dict[int, float], n: int, tau0: float, seed=None) -> np.ndarray:
    """Phase samples (s) with the given h_α (Kasdin–Walter, as in :func:`simulate.powerlaw_phase`)."""
    from .simulate import powerlaw_phase

    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for a, v in h.items():
        if v > 0:
            x += powerlaw_phase(n, int(a), float(np.sqrt(q_from_h(v, int(a), tau0))), rng)
    return x


def _norm(kind: str, m: int, tau0: float) -> float:
    if kind in ("adev", "oadev"):
        return 2.0 * m * m * tau0 * tau0
    if kind == "mdev":
        return 2.0 * m ** 4 * tau0 * tau0
    if kind == "tdev":
        return 2.0 * m ** 4 * tau0 * tau0 * 3.0 / (m * tau0) ** 2
    if kind == "hdev":
        return 6.0 * m * m * tau0 * tau0
    raise ValueError(f"no power-law model for {kind}")


def basis(kind: str, m: int, alpha: int, tau0: float) -> float:
    """Expected variance (dev²) of ``kind`` at averaging factor ``m`` for h_α = 1."""
    est = "mdev" if kind == "tdev" else kind
    rho0 = float(_autocov(est, int(alpha), int(m), 0)[0])
    return q_from_h(1.0, alpha, tau0) * rho0 / _norm(kind, m, tau0)


def spectrum_basis(kind: str, f: np.ndarray, alpha: int, tau0: float) -> np.ndarray:
    """Discrete-model PSD for h_α = 1: S_x (kind 'x') or S_y of first differences (kind 'y')."""
    s = np.abs(2 * np.sin(np.pi * np.asarray(f) * tau0))
    sx = 2 * q_from_h(1.0, alpha, tau0) * tau0 / s ** (2 - alpha)
    return sx if kind == "x" else sx * (s / tau0) ** 2


def predict(h: Dict[int, float], kind: str, taus: Sequence[float], tau0: float) -> np.ndarray:
    """Deviation predicted by the model at ``taus`` (multiples of ``tau0``)."""
    out = []
    for t in taus:
        m = max(1, int(round(t / tau0)))
        out.append(np.sqrt(sum(v * basis(kind, m, a, tau0) for a, v in h.items() if v > 0)))
    return np.array(out)


@dataclass
class NoiseFit:
    h: Dict[int, float]
    lo: Dict[int, float]
    hi: Dict[int, float]
    tau0: float
    ci: float
    chi2: float
    dof: int
    method: str = "analytic"
    active: Tuple[int, ...] = ()
    drift: float = 0.0  # |linear frequency drift| (1/s) fitted with ``drift=True``, else 0
    drift_hi: float = 0.0
    corners: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)
    #: plausible coefficient sets from the bootstrap (reflected around the estimate), for propagating uncertainty
    samples: List[Dict[int, float]] = field(default_factory=list, repr=False)

    @property
    def reduced_chi2(self) -> float:
        return self.chi2 / self.dof if self.dof > 0 else float("nan")

    def predict(self, kind: str, taus: Sequence[float]) -> np.ndarray:
        """Model deviation at ``taus``, including a fitted drift."""
        dev = predict(self.h, kind, taus, self.tau0)
        if self.drift:
            d = np.array([drift_basis(kind, max(1, int(round(t / self.tau0))), self.tau0) for t in taus])
            dev = np.sqrt(dev ** 2 + self.drift ** 2 * d)
        return dev

    def dominant(self, kind: str, taus: Iterable[float]) -> List[Optional[int]]:
        """Noise type contributing most to ``kind`` at each tau."""
        out: List[Optional[int]] = []
        for t in taus:
            m = max(1, int(round(t / self.tau0)))
            c = {a: v * basis(kind, m, a, self.tau0) for a, v in self.h.items() if v > 0}
            out.append(max(c, key=lambda a: c[a]) if c else None)
        return out

    def as_dict(self) -> dict:
        return {"h": {str(a): self.h[a] for a in ALPHAS}, "lo": {str(a): self.lo[a] for a in ALPHAS},
                "hi": {str(a): self.hi[a] for a in ALPHAS}, "noise": {str(a): NOISE_NAMES[a] for a in ALPHAS},
                "tau0": self.tau0, "ci": self.ci, "chi2": self.chi2, "dof": self.dof,
                "reduced_chi2": self.reduced_chi2, "method": self.method, "active": list(self.active),
                "drift": self.drift, "drift_hi": self.drift_hi, "corners": self.corners, "meta": self.meta}

    def scenario_clock(self) -> Dict[str, object]:
        """``[clock]`` table for a simulator scenario reproducing this noise."""
        return {"h_alpha": {str(a): v for a, v in self.h.items() if v > 0}, "freq_offset": 0.0, "drift": 0.0}


def drift_basis(kind: str, m: int, tau0: float) -> float:
    """Variance a linear frequency drift D = 1 adds to ``kind`` (AVAR, MVAR: D²τ²/2; HVAR: 0)."""
    tau = m * tau0
    if kind == "hdev":
        return 0.0
    return tau * tau / 2 * (tau * tau / 3 if kind == "tdev" else 1.0)


def _rows(results: Iterable[StabilityResult], spectra: Iterable[Spectrum], alphas: Sequence[int], drift=False):
    A, y, edf = [], [], []
    tau0 = None
    for r in results:
        if r.kind not in FIT_KINDS:
            raise ValueError(f"cannot fit {r.kind}; use {', '.join(FIT_KINDS)}")
        tau0 = r.tau0
        e = r.edf if r.edf is not None else np.maximum(r.n, 1.0)
        for t, d, k in zip(r.taus, r.dev, e):
            if np.isfinite(d) and d > 0 and np.isfinite(k) and k > 0:
                m = int(round(t / r.tau0))
                A.append([basis(r.kind, m, a, r.tau0) for a in alphas]
                         + ([drift_basis(r.kind, m, r.tau0)] if drift else []))
                y.append(d * d)
                edf.append(float(k))
    for sp in spectra:
        tau0 = tau0 or sp.tau0
        for f, p, k in list(zip(sp.f, sp.psd, sp.dof))[2:]:  # lowest bins: detrending/leakage bias
            if p > 0 and f < 0.4 / sp.tau0:
                A.append([float(spectrum_basis(sp.kind, np.array([f]), a, sp.tau0)[0]) for a in alphas]
                         + ([0.0] if drift else []))
                y.append(p)
                edf.append(float(k))
    if not y:
        raise ValueError("nothing to fit")
    return np.array(A), np.array(y), np.array(edf), tau0


def _wls(A, y, w):
    scale = np.sqrt(np.sum(A * A * w[:, None], axis=0))
    scale[scale == 0] = 1.0
    As = A / scale
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(As * sw[:, None], y * sw, rcond=None)
    return coef / scale


def _cov(A, w):
    """Covariance of weighted least-squares coefficients, computed with scaled columns (conditioning)."""
    scale = np.sqrt(np.sum(A * A * w[:, None], axis=0))
    scale[scale == 0] = 1.0
    As = A / scale
    return np.linalg.pinv(As.T @ (As * w[:, None])) / np.outer(scale, scale)


def _nnls(A, y, w, alphas, penalty=0.0):
    best = None
    for k in range(1, A.shape[1] + 1):
        for sub in itertools.combinations(range(A.shape[1]), k):
            c = _wls(A[:, sub], y, w)
            if np.any(c <= 0):
                continue
            chi2 = float(np.sum(w * (y - A[:, sub] @ c) ** 2))
            score = chi2 + penalty * len(sub)
            if best is None or score < best[0]:
                best = (score, sub, c, chi2)
    if best is None:
        raise ValueError("no positive power-law model fits the data")
    return best[3], best[1], best[2]


def fit(results: Iterable[StabilityResult] = (), spectra: Iterable[Spectrum] = (), alphas: Sequence[int] = ALPHAS,
        ci: float = 0.683, iterations: int = 6, selection: str = "bic", drift: bool = False) -> NoiseFit:
    """Fit h_α to stability results (ADEV/OADEV/MDEV/TDEV/HDEV, with EDF) and/or spectra.

    ``drift=True`` also fits a linear frequency drift (D²τ²/2 in AVAR/MVAR), so
    drift in the data is not mistaken for random-walk FM.
    """
    results, spectra = list(results), list(spectra)
    alphas = tuple(int(a) for a in alphas)
    A, y, edf, tau0 = _rows(results, spectra, alphas, drift)
    penalty = float(np.log(y.size)) if selection == "bic" else 0.0  # BIC: a noise type must earn its place
    max_tau = max([float(np.nanmax(r.taus)) for r in results if r.taus.size] + [float(tau0)])
    w = edf / (2 * y * y)
    for _ in range(iterations):
        chi2, sub, c = _nnls(A, y, w, alphas, penalty)
        model = A[:, sub] @ c
        w = edf / (2 * model * model)
    chi2, sub, c = _nnls(A, y, w, alphas, penalty)
    z = NormalDist().inv_cdf(0.5 + ci / 2)
    As = A[:, sub]
    cov = _cov(As, w)
    h = {a: 0.0 for a in ALPHAS}
    lo = {a: 0.0 for a in ALPHAS}
    hi = {a: 0.0 for a in ALPHAS}
    d_val = d_hi = 0.0
    rel_se: Dict[int, float] = {}
    upper: Dict[int, Tuple[float, float]] = {}
    for j, i in enumerate(sub):
        se = float(np.sqrt(max(cov[j, j], 0.0)))
        if i >= len(alphas):  # drift column (holds D²)
            d_val, d_hi = float(np.sqrt(c[j])), float(np.sqrt(c[j] + z * se))
            continue
        a = alphas[i]
        h[a] = float(c[j])
        r = min(se / c[j], 50.0)
        lo[a], hi[a] = float(c[j] * np.exp(-z * r)), float(c[j] * np.exp(z * r))
        rel_se[a] = r
    for i in range(A.shape[1]):  # inactive terms: an upper limit from the unconstrained fit with them added
        if i in sub:
            continue
        cols = tuple(sorted(sub + (i,)))
        cf = _wls(A[:, cols], y, w)
        cv = _cov(A[:, cols], w)
        j = cols.index(i)
        se_j = float(np.sqrt(max(cv[j, j], 0.0)))
        up = float(max(cf[j], 0.0) + z * se_j)
        if i >= len(alphas):
            d_hi = float(np.sqrt(up))
        else:
            hi[alphas[i]] = up
            upper[alphas[i]] = (float(max(cf[j], 0.0)), se_j)
    out = NoiseFit(h, lo, hi, float(tau0), ci, chi2, int(y.size - len(sub)), "analytic",
                   tuple(alphas[i] for i in sub if i < len(alphas)), d_val, d_hi)
    out.meta["max_tau"] = max_tau
    out.meta["_rel_se"], out.meta["_upper"] = rel_se, upper
    out.corners = corner_taus(out)
    out.meta["points"] = int(y.size)
    out.meta["inputs"] = [r.kind for r in results] + [f"S_{s.kind}(f)" for s in spectra]
    return out


def corner_taus(nf: NoiseFit, kind: str = "oadev", max_tau: Optional[float] = None) -> List[Dict[str, Any]]:
    """Averaging times (up to ``max_tau``, default the longest fitted tau) where the dominant noise type changes."""
    top = max_tau or float(nf.meta.get("max_tau", nf.tau0 * 1e4))  # type: ignore[arg-type]
    taus = nf.tau0 * np.unique(np.round(np.logspace(0, np.log10(max(top / nf.tau0, 1.0)), 120)).astype(int))
    dom = nf.dominant(kind, taus)
    out: List[Dict[str, Any]] = []
    for i in range(1, len(taus)):
        a, b = dom[i - 1], dom[i]
        if a is not None and b is not None and a != b:
            out.append({"tau": float(taus[i]), "from": NOISE_NAMES[a], "to": NOISE_NAMES[b]})
    return out


def fit_phase(x: np.ndarray, tau0: float, kinds: Sequence[str] = ("oadev",), spectrum: bool = False,
              ci: float = 0.683, bootstrap: int = 100, seed=0, alphas: Sequence[int] = ALPHAS,
              selection: str = "bic", drift: bool = False) -> NoiseFit:
    """Fit h_α to evenly sampled phase ``x`` (s; NaN marks gaps).

    ``bootstrap=N`` (default 100) replaces the analytic intervals by a basic
    bootstrap interval on a log scale from N refits of data simulated with the
    fitted model (same length, gaps and tau grid). The analytic intervals
    treat the points of a curve as independent, which they are not, so they
    are too narrow; in Monte Carlo tests the bootstrap intervals hold their
    stated coverage. ``bootstrap=0`` is fast and approximate.
    """
    from .spectrum import frequency_psd, log_bins
    from .stability import compute

    x = np.asarray(x, dtype=float)
    gaps = ~np.isfinite(x)

    def stats(v, ms=None):
        rr = [compute(v, tau0, k, "octave" if ms is None else list(m), ci=0.683)
              for k, m in zip(kinds, ms or [None] * len(kinds))]
        sp = [log_bins(frequency_psd(v, tau0))] if spectrum else []
        return rr, sp

    res, sps = stats(x)
    nf = fit(res, sps, alphas=alphas, ci=ci, selection=selection, drift=drift)
    if bootstrap:
        ms = [np.round(r.taus / r.tau0).astype(int) for r in res]
        rng = np.random.default_rng(seed)
        samples: Dict[int, List[float]] = {a: [] for a in ALPHAS}
        sets: List[Dict[int, float]] = []
        for _ in range(int(bootstrap)):
            xb = simulate(nf.h, x.size, tau0, rng) + 0.5 * nf.drift * (np.arange(x.size) * tau0) ** 2
            xb[gaps] = np.nan
            try:
                rb, sb = stats(xb, ms)
                b = fit(rb, sb, alphas=alphas, ci=ci, selection=selection, drift=drift)
            except ValueError:
                continue
            for a in ALPHAS:
                samples[a].append(b.h[a])
            sets.append(dict(b.h))
        q = (0.5 - ci / 2) * 100, (0.5 + ci / 2) * 100
        # The analytic errors treat correlated points of a curve as independent; the bootstrap shows by how
        # much that understates the spread. Use the same factor for upper limits of undetected types.
        rel_se: Dict[int, float] = nf.meta.pop("_rel_se", {})  # type: ignore[assignment]
        upper: Dict[int, Tuple[float, float]] = nf.meta.pop("_upper", {})  # type: ignore[assignment]
        ratios = []
        for a, r in rel_se.items():
            pos = np.asarray([v for v in samples[a] if v > 0])
            if pos.size > 5 and r > 0:
                ratios.append(float(np.std(np.log(pos))) / r)
        inflate = float(np.clip(np.median(ratios), 1.0, 10.0)) if ratios else 1.0
        nf.meta["error_inflation"] = inflate
        z = NormalDist().inv_cdf(0.5 + ci / 2)
        z95 = NormalDist().inv_cdf(0.975)
        # plausible true coefficient sets (for holdover): reflected refits on a log scale; a type the data
        # could not detect may still be there, up to its (inflated) 95 % upper limit
        up95 = {a: upper.get(a, (0.0, 0.0))[0] + z95 * upper.get(a, (0.0, 0.0))[1] * inflate for a in ALPHAS}
        nf.samples = [{a: (nf.h[a] ** 2 / b[a] if b[a] > 0 else nf.h[a]) if nf.h[a] > 0
                       else float(up95[a] * rng.uniform() ** 2) for a in ALPHAS} for b in sets]
        for a in ALPHAS:
            if not samples[a]:
                continue
            smp = np.asarray(samples[a])
            p_lo, p_hi = np.percentile(smp, q)
            pos = smp[smp > 0]
            if nf.h[a] > 0 and pos.size:
                # basic bootstrap interval on a log scale: corrects the fit's bias and keeps h positive.
                # Refits that dropped the type (h = 0) say the estimate may be too low: they widen the top.
                # When refits often drop the type, it may be absent (lower bound 0) or stronger than estimated.
                lo_ref = p_lo if p_lo > 0 else float(np.percentile(pos, q[0]))
                nf.lo[a] = float(nf.h[a] ** 2 / p_hi) if p_lo > 0 else 0.0
                nf.hi[a] = float(nf.h[a] ** 2 / lo_ref) * (1.0 if p_lo > 0 else float(smp.size / pos.size))
                # never narrower than the analytic interval with the bootstrap-calibrated error
                r = min(rel_se.get(a, 0.0) * inflate, 50.0)
                nf.lo[a] = min(nf.lo[a], float(nf.h[a] * np.exp(-z * r)))
                nf.hi[a] = max(nf.hi[a], float(nf.h[a] * np.exp(z * r)))
            else:
                cf, se = upper.get(a, (0.0, 0.0))
                nf.lo[a], nf.hi[a] = 0.0, float(max(p_hi, nf.h[a], cf + z * se * inflate))
        nf.method = f"bootstrap ({len(samples[ALPHAS[0]])})"
    nf.meta.pop("_rel_se", None)
    nf.meta.pop("_upper", None)
    nf.meta.update(samples=int(x.size), gap_points=int(gaps.sum()))
    return nf


def fit_series(series, kinds: Sequence[str] = ("oadev",), spectrum: bool = False, ci: float = 0.683,
               bootstrap: int = 100, seed=0, alphas: Sequence[int] = ALPHAS, tau0: Optional[float] = None,
               max_gap: float = 3.0, detrend: Optional[str] = "linear", drift: bool = False) -> NoiseFit:
    """:func:`fit_phase` on a :class:`TimeSeries` (resampled; ``detrend`` removes offset/frequency/drift)."""
    from .analysis import detrend as _detrend

    grid, x, tau0 = series.to_uniform(tau0=tau0, max_gap=max_gap)
    if detrend:
        ok = np.isfinite(x)
        x = x.copy()
        x[ok] = _detrend(grid[ok], x[ok], detrend)
    nf = fit_phase(x, tau0, kinds, spectrum, ci, bootstrap, seed, alphas, drift=drift)
    nf.meta["name"] = series.name
    return nf
