# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Clock-state estimation from noisy offset measurements.

Replaces the four ad-hoc Kalman variants of the 2012 prototype (which
assumed a fixed 32 s poll, mixed filtered output back into the raw
timestamps and never modelled the time step) with one standard two-state
(phase, frequency) Kalman filter supporting irregular sampling, plus an
optional Rauch-Tung-Striebel smoother for offline analysis.

State model (continuous-time random-walk FM + white FM clock)::

    x_k   = [phase (s), frequency (s/s)]
    x_k+1 = F(dt) x_k + w,  F = [[1, dt], [0, 1]]
    Q(dt) = q_phase * [[dt, 0], [0, 0]]
          + q_freq  * [[dt^3/3, dt^2/2], [dt^2/2, dt]]
    z_k   = phase + v,  v ~ N(0, r)

``q_phase`` (s^2/s) is the white-FM diffusion and ``q_freq`` (1/s) the
random-walk-FM diffusion; they relate to the Allan variance by
``AVAR(tau) ~= q_phase/tau + q_freq*tau/3``. :func:`fit_noise` estimates
them (and ``r``) from an OADEV curve so the filter can be tuned from data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .series import TimeSeries


@dataclass
class KalmanResult:
    t: np.ndarray
    phase: np.ndarray  # filtered (or smoothed) offset, s
    freq: np.ndarray  # frequency offset, s/s
    phase_sd: np.ndarray
    freq_sd: np.ndarray
    innovation: np.ndarray
    r: float
    q_phase: float
    q_freq: float
    smoothed: bool


def fit_noise(series: TimeSeries):
    """Rough (r, q_phase, q_freq) from the series' OADEV.

    Least-squares fit of ``AVAR(tau) = 3 r / tau^2 + q_phase / tau + q_freq tau / 3``
    (white PM + white FM + RW FM) on the octave-spaced OADEV, with
    non-negative coefficients.
    """
    from .stability import series_stability

    (res,) = series_stability(series, kinds=("oadev",), ci=None)
    ok = np.isfinite(res.dev) & (res.dev > 0)
    tau = res.taus[ok]
    avar = res.dev[ok] ** 2
    if tau.size >= 2:
        A = np.column_stack([3 / tau ** 2, 1 / tau, tau / 3])
        w = 1 / avar  # relative least squares
        coef = _nnls(A * w[:, None], avar * w)
        r, qp, qf = (max(float(c), 0.0) for c in coef)
    else:  # constant or degenerate data: fall back to tiny, positive defaults
        r, qp, qf = 0.0, 0.0, 0.0
    # keep things strictly positive for numerical stability
    scale = float(np.median(np.abs(np.diff(series.offset)))) or 1e-6
    return max(r, (1e-3 * scale) ** 2), max(qp, 1e-30), max(qf, 1e-40)


def _nnls(A, b, iters=200):
    """Tiny projected-gradient NNLS (avoids a SciPy dependency)."""
    x = np.maximum(np.linalg.lstsq(A, b, rcond=None)[0], 0)
    L = np.linalg.norm(A, 2) ** 2
    for _ in range(iters):
        x = np.maximum(x - (A.T @ (A @ x - b)) / L, 0)
    return x


