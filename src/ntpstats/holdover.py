# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Holdover: predicted time error after the reference is lost, and time to violation.

The question is operational: *if GNSS or the upstream network goes away now,
how long does this clock stay within 1.1 µs, 100 µs or 1 ms?*

**Input.** The phase of the oscillator against a reference while the
reference was available: a free-running measurement (TIC, a GNSSDO against
a better reference), or the frequency correction a disciplining daemon logs
(chrony's ``frequency`` column), integrated to phase.

**Holdover model.** At the loss time ``T`` the clock is aligned and then
runs on the frequency (``model="frequency"``), or frequency and drift
(``model="drift"``), fitted by least squares over the last ``window`` of
data. The time error after ``t`` is::

    TIE(t) = x(T+t) - x(T) - [fit(T+t) - fit(T)]

This is a linear function of the phase samples, so for power-law noise with
coefficients h_α (fitted with :mod:`ntpstats.noisefit`, Kasdin–Walter model)
its variance is computed *exactly*, including the error of the fitted
frequency and drift. With ``model="frequency"`` a fitted drift gives the
mean of TIE(t); with ``model="drift"`` the mean is zero. The envelope is
``mean ± z·σ``, and the time to violation is when it first leaves a limit.

:func:`backtest` checks the prediction on the data itself: it cuts the
reference out at many points of a long log and counts how often the real
TIE stays inside the envelope (calibration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Dict, List, Optional, Sequence

import numpy as np

from .edf import _phase_filter
from .noisefit import ALPHAS, NoiseFit, fit_phase, q_from_h
from .series import TimeSeries

MODELS = ("frequency", "drift")
MAX_POINTS = 2048


@dataclass
class HoldoverResult:
    t: np.ndarray  # s after the loss of reference
    mean: np.ndarray  # predicted TIE (s)
    sd: np.ndarray  # standard deviation of TIE (s)
    ci: float
    model: str
    window: float  # s of data used to fit frequency (and drift)
    h: Dict[int, float]
    frequency: float  # fitted fractional frequency at T
    drift: float  # fitted drift, 1/s
    limits: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    meta: Dict[str, object] = field(default_factory=dict)

    @property
    def z(self) -> float:
        return NormalDist().inv_cdf(0.5 + self.ci / 2)

    @property
    def lo(self) -> np.ndarray:
        return self.mean - self.z * self.sd

    @property
    def hi(self) -> np.ndarray:
        return self.mean + self.z * self.sd

    def time_to(self, limit: float) -> Dict[str, Optional[float]]:
        """First t where the envelope (and where the mean) leaves ±limit; None if not within the horizon."""
        env = np.maximum(np.abs(self.lo), np.abs(self.hi))

        def first(v):
            k = np.flatnonzero(v > limit)
            if not k.size:
                return None
            i = int(k[0])
            if i == 0:
                return float(self.t[0])
            # log-log interpolation between the bracketing horizons
            a, b = np.log(v[i - 1]), np.log(v[i])
            f = (np.log(limit) - a) / (b - a) if b > a else 1.0
            return float(np.exp(np.log(self.t[i - 1]) + f * (np.log(self.t[i]) - np.log(self.t[i - 1]))))

        return {"envelope": first(env), "mean": first(np.abs(self.mean))}

    def as_dict(self) -> dict:
        return {"t": self.t.tolist(), "mean": self.mean.tolist(), "sd": self.sd.tolist(), "lo": self.lo.tolist(),
                "hi": self.hi.tolist(), "ci": self.ci, "model": self.model, "window": self.window,
                "h": {str(a): v for a, v in self.h.items()}, "frequency": self.frequency, "drift": self.drift,
                "limits": self.limits, "meta": self.meta}


def _q(h: float, alpha: int, tau: float, tau0: float) -> float:
    # Sub-sampling keeps the per-sample variance of white PM; the other types scale with the interval.
    return q_from_h(h, alpha, tau0 if alpha == 2 else tau)


class _Predictor:
    """The holdover error as a linear functional of the (sub-sampled) phase.

    ``TIE(t) - mean(t) = x(T+t) - x(T) + (U @ gamma(t)) . x_W``, where x_W are
    the samples of the fitting window. For a frequency (drift) holdover the
    columns of U come from the linear (quadratic) least-squares fit. When a
    frequency holdover also predicts the effect of a fitted drift, U gains the
    weights of the drift estimate, so its uncertainty is part of the variance.
    """

    def __init__(self, xs: np.ndarray, window_pts: int, deg: int, drift_mean: bool, tau: float):
        valid = np.isfinite(xs)
        self.T = xs.size - 1
        idx = np.arange(max(0, xs.size - window_pts), xs.size)
        self.W = idx[valid[idx]]
        if self.W.size <= deg + 2:
            raise ValueError("too few samples in the fitting window")
        self.scale = max(1.0, float(xs.size - idx[0]))
        self.deg, self.tau = deg, tau
        P = self._row(self.W, deg)
        self.U1 = -P @ np.linalg.pinv(P.T @ P)
        self.drift_mean = drift_mean and deg == 1
        P2 = self._row(self.W, 2)
        self.b = 2 * np.linalg.pinv(P2)[2] / (self.scale * tau) ** 2  # drift estimate D = b . x_W
        self.U = np.column_stack([self.U1, self.b]) if self.drift_mean else self.U1

    def _row(self, k, deg: int) -> np.ndarray:
        u = (np.atleast_1d(np.asarray(k, dtype=float)) - self.T) / self.scale
        return np.vander(u, deg + 1, increasing=True)

    def _gamma1(self, t: int) -> np.ndarray:
        return (self._row(self.T + t, self.deg) - self._row(self.T, self.deg))[0]

    def _q(self, t: int) -> float:
        """Mean TIE per unit drift: the frequency functional applied to 1/2 ((k - T) tau)^2."""
        qw = 0.5 * ((self.W - self.T) * self.tau) ** 2
        return 0.5 * (t * self.tau) ** 2 + float(self._gamma1(t) @ (self.U1.T @ qw))

    def gamma(self, t: int) -> np.ndarray:
        g = self._gamma1(t)
        return np.concatenate((g, [-self._q(t)])) if self.drift_mean else g

    def drift(self, xs: np.ndarray) -> float:
        return float(self.b @ xs[self.W])

    def mean(self, xs: np.ndarray, t: int) -> float:
        return self.drift(xs) * self._q(t) if self.drift_mean else 0.0

    def tie(self, xs: np.ndarray, t: int, x_future: float) -> float:
        """Realised holdover error: phase at T+t minus the servo's prediction."""
        return float(x_future - xs[self.T] + self._gamma1(t) @ (self.U1.T @ xs[self.W]))

    def frequency(self, xs: np.ndarray) -> float:
        coef = np.linalg.lstsq(self._row(self.W, self.deg), xs[self.W], rcond=None)[0]
        return float(coef[1] / (self.scale * self.tau))


def _tie_variance(pred: _Predictor, steps: np.ndarray, h: Dict[int, float], tau: float, tau0: float) -> np.ndarray:
    T, W = pred.T, pred.W
    L = T + int(steps.max()) + 1
    out = np.zeros(steps.size)
    size = 1 << int(np.ceil(np.log2(2 * (T + 1))))
    j = np.arange(T + 1)
    gammas = [pred.gamma(int(s)) for s in steps]
    for a, hv in h.items():
        if hv <= 0:
            continue
        q = _q(hv, int(a), tau, tau0)
        hk = _phase_filter(int(a), L)
        if hk.size < L:
            hk = np.concatenate((hk, np.zeros(L - hk.size)))
        # G_i[j] = sum_{k in W} U[k, i] h[k - j]  (driver sample j's weight through the window fit)
        H = np.fft.rfft(hk[: T + 1], size)
        G = np.zeros((pred.U.shape[1], T + 1))
        for i in range(pred.U.shape[1]):
            c = np.zeros(T + 1)
            c[W] = pred.U[:, i]
            G[i] = np.fft.irfft(np.fft.rfft(c[::-1], size) * H, size)[: T + 1][::-1]
        for n, s in enumerate(steps):
            v = hk[T + s - j] - hk[T - j] + gammas[n] @ G
            tail = hk[:s]  # driver samples after T only reach x(T+s)
            out[n] += q * (float(v @ v) + float(tail @ tail))
    return out


def _noise(x: np.ndarray, tau0: float, bootstrap: int = 0) -> NoiseFit:
    """Noise model of the training data, fitted with a drift term so drift is not taken for random-walk FM."""
    return fit_phase(x, tau0, bootstrap=bootstrap, drift=True)


def _mixture_halfwidth(mean: np.ndarray, var_sets: np.ndarray, ci: float) -> np.ndarray:
    """Half-width c with P(|N(0, V)| <= c) = ci averaged over the variance samples (per horizon)."""
    out = np.zeros(var_sets.shape[1])
    nd = NormalDist()
    for n in range(var_sets.shape[1]):
        sd = np.sqrt(np.maximum(var_sets[:, n], 1e-300))
        lo, hi = 0.0, float(sd.max()) * 10
        for _ in range(60):
            mid = (lo + hi) / 2
            p = np.mean([2 * nd.cdf(mid / v) - 1 for v in sd])
            lo, hi = (mid, hi) if p < ci else (lo, mid)
        out[n] = hi
    return out


def _core(x, tau0, horizon, h, model, window, ci, points, noise, drift_mean, uncertainty=0):
    if model not in MODELS:
        raise ValueError(f"model must be one of {', '.join(MODELS)}")
    x = np.asarray(x, dtype=float)
    if np.isfinite(x).sum() < 16:
        raise ValueError("need at least 16 samples before the loss of reference")
    sets: List[Dict[int, float]] = []
    if h is None:
        nf = noise or _noise(x, tau0, uncertainty)
        h = dict(nf.h)
        sets = nf.samples
        if drift_mean is None:
            drift_mean = nf.drift > 0
    h = {int(a): float(v) for a, v in h.items()}
    window = float(window or x.size * tau0)
    # Work on a sub-sampled grid of at most MAX_POINTS window samples (the last sample is kept).
    step = max(1, int(np.ceil(min(x.size, window / tau0) / MAX_POINTS)))
    xs = x[::-1][::step][::-1]
    tau = tau0 * step
    pred = _Predictor(xs, int(round(window / tau)), 1 if model == "frequency" else 2,
                      True if drift_mean is None else bool(drift_mean), tau)
    steps = np.unique(np.round(np.logspace(0, np.log10(max(horizon / tau, 1.0)), points)).astype(int))
    var = _tie_variance(pred, steps, h, tau, tau0)
    mean = np.array([pred.mean(xs, int(s)) for s in steps])
    sd = np.sqrt(var)
    if sets:
        # propagate the uncertainty of the noise model: the envelope of the mixture over plausible h
        vs = np.array([_tie_variance(pred, steps, hs, tau, tau0) for hs in sets])
        z = NormalDist().inv_cdf(0.5 + ci / 2)
        sd = _mixture_halfwidth(mean, vs, ci) / z  # expressed as the sd of an equivalent normal band
    res = HoldoverResult(steps * tau, mean, sd, ci, model, float(min(window, xs.size * tau)), h,
                         pred.frequency(xs), pred.drift(xs))
    res.meta.update(step=step, tau=tau, training_points=int(pred.W.size), drift_in_mean=pred.drift_mean,
                    noise_samples=len(sets))
    longest = x.size * tau0 / 4  # about the longest averaging time the noise fit could see
    if horizon > 2 * longest:
        res.meta["extrapolated_beyond"] = longest
        res.meta["warning"] = (f"horizons beyond {longest:.0f} s extrapolate the noise model past the data; "
                               "long-term noise (flicker/random-walk FM) may be under-represented")
    return res, pred, xs, steps


def predict(x: np.ndarray, tau0: float, horizon: float, h: Optional[Dict[int, float]] = None,
            model: str = "frequency", window: Optional[float] = None, ci: float = 0.95,
            limits: Sequence[float] = (), points: int = 60, noise: Optional[NoiseFit] = None,
            drift_mean: Optional[bool] = None, uncertainty: int = 40) -> HoldoverResult:
    """Holdover prediction from evenly sampled phase ``x`` (s, NaN = gap); the reference is lost after the last sample.

    ``h`` (power-law coefficients) defaults to a fit of ``x``. With
    ``model="frequency"``, ``drift_mean`` says whether the fitted drift shifts
    the mean TIE (default: when the noise fit finds a drift, or always when
    ``h`` is given). ``uncertainty=N`` mixes N bootstrap noise models into
    the envelope, so the uncertainty of the fitted model is included.
    """
    res, *_ = _core(x, tau0, horizon, h, model, window, ci, points, noise, drift_mean, uncertainty)
    for lim in limits:
        res.limits[f"{lim:g}"] = res.time_to(float(lim))
    return res


def phase_from(series: TimeSeries, source: str = "offset", tau0: Optional[float] = None,
               max_gap: float = 3.0):
    """Uniform phase grid from a series: its offset (negated to local - reference) or its integrated frequency (ppm)."""
    if source == "frequency":
        if "frequency" not in series.extra:
            raise ValueError(f"{series.name} has no frequency column")
        tmp = TimeSeries(series.t, series.extra["frequency"], name=series.name)
        grid, f, tau0 = tmp.to_uniform(tau0=tau0, max_gap=max_gap)
        y = f * 1e-6
        x = np.concatenate(([0.0], np.cumsum(np.where(np.isfinite(y[:-1]), y[:-1], np.nan) * tau0)))
        return grid, x, tau0
    grid, x, tau0 = series.to_uniform(tau0=tau0, max_gap=max_gap)
    return grid, -x, tau0


def backtest(x: np.ndarray, tau0: float, horizon: float, trials: int = 20, train: Optional[float] = None,
             h: Optional[Dict[int, float]] = None, model: str = "frequency", window: Optional[float] = None,
             ci: float = 0.95, points: int = 20, drift_mean: Optional[bool] = None) -> Dict[str, object]:
    """Cut the reference at ``trials`` points of a long log, predict, and compare with what the data did.

    The noise model is fitted once, on the first ``train`` seconds. Returns
    the fraction of (trial, horizon) points where the real TIE stayed inside
    the envelope, which should be close to ``ci``.
    """
    x = np.asarray(x, dtype=float)
    hz = int(round(horizon / tau0))
    tr = int(round((train or max(horizon, x.size * tau0 / 4)) / tau0))
    if tr + hz >= x.size:
        raise ValueError("log too short for this training length and horizon")
    starts = np.unique(np.linspace(tr, x.size - hz - 1, trials).astype(int))
    if h is None:
        nf = _noise(x[:tr], tau0)
        h = nf.h
        if drift_mean is None:
            drift_mean = nf.drift > 0
    inside, total, rows = 0, 0, []
    for s in starts:
        res, pred, xs, steps = _core(x[s - tr: s], tau0, horizon, h, model, window, ci, points, None, drift_mean)
        step = int(res.meta["step"])
        act = np.array([pred.tie(xs, int(k), x[s - 1 + int(k) * step]) for k in steps])
        ok = np.isfinite(act)
        hit = (act >= res.lo) & (act <= res.hi) & ok
        inside += int(hit.sum())
        total += int(ok.sum())
        rows.append({"loss_index": int(s), "inside": float(hit.sum() / max(ok.sum(), 1)),
                     "max_abs_tie": float(np.nanmax(np.abs(act))) if ok.any() else None})
    return {"trials": len(rows), "coverage": inside / total if total else float("nan"), "ci": ci,
            "h": {str(a): v for a, v in h.items()}, "per_trial": rows}


def holdover_series(series: TimeSeries, horizon: float, source: str = "offset", **kw) -> HoldoverResult:
    grid, x, tau0 = phase_from(series, source)
    r = predict(x, tau0, horizon, **kw)
    r.meta.update(name=series.name, source=source, loss_time=float(grid[-1]))
    return r


__all__ = ["ALPHAS", "HoldoverResult", "backtest", "holdover_series", "phase_from", "predict"]
