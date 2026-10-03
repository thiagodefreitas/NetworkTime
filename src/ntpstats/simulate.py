# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Synthetic clocks and NTP or PTP exchanges with known ground truth.

Use these to validate estimators and synchronisation algorithms: every
simulated measurement comes with the true offset, so filters can be scored
objectively (see :func:`ntpstats.analysis.compare`).

With ``protocol="ptp"`` a scenario produces exchange-level PTP (E2E delay
mechanism) instead of NTP exchanges: a Sync every ``poll`` seconds and a
Delay_Req every ``delay_interval`` seconds, each with its own one-way delay
and timestamp noise. The series has the one-way ``ms`` (t2 - t1) of every
Sync and the ``sm`` (t4 - t3) of every Delay_Req, plus the offset a slave
computes with the latest mean path delay, so both NTP-style estimators and
PTP clients (``ptp4l``, ``sptp`` in :mod:`ntpstats.estimators`) can be scored
on the same exchanges. ``transparent`` is the fraction of queueing delay that
transparent clocks on the path correct (1 = full on-path support).

Power-law noise is generated with the Kasdin & Walter (1992) fractional
integration method, the approach commonly used by frequency-stability software.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    magnitudes expressed as the ADEV they produce at ``tau = 1 s`` (flicker FM:
    its constant ADEV floor; flicker PM: phase rms). An optional sinusoidal
    temperature cycle drives frequency through ``tempco`` (fractional frequency
    per kelvin), the dominant wander of real crystal oscillators.
    """

    freq_offset: float = 5e-6  # 5 ppm, typical uncompensated crystal
    drift: float = 1e-11  # aging / thermal, per second
    white_pm: float = 0.0  # timestamping noise, seconds rms
    white_fm_adev1: float = 1e-9
    rw_fm_adev1: float = 1e-11
    flicker_fm_adev: float = 0.0  # flicker FM floor (ADEV, dimensionless)
    flicker_pm: float = 0.0  # flicker PM, seconds rms
    initial_offset: float = 0.0
    tempco: float = 0.0  # fractional frequency per K (1e-7 = 0.1 ppm/K)
    temp_amplitude: float = 0.0  # K, peak of the temperature cycle
    temp_period: float = 86400.0  # s
    #: power-law coefficients h_α (S_y(f) = Σ h_α f^α), e.g. from ``ntpstats noise``; when given they
    #: replace the white/random-walk/flicker fields above
    h_alpha: Optional[Dict[int, float]] = None

    def phase(self, t: np.ndarray, rng=None) -> np.ndarray:
        """Local clock error (local - true) at uniform times ``t``."""
        rng = np.random.default_rng(rng)
        n = t.size
        tau0 = float(np.median(np.diff(t))) if n > 1 else 1.0
        rel = t - t[0]
        x = self.initial_offset + self.freq_offset * rel + 0.5 * self.drift * rel ** 2
        if self.h_alpha:
            from .noisefit import simulate as _powerlaw

            x = x + _powerlaw({int(a): float(v) for a, v in self.h_alpha.items()}, n, tau0, rng)
            if self.tempco and self.temp_amplitude:
                w = 2 * np.pi / self.temp_period
                x = x + self.tempco * self.temp_amplitude * (1 - np.cos(w * rel)) / w
            return x
        if self.white_fm_adev1:
            # white FM: ADEV(tau) = sqrt(h0 / (2 tau)); random-walk phase step
            x = x + powerlaw_phase(n, 0, self.white_fm_adev1 * np.sqrt(tau0), rng)
        if self.rw_fm_adev1:
            # RW FM: ADEV(tau) = c * sqrt(tau); cumulative frequency walk
            x = x + powerlaw_phase(n, -2, self.rw_fm_adev1 * np.sqrt(3.0) * tau0 ** 1.5, rng)
        if self.white_pm:
            x = x + rng.normal(0.0, self.white_pm, n)
        if self.flicker_fm_adev:
            x = x + self.flicker_fm_adev * _unit_flicker_fm(n, tau0, rng)
        if self.flicker_pm:
            f = powerlaw_phase(n, 1, 1.0, rng)
            x = x + self.flicker_pm * (f - f.mean()) / (f.std() or 1.0)
        if self.tempco and self.temp_amplitude:
            w = 2 * np.pi / self.temp_period
            # y(t) = tempco * A * sin(w t)  ->  x(t) = tempco * A * (1 - cos(w t)) / w
            x = x + self.tempco * self.temp_amplitude * (1 - np.cos(w * rel)) / w
        return x


def _unit_flicker_fm(n, tau0, rng):
    """Flicker-FM phase scaled so that its ADEV floor is 1 (calibrated on the realisation)."""
    f = powerlaw_phase(n, -1, 1.0, rng)
    m = max(1, n // 16)
    d = f[2 * m:] - 2 * f[m:-m] + f[:-2 * m]
    adev = np.sqrt(np.mean(d * d) / 2) / (m * tau0) if d.size else 1.0
    return f / (adev or 1.0)


@dataclass
class PathEvent:
    """A change of path behaviour between ``start`` and ``end`` (seconds
    from the beginning of the run): route change (``base_delta``, a step of
    the one-way propagation delay), congestion (``queue_scale``/``load``),
    or outage (``loss=1``)."""

    start: float
    end: float = float("inf")
    base_delta: float = 0.0
    queue_scale: float = 1.0
    load: Optional[float] = None
    loss: Optional[float] = None


@dataclass
class PathModel:
    """One-way network path: fixed propagation plus random queueing.

    Queueing delay is exponential with mean ``queue_mean`` applied with
    probability ``load`` (else zero), which yields the characteristic
    "floor plus tail" delay distribution of real networks. ``events``
    modify it over time.
    """

    base: float = 5e-3
    queue_mean: float = 1e-3
    load: float = 0.5
    events: List[PathEvent] = field(default_factory=list)

    def sample(self, n: int, rng, rel: Optional[np.ndarray] = None) -> np.ndarray:
        q = rng.exponential(self.queue_mean, n) * (rng.random(n) < self.load)
        d = self.base + q
        if self.events and rel is not None:
            for ev in self.events:
                on = (rel >= ev.start) & (rel < ev.end)
                if not on.any():
                    continue
                d = np.where(on, d + ev.base_delta, d)
                if ev.queue_scale != 1.0 or ev.load is not None:
                    load = self.load if ev.load is None else ev.load
                    q2 = rng.exponential(self.queue_mean * ev.queue_scale, n) * (rng.random(n) < load)
                    d = np.where(on, self.base + ev.base_delta + q2, d)
        return d

    def floor(self, n: int, rel: Optional[np.ndarray] = None) -> np.ndarray:
        """The queue-free delay (propagation, with route changes) at each sample."""
        d = np.full(n, float(self.base))
        if self.events and rel is not None:
            for ev in self.events:
                if ev.base_delta:
                    d = np.where((rel >= ev.start) & (rel < ev.end), d + ev.base_delta, d)
        return d

    def loss_mask(self, rel: np.ndarray, rng) -> np.ndarray:
        """True where a packet on this path is lost because of an event."""
        lost = np.zeros(rel.size, dtype=bool)
        for ev in self.events:
            if ev.loss:
                on = (rel >= ev.start) & (rel < ev.end)
                lost |= on & (rng.random(rel.size) < ev.loss)
        return lost


@dataclass
class ServerSpec:
    """A time server as seen through its own network path.

    ``bias`` makes it a falseticker (constant error of its clock); ``step_at``
    / ``step`` add a time step of its clock at a given run time.
    """

    name: str = "server"
    forward: PathModel = field(default_factory=PathModel)
    backward: PathModel = field(default_factory=lambda: PathModel(base=5e-3, queue_mean=3e-3, load=0.6))
    noise: float = 1e-6
    bias: float = 0.0
    step_at: Optional[float] = None
    step: float = 0.0
    stagger: float = 0.0  # seconds after the common poll instant
    #: a :class:`ntpstats.trace.TracePath`: real delays replace ``forward``/``backward``
    trace: Optional[Any] = None


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
    servers: List[ServerSpec] = field(default_factory=list)  # multi-server scenarios
    name: str = "scenario"
    #: a :class:`ntpstats.trace.TracePath`: replay real delays instead of ``forward``/``backward``
    trace: Optional[Any] = None
    #: ``"ntp"`` (client/server exchanges) or ``"ptp"`` (Sync every ``poll`` s, Delay_Req every ``delay_interval`` s)
    protocol: str = "ntp"
    #: PTP only: seconds between Delay_Req messages (default: ``poll``)
    delay_interval: Optional[float] = None
    #: fraction of queueing delay corrected by transparent clocks (PTP correction field), 0 to 1
    transparent: float = 0.0


PROTOCOLS = ("ntp", "ptp")


def _measure(t, rel, theta, spec: ServerSpec, loss: float, rng, label: str, protocol: str = "ntp",
             delay_every: int = 1, transparent: float = 0.0):
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol {protocol!r}; choose from {', '.join(PROTOCOLS)}")
    lost_trace = None
    if spec.trace is not None:
        df, db = spec.trace.delays(rel, rng)
        lost_trace = ~(np.isfinite(df) & np.isfinite(db))
        df, db = np.nan_to_num(df), np.nan_to_num(db)
        floor_f = np.full(t.size, np.min(df[~lost_trace]) if (~lost_trace).any() else 0.0)
        floor_b = np.full(t.size, np.min(db[~lost_trace]) if (~lost_trace).any() else 0.0)
    else:
        df = spec.forward.sample(t.size, rng, rel)
        db = spec.backward.sample(t.size, rng, rel)
        floor_f, floor_b = spec.forward.floor(t.size, rel), spec.backward.floor(t.size, rel)
    if transparent:
        df = df - transparent * np.maximum(df - floor_f, 0.0)
        db = db - transparent * np.maximum(db - floor_b, 0.0)
    server_err = np.full(t.size, spec.bias)
    if spec.step_at is not None:
        server_err = server_err + np.where(rel >= spec.step_at, spec.step, 0.0)
    keep = rng.random(t.size) >= loss
    if lost_trace is not None:
        keep &= ~lost_trace
    elif spec.forward.events or spec.backward.events:
        keep &= ~(spec.forward.loss_mask(rel, rng) | spec.backward.loss_mask(rel, rng))
    meta = {"peer": spec.name, "falseticker": bool(spec.bias or spec.step), "protocol": protocol}
    if protocol == "ptp":
        return _measure_ptp(t, theta + server_err, theta, df, db, keep, spec.noise, max(1, int(delay_every)),
                            rng, label, meta)
    noise = rng.normal(0.0, spec.noise, t.size)
    measured = theta + server_err + (df - db) / 2 + noise
    delay = df + db
    return TimeSeries(
        t[keep], measured[keep], name=label, source_format="simulated",
        extra={"delay": delay[keep], "true_offset": theta[keep]},
        meta=meta,
    )


def _measure_ptp(t, theta_seen, theta, df, db, keep, noise, every, rng, label, meta):
    """E2E PTP: Sync one-way ``ms = t2 - t1`` at every sample, Delay_Req ``sm = t4 - t3`` every ``every``-th.

    Offsets follow the ntpd convention (reference - local): ``ms = d_ms - theta``, ``sm = d_sm + theta``;
    the slave's offset is ``mean_path_delay - ms`` with the mean path delay of the latest Delay_Req.
    """
    n = t.size
    ms = df - theta_seen + rng.normal(0.0, noise, n)
    sm = db + theta_seen + rng.normal(0.0, noise, n)
    req = keep & (np.arange(n) % every == 0)
    sm = np.where(req, sm, np.nan)
    mpd = np.where(req, (ms + sm) / 2, np.nan)
    last = np.maximum.accumulate(np.where(req, np.arange(n), -1))  # index of the latest Delay_Req
    ok = keep & (last >= 0)
    mpd_now = mpd[np.maximum(last, 0)]
    offset = mpd_now - ms
    meta = dict(meta, delay_every=every)
    return TimeSeries(
        t[ok], offset[ok], name=label, source_format="simulated",
        extra={"delay": 2 * mpd_now[ok], "ms": ms[ok], "sm": sm[ok], "true_offset": theta[ok]},
        meta=meta,
    )


def simulate_ntp(sc: Optional[Scenario] = None, name: str = "simulated"):
    """Simulate SNTP exchanges against a perfect server.

    Returns ``(measured, truth)`` time series. ``measured`` uses the ntpd
    sign convention (server - local) and has ``delay`` and
    ``true_offset`` columns; ``truth`` is the true offset at the same times.
    For multi-server scenarios this returns the first server; see
    :func:`simulate_multi`.
    """
    sc = Scenario() if sc is None else sc
    if sc.servers:
        ms, truth = simulate_multi(sc, name)
        first = ms[0]
        return first, TimeSeries(first.t, first.extra["true_offset"], name=f"{name} (truth)", source_format="simulated")
    rng = np.random.default_rng(sc.seed)
    t = np.arange(0.0, sc.duration, sc.poll) + 1.7e9  # arbitrary epoch in 2023
    rel = t - t[0]
    x_local = sc.clock.phase(t, rng)  # local - true
    theta = -x_local  # true offset, server - local
    spec = ServerSpec(name=name, forward=sc.forward, backward=sc.backward, noise=sc.server_noise, trace=sc.trace)
    meas = _measure(t, rel, theta, spec, sc.loss, rng, name, **_protocol_options(sc))
    meas.meta["scenario"] = repr(sc)
    truth = TimeSeries(meas.t, meas.extra["true_offset"], name=f"{name} (truth)", source_format="simulated")
    return meas, truth


def _protocol_options(sc: Scenario) -> Dict[str, Any]:
    every = 1
    if sc.protocol == "ptp" and sc.delay_interval:
        every = max(1, int(round(sc.delay_interval / sc.poll)))
    return {"protocol": sc.protocol, "delay_every": every, "transparent": float(sc.transparent)}


def simulate_multi(sc: Scenario, name: str = "simulated"):
    """One local clock measured against every server in ``sc.servers``.

    Returns ``(list_of_measured, truth)``; ``truth`` is the true offset on a
    fine common grid (poll / 4) so any estimator output can be scored.
    """
    servers = sc.servers or [ServerSpec(name=name, forward=sc.forward, backward=sc.backward, noise=sc.server_noise,
                                        trace=sc.trace)]
    rng = np.random.default_rng(sc.seed)
    step = sc.poll / 4
    grid = np.arange(0.0, sc.duration + sc.poll, step) + 1.7e9
    theta_grid = -sc.clock.phase(grid, rng)
    out = []
    for i, spec in enumerate(servers):
        t = np.arange(0.0, sc.duration, sc.poll) + 1.7e9 + (spec.stagger or i * min(1.0, sc.poll / (2 * len(servers))))
        theta = np.interp(t, grid, theta_grid)
        out.append(_measure(t, t - grid[0], theta, spec, sc.loss, rng, f"{name} [{spec.name}]", **_protocol_options(sc)))
    truth = TimeSeries(grid, theta_grid, name=f"{name} (truth)", source_format="simulated")
    return out, truth


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
    # Route change after 8 h (+4 ms one way) and an evening congestion period.
    "route-change": Scenario(
        forward=PathModel(events=[PathEvent(start=8 * 3600, base_delta=4e-3),
                                  PathEvent(start=18 * 3600, end=21 * 3600, queue_scale=6, load=0.9)]),
        clock=ClockModel(tempco=1e-7, temp_amplitude=3.0),
    ),
    # Four servers: one falseticker (+40 ms) and one that steps by +100 ms at 12 h.
    # Both exceed the root distance (~10 ms) so RFC 5905 selection can reject
    # them; errors smaller than the root distance are undetectable by design.
    # PTP over a LAN of switches without PTP support (hardware time stamps, 1 Sync and 1 Delay_Req per second),
    # and the same network with transparent clocks that correct 95 % of the queueing delay.
    "ptp-lan": Scenario(
        duration=4 * 3600, poll=1.0, protocol="ptp",
        clock=ClockModel(freq_offset=8e-6, white_fm_adev1=1e-10, rw_fm_adev1=1e-13, white_pm=0.0),
        forward=PathModel(base=4e-6, queue_mean=3e-6, load=0.4),
        backward=PathModel(base=4e-6, queue_mean=6e-6, load=0.5),
        server_noise=8e-9,
    ),
    "ptp-tc": Scenario(
        duration=4 * 3600, poll=1.0, protocol="ptp", transparent=0.95,
        clock=ClockModel(freq_offset=8e-6, white_fm_adev1=1e-10, rw_fm_adev1=1e-13, white_pm=0.0),
        forward=PathModel(base=4e-6, queue_mean=3e-6, load=0.4),
        backward=PathModel(base=4e-6, queue_mean=6e-6, load=0.5),
        server_noise=8e-9,
    ),
    "falseticker": Scenario(
        clock=ClockModel(flicker_fm_adev=3e-11),
        servers=[
            ServerSpec("a", PathModel(base=4e-3), PathModel(base=4e-3, queue_mean=2e-3)),
            ServerSpec("b", PathModel(base=9e-3, queue_mean=2e-3), PathModel(base=8e-3)),
            ServerSpec("c", PathModel(base=6e-3), PathModel(base=7e-3), bias=40e-3),
            ServerSpec("d", PathModel(base=12e-3), PathModel(base=12e-3, queue_mean=4e-3), step_at=12 * 3600, step=100e-3),
        ],
    ),
}


def scenario_from_dict(d: dict, base_dir: str = ".") -> Scenario:
    """Build a :class:`Scenario` from a plain dict (e.g. a TOML scenario file).

    ```toml
    name = "wan-route-change"
    duration = 86400
    poll = 64
    seed = 1
    [clock]
    freq_offset = 5e-6
    tempco = 1e-7
    temp_amplitude = 3
    [forward]
    base = 5e-3
    events = [{start = 28800, base_delta = 4e-3}]
    [backward]
    base = 5e-3
    queue_mean = 3e-3
    [[servers]]            # optional: multi-server
    name = "a"
    bias = 0.0
    forward = {base = 4e-3}
    [trace]                # optional: real delays from a capture or log (replaces forward/backward)
    file = "capture.pcap"  # relative to the scenario file
    mode = "bootstrap"     # or "replay"
    ```

    PTP exchanges instead of NTP: ``protocol = "ptp"``, ``poll`` is the Sync
    interval, ``delay_interval`` the Delay_Req interval and ``transparent``
    the fraction of queueing delay corrected by transparent clocks.
    """
    d = dict(d)
    if "preset" in d:
        from dataclasses import replace

        base = replace(PRESETS[d.pop("preset")])
    else:
        base = Scenario()

    def path(p, default):
        if p is None:
            return default
        p = dict(p)
        evs = [PathEvent(**e) for e in p.pop("events", [])]
        return PathModel(**p, events=evs)

    kw = {}
    for k in ("duration", "poll", "server_noise", "loss", "seed", "name", "protocol", "delay_interval", "transparent"):
        if k in d:
            kw[k] = d[k]
    if "clock" in d:
        kw["clock"] = ClockModel(**d["clock"])
    kw["forward"] = path(d.get("forward"), base.forward)
    kw["backward"] = path(d.get("backward"), base.backward)
    if "trace" in d:
        from .trace import trace_path_from_dict

        kw["trace"] = trace_path_from_dict(d["trace"], base_dir)
    if "servers" in d:
        specs = []
        for sd in d["servers"]:
            sd = dict(sd)
            fw, bw = sd.pop("forward", None), sd.pop("backward", None)
            if "trace" in sd:
                from .trace import trace_path_from_dict

                sd["trace"] = trace_path_from_dict(sd["trace"], base_dir)
            specs.append(ServerSpec(**sd, forward=path(fw, PathModel()),
                                    backward=path(bw, PathModel(base=5e-3, queue_mean=3e-3, load=0.6))))
        kw["servers"] = specs
    from dataclasses import replace

    return replace(base, **kw)