def kalman(
    series: TimeSeries,
    r: Optional[float] = None,
    q_phase: Optional[float] = None,
    q_freq: Optional[float] = None,
    smooth: bool = False,
    gate: Optional[float] = 5.0,
    delay_weighting: bool = True,
) -> KalmanResult:
    """Run the two-state Kalman filter over ``series``.

    Parameters default to :func:`fit_noise` estimates. ``gate`` rejects
    measurements whose normalised innovation exceeds ``gate`` sigmas (popcorn
    spikes from queueing delay); ``None`` disables gating. With
    ``smooth=True`` an RTS backward pass gives the offline optimum.

    If the series has a ``delay`` column and ``delay_weighting`` is true,
    each measurement's variance is inflated by ``((delay - min_delay)/2)^2``,
    the square of the worst-case error its queueing could cause, so
    low-delay samples dominate (a soft version of NTP's clock filter).
    """
    s = series.sorted()
    if len(s) < 3:
        raise ValueError("need at least 3 samples")
    if r is None or q_phase is None or q_freq is None:
        fr, fqp, fqf = fit_noise(s)
        r = fr if r is None else r
        q_phase = fqp if q_phase is None else q_phase
        q_freq = fqf if q_freq is None else q_freq

    n = len(s)
    t, z = s.t, s.offset
    xf = np.zeros((n, 2))
    Pf = np.zeros((n, 2, 2))
    xp_all = np.zeros((n, 2))
    Pp_all = np.zeros((n, 2, 2))
    Fs = np.zeros((n, 2, 2))
    innov = np.full(n, np.nan)

    slope = (z[min(n - 1, 10)] - z[0]) / max(t[min(n - 1, 10)] - t[0], 1e-9)
    x = np.array([z[0], slope])
    P = np.diag([r * 10, (np.std(np.diff(z)) / max(np.median(np.diff(t)), 1e-9)) ** 2 + 1e-18])
    H = np.array([1.0, 0.0])
    rk = np.full(n, float(r))
    if delay_weighting and "delay" in s.extra and np.isfinite(s.extra["delay"]).any():
        q = s.extra["delay"] - np.nanmin(s.extra["delay"])
        rk = rk + np.where(np.isfinite(q), (q / 2) ** 2, 0.0)
    for k in range(n):
        if k > 0:
            dt = t[k] - t[k - 1]
            F = np.array([[1.0, dt], [0.0, 1.0]])
            Q = q_phase * np.array([[dt, 0.0], [0.0, 0.0]]) + q_freq * np.array(
                [[dt ** 3 / 3, dt ** 2 / 2], [dt ** 2 / 2, dt]]
            )
            x = F @ x
            P = F @ P @ F.T + Q
            Fs[k] = F
        xp_all[k], Pp_all[k] = x, P
        S = H @ P @ H + rk[k]
        e = z[k] - H @ x
        innov[k] = e
        if gate is None or k < 3 or abs(e) <= gate * np.sqrt(S):
            K = P @ H / S
            x = x + K * e
            P = P - np.outer(K, H @ P)
            P = 0.5 * (P + P.T)
        xf[k], Pf[k] = x, P

    if smooth:
        xs, Ps = xf.copy(), Pf.copy()
        for k in range(n - 2, -1, -1):
            C = Pf[k] @ Fs[k + 1].T @ np.linalg.pinv(Pp_all[k + 1])
            xs[k] = xf[k] + C @ (xs[k + 1] - xp_all[k + 1])
            Ps[k] = Pf[k] + C @ (Ps[k + 1] - Pp_all[k + 1]) @ C.T
        xf, Pf = xs, Ps

    return KalmanResult(
        t=t,
        phase=xf[:, 0],
        freq=xf[:, 1],
        phase_sd=np.sqrt(np.maximum(Pf[:, 0, 0], 0)),
        freq_sd=np.sqrt(np.maximum(Pf[:, 1, 1], 0)),
        innovation=innov,
        r=float(r),
        q_phase=float(q_phase),
        q_freq=float(q_freq),
        smoothed=smooth,
    )


def kalman_series(series: TimeSeries, **kw) -> TimeSeries:
    """Return a new :class:`TimeSeries` holding the filtered offset."""
    res = kalman(series, **kw)
    return TimeSeries(
        t=res.t,
        offset=res.phase,
        name=f"{series.name} ({'RTS smoothed' if res.smoothed else 'Kalman'})",
        source_format=series.source_format,
        extra={"frequency_ppm": res.freq * 1e6, "phase_sd": res.phase_sd},
        meta={"r": res.r, "q_phase": res.q_phase, "q_freq": res.q_freq, "derived_from": series.name},
    )
