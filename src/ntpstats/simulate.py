# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Synthetic clocks and NTP exchanges with known ground truth.

Use these to validate estimators and synchronisation algorithms: every
simulated measurement comes with the true offset, so filters can be scored
objectively (see :func:`ntpstats.analysis.compare`).

Power-law noise is generated with the Kasdin & Walter (1992) fractional
integration method, the approach commonly used by frequency-stability software.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

from .series import TimeSeries

#: alpha (exponent of S_y(f) ~ f^alpha) -> name
NOISE_TYPES = {2: "white PM", 1: "flicker PM", 0: "white FM", -1: "flicker FM", -2: "random-walk FM"}


def powerlaw_phase(n: int, alpha: int, sigma: float = 1.0, rng=None) -> np.ndarray:
    """Phase samples whose fractional-frequency PSD is ``~ f^alpha``.

    ``sigma`` scales the driving white noise. For ``alpha=2`` the result is
    white phase noise with standard deviation ``sigma``; for ``alpha=0``
    (white FM) it is a random walk with step ``sigma``.
    """
    rng = np.random.default_rng(rng)
    d = (2 - alpha) / 2.0  # fractional integration order for phase
    w = rng.normal(0.0, sigma, n)
    if d == 0:
        return w
    k = np.arange(1, n)
    h = np.concatenate(([1.0], np.cumprod((d + k - 1) / k)))
    size = 1 << int(np.ceil(np.log2(2 * n)))
    return np.fft.irfft(np.fft.rfft(w, size) * np.fft.rfft(h, size), size)[:n]


@dataclass
class ClockModel:
    """Free-running local oscillator.

    ``freq_offset`` (s/s), ``drift`` (s/s per s), and power-law noise
    magnitudes expressed as the ADEV they produce at ``tau = 1 s``.
    """

    freq_offset: float = 5e-6  # 5 ppm, typical uncompensated crystal
    drift: float = 1e-11  # aging / thermal, per second
    white_pm: float = 0.0  # timestamping noise, seconds rms
    white_fm_adev1: float = 1e-9
    rw_fm_adev1: float = 1e-11
    initial_offset: float = 0.0

    def phase(self, t: np.ndarray, rng=None) -> np.ndarray:
        """Local clock error (local - true) at uniform times ``t``."""
        rng = np.random.default_rng(rng)
        n = t.size
        tau0 = float(np.median(np.diff(t))) if n > 1 else 1.0
        rel = t - t[0]
        x = self.initial_offset + self.freq_offset * rel + 0.5 * self.drift * rel ** 2
        if self.white_fm_adev1:
            # white FM: ADEV(tau) = sqrt(h0 / (2 tau)); random-walk phase step
            x = x + powerlaw_phase(n, 0, self.white_fm_adev1 * np.sqrt(tau0), rng)
        if self.rw_fm_adev1:
            # RW FM: ADEV(tau) = c * sqrt(tau); cumulative frequency walk
            x = x + powerlaw_phase(n, -2, self.rw_fm_adev1 * np.sqrt(3.0) * tau0 ** 1.5, rng)
        if self.white_pm:
            x = x + rng.normal(0.0, self.white_pm, n)
        return x


@dataclass
class PathModel:
    """One-way network path: fixed propagation plus random queueing.

    Queueing delay is exponential with mean ``queue_mean`` applied with
    probability ``load`` (else zero), which yields the characteristic
    "floor plus tail" delay distribution of real networks.
    """

    base: float = 5e-3
    queue_mean: float = 1e-3
    load: float = 0.5

    def sample(self, n: int, rng) -> np.ndarray:
        q = rng.exponential(self.queue_mean, n) * (rng.random(n) < self.load)
        return self.base + q


@dataclass
class Scenario:
    duration: float = 86400.0
    poll: float = 64.0
    clock: ClockModel = field(default_factory=ClockModel)
    forward: PathModel = field(default_factory=PathModel)
    backward: PathModel = field(default_factory=lambda: PathModel(base=5e-3, queue_mean=3e-3, load=0.6))
    server_noise: float = 1e-6  # server timestamping noise, s rms
    loss: float = 0.0  # packet loss probability
    seed: Optional[int] = None


def simulate_ntp(sc: Scenario = Scenario(), name: str = "simulated"):
    """Simulate SNTP exchanges against a perfect server.

    Returns ``(measured, truth)`` time series. ``measured`` uses the ntpd
    sign convention (server - local) and has ``delay`` and
    ``true_offset`` columns; ``truth`` is the true offset at the same times.
    """
    rng = np.random.default_rng(sc.seed)
    t = np.arange(0.0, sc.duration, sc.poll) + 1.7e9  # arbitrary epoch in 2023
    x_local = sc.clock.phase(t, rng)  # local - true
    theta = -x_local  # true offset, server - local
    df = sc.forward.sample(t.size, rng)
    db = sc.backward.sample(t.size, rng)
    noise = rng.normal(0.0, sc.server_noise, t.size)
    measured = theta + (df - db) / 2 + noise
    delay = df + db
    keep = rng.random(t.size) >= sc.loss
    meas = TimeSeries(
        t[keep], measured[keep], name=name, source_format="simulated",
        extra={"delay": delay[keep], "true_offset": theta[keep]},
        meta={"scenario": repr(sc)},
    )
    truth = TimeSeries(t[keep], theta[keep], name=f"{name} (truth)", source_format="simulated")
    return meas, truth


def noise_series(n: int = 4096, tau0: float = 1.0, alpha: int = 0, sigma: float = 1e-9, seed=None) -> TimeSeries:
    """A pure power-law phase series (for estimator validation / teaching)."""
    x = powerlaw_phase(n, alpha, sigma, seed)
    t = 1.7e9 + tau0 * np.arange(n)
    return TimeSeries(t, x, name=f"{NOISE_TYPES.get(alpha, alpha)} noise", source_format="simulated")


PRESETS: Dict[str, Scenario] = {
    "lan": Scenario(
        duration=6 * 3600, poll=16,
        clock=ClockModel(freq_offset=-12e-6, white_fm_adev1=2e-9, rw_fm_adev1=3e-12, white_pm=2e-6),
        forward=PathModel(base=80e-6, queue_mean=40e-6, load=0.3),
        backward=PathModel(base=80e-6, queue_mean=60e-6, load=0.3),
        server_noise=1e-6,
    ),
    "internet": Scenario(),
    "congested": Scenario(
        forward=PathModel(base=20e-3, queue_mean=8e-3, load=0.7),
        backward=PathModel(base=20e-3, queue_mean=15e-3, load=0.8),
        loss=0.02,
    ),
}
