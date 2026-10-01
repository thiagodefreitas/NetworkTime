# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""PTP servos and chains of boundary clocks, simulated with ground truth (#29).

A telecom or datacenter timing chain is a grandmaster followed by N boundary
clocks (T-BC), each a PTP slave on its upstream port and a master on its
downstream port. This module simulates such a chain sample by sample:

* every node has its own free-running oscillator (:class:`ClockModel`);
* every link has a delay, an **asymmetry** (master→slave minus slave→master,
  the source of constant time error that no servo can see), per-timestamp
  noise, and optionally packet delay variation, either modelled
  (:class:`PathModel`, for links through switches without PTP support) or
  replayed from a real capture (:class:`ntpstats.trace.TracePath`);
* every slave runs the E2E delay mechanism with a moving-median delay filter
  and a **servo** that steers its clock's frequency.

Two servos are provided:

:class:`PIServo`
    The proportional-integral servo of linuxptp (``pi.c``): the first
    sample stores the offset, the second estimates the frequency error and
    steps the clock if the offset exceeds ``first_step_threshold``, then
    ``freq = -(kp·offset + Σ ki·offset)``. The gains follow linuxptp's
    defaults for hardware time stamping: ``kp = min(0.7·Ts^-0.3, 0.7/Ts)``,
    ``ki = min(0.3·Ts^0.4, 0.3/Ts)`` for a sync interval ``Ts``.
:class:`LinRegServo`
    Adaptive-window linear regression, after linuxptp's ``linreg.c``: a line
    through the recent free-running phase (offset minus the corrections
    already applied) predicts the phase at the next sync, and the frequency
    is set to bring it to zero. The window (4 to 64 samples) is the one with
    the smallest prediction variance.

The result is the time error of every node relative to the grandmaster, with
the time-error metrics of :mod:`ntpstats.timeerror` per node and per hop, so
a chain design can be checked against a time-error budget: per-hop limits
(for example the T-BC classes of ITU-T G.8273.2) and an end-to-end limit
(for example 1.1 µs, the G.8271.1 network limit for 1.5 µs applications).
These are models: they show how servo choice, sync rate, asymmetry and noise
accumulate along a chain, not how a particular product behaves.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from .series import TimeSeries
from .simulate import ClockModel, PathModel

#: Per-hop limits commonly used for T-BC/T-TSC noise generation (ITU-T G.8273.2, Table 7-1): max|TE|
#: (unfiltered), |cTE|, MTIE of dTE_L (0.1 Hz low-pass, up to 1000 s) and dTE_H peak-to-peak. Check them
#: against the edition you certify to; pass your own limits for anything else.
CLASS_LIMITS: Dict[str, Dict[str, float]] = {
    "A": {"max_te": 100e-9, "cte": 50e-9, "dte_l_mtie": 40e-9, "dte_h_pp": 70e-9},
    "B": {"max_te": 70e-9, "cte": 20e-9, "dte_l_mtie": 40e-9, "dte_h_pp": 70e-9},
    "C": {"max_te": 30e-9, "cte": 10e-9, "dte_l_mtie": 10e-9},
}
#: End-to-end max|TE| of the G.8271.1 network limit (reference point C) for 1.5 µs applications.
NETWORK_LIMIT = 1.1e-6
SERVOS = ("pi", "linreg")


# ------------------------------------------------------------------ servos
@dataclass
class PIServo:
    """linuxptp-style PI servo; offsets in seconds (local − master), frequency in s/s."""

    kp: Optional[float] = None
    ki: Optional[float] = None
    first_step_threshold: float = 20e-6
    step_threshold: float = 0.0
    max_frequency: float = 500e-6
    name: str = "pi"

    def gains(self, interval: float) -> Tuple[float, float]:
        kp = self.kp if self.kp is not None else min(0.7 * interval ** -0.3, 0.7 / interval)
        ki = self.ki if self.ki is not None else min(0.3 * interval ** 0.4, 0.3 / interval)
        return kp, ki

    def lock_time(self, interval: float) -> float:
        """Rough time for a chain of these loops to settle: 25 time constants of the slowest pole of
        the continuous-time loop s² + kp·s + ki/Ts."""
        kp, ki = self.gains(interval)
        rate = ki / interval
        disc = kp * kp - 4 * rate
        slow = (kp - np.sqrt(disc)) / 2 if disc > 0 else kp / 2
        return float(25.0 / slow) if slow > 0 else float("inf")

    def reset(self, interval: float) -> None:
        self._kp, self._ki = self.gains(interval)
        self._count, self._drift = 0, 0.0
        self._first = True
        self._o0 = self._t0 = 0.0

    def sample(self, offset: float, t: float) -> Tuple[float, bool]:
        """Return (frequency to set, step the clock by -offset now?)."""
        lim = self.max_frequency
        if self._count == 0:
            self._o0, self._t0, self._count = offset, t, 1
            return -self._drift, False
        if self._count == 1:
            if t <= self._t0:
                self._count = 0
                return -self._drift, False
            self._drift = float(np.clip(self._drift + (offset - self._o0) / (t - self._t0), -lim, lim))
            step = (self._first and self.first_step_threshold and abs(offset) > self.first_step_threshold) or \
                   (self.step_threshold and abs(offset) > self.step_threshold)
            self._first, self._count = False, 2
            return -self._drift, bool(step)
        if self.step_threshold and abs(offset) > self.step_threshold:
            self._count = 0
            return -self._drift, False
        ki_term = self._ki * offset
        ppb = self._kp * offset + self._drift + ki_term
        if abs(ppb) > lim:
            ppb = float(np.clip(ppb, -lim, lim))
        else:
            self._drift += ki_term
        return -ppb, False


@dataclass
class LinRegServo:
    """Adaptive-window linear-regression servo (after linuxptp's linreg)."""

    min_window: int = 4
    max_window: int = 64
    first_step_threshold: float = 20e-6
    max_frequency: float = 500e-6
    name: str = "linreg"

    def reset(self, interval: float) -> None:
        self._interval = interval
        self._hist: Deque[Tuple[float, float]] = deque(maxlen=self.max_window)
        self._corr = 0.0  # phase already removed by our frequency settings and steps
        self._freq = 0.0
        self._last_t: Optional[float] = None
        self._first = True

    def sample(self, offset: float, t: float) -> Tuple[float, bool]:
        if self._last_t is not None:
            self._corr += self._freq * (t - self._last_t)
        self._last_t = t
        free = offset - self._corr  # free-running phase: what the clock would read without our corrections
        if self._first and self.first_step_threshold and abs(offset) > self.first_step_threshold:
            self._first = False
            self._corr -= offset  # the step is a correction of -offset
            self._hist.append((t, free))
            return self._freq, True
        self._first = False
        self._hist.append((t, free))
        n = len(self._hist)
        if n < 2:
            return self._freq, False
        # Regressions over the last m = 4, 8, ..., 64 samples at once, from cumulative sums of the
        # samples taken newest first (j = 0 is the newest; times relative to it).
        tt = np.fromiter((h[0] for h in reversed(self._hist)), float, n) - t
        xx = np.fromiter((h[1] for h in reversed(self._hist)), float, n)
        sizes = [m for m in (4, 8, 16, 32, 64) if self.min_window <= m <= min(n, self.max_window)] or [n]
        c1, ct, cx = np.cumsum(np.ones(n)), np.cumsum(tt), np.cumsum(xx)
        ctt, ctx, cxx = np.cumsum(tt * tt), np.cumsum(tt * xx), np.cumsum(xx * xx)
        i = np.array(sizes) - 1
        m, st, sx, stt, stx, sxx_ = c1[i], ct[i], cx[i], ctt[i], ctx[i], cxx[i]
        sxx = stt - st * st / m
        ok = sxx > 0
        if not ok.any():
            return self._freq, False
        slope = np.where(ok, (stx - st * sx / m) / np.where(ok, sxx, 1.0), 0.0)
        icpt = (sx - slope * st) / m
        ssr = np.maximum(cxx[i] * 0 + sxx_ - sx * sx / m - slope * slope * sxx, 0.0)
        s2 = ssr / np.maximum(m - 2, 1)
        tn = self._interval  # next sync, relative to now
        var = np.where(ok & (m > 2), s2 * (1 + 1 / m + (tn - st / m) ** 2 / np.where(ok, sxx, 1.0)), np.inf)
        k = int(np.argmin(var)) if np.isfinite(var).any() else int(np.argmax(m))
        best = (float(var[k]), float(slope[k]), float(icpt[k]))
        _, slope, icpt = best
        pred_free = icpt + slope * tn
        # set the frequency so that free phase + corrections reaches zero at the next sync
        self._freq = float(np.clip(-(pred_free + self._corr) / self._interval, -self.max_frequency,
                                   self.max_frequency))
        return self._freq, False


def make_servo(name: str, **options):
    """A servo by name; ``options`` are its fields (e.g. ``kp``, ``ki`` of :class:`PIServo`)."""
    if name == "pi":
        return PIServo(**options)
    if name == "linreg":
        return LinRegServo(**options)
    raise ValueError(f"unknown servo {name!r}; choose from {', '.join(SERVOS)}")


# ------------------------------------------------------------------ chain
@dataclass
class Link:
    """One PTP link (master port to slave port).

    ``asymmetry``: master→slave minus slave→master delay (s); it adds
    ``asymmetry/2`` of constant time error per hop. ``timestamp_noise``: rms
    of each of the four timestamps (hardware time stamping: a few ns).
    ``pdv``: a :class:`PathModel` for the queueing of each direction, for links
    through switches without PTP support. ``trace``: a
    :class:`ntpstats.trace.TracePath` replaying a real capture instead.
    """

    delay: float = 1e-6
    asymmetry: float = 0.0
    timestamp_noise: float = 4e-9
    pdv: Optional[PathModel] = None
    trace: Optional[Any] = None


@dataclass
class ChainScenario:
    """A grandmaster and ``hops`` boundary clocks in series."""

    hops: int = 10
    duration: float = 3600.0
    sync_rate: float = 16.0  # Sync messages per second (G.8275.1: 16)
    delay_rate: Optional[float] = None  # Delay_Req per second (default: the Sync rate)
    servo: str = "pi"
    #: servo settings, e.g. ``{"kp": 0.3, "ki": 3.5e-4}`` for a narrower PI loop (default: linuxptp's gains)
    servo_options: Dict[str, Any] = field(default_factory=dict)
    link: Link = field(default_factory=Link)
    #: oscillator of each boundary clock; its frequency offset is drawn per node within ±freq_spread
    oscillator: ClockModel = field(default_factory=lambda: ClockModel(
        freq_offset=0.0, drift=0.0, white_fm_adev1=1e-11, rw_fm_adev1=1e-13, initial_offset=1e-3))
    freq_spread: float = 2e-6
    asymmetry_spread: float = 0.0  # per-hop asymmetry drawn uniformly in ±spread (added to link.asymmetry)
    gm_noise: float = 0.0  # white phase noise of the grandmaster (rms, s), e.g. its GNSS receiver
    delay_filter: int = 10  # moving-median length of the mean-path-delay filter (linuxptp default)
    #: seconds excluded from the metrics while the servos lock; None: from the servo's lock time (at least 300 s,
    #: at most half the run)
    warmup: Optional[float] = None
    seed: Optional[int] = None
    name: str = "chain"


@dataclass
class ChainResult:
    scenario: ChainScenario
    t: np.ndarray  # seconds from the start
    te: List[np.ndarray]  # te[i]: time error of node i (0 = grandmaster) relative to true time, local - true
    asymmetries: List[float]
    nodes: List[Dict[str, Any]] = field(default_factory=list)  # metrics of the cumulative TE per node
    hops: List[Dict[str, Any]] = field(default_factory=list)  # metrics of the TE added by each hop

    @property
    def warmup(self) -> float:
        return effective_warmup(self.scenario)

    def series(self, node: int) -> TimeSeries:
        """Time error of a node as a series (offset = reference − local, the ntpstats convention)."""
        return TimeSeries(self.t + 1.7e9, -self.te[node], name=f"{self.scenario.name} node {node}",
                          source_format="simulated", meta={"node": node, "te_convention": "offset = -TE"})

    def check(self, limits: Optional[Dict[str, float]] = None, cls: Optional[str] = "B",
              budget: Optional[float] = NETWORK_LIMIT) -> Dict[str, Any]:
        """Per-hop limits (``limits`` or a G.8273.2 ``cls``) and the end-to-end ``budget`` on max|TE|."""
        lim = dict(limits) if limits is not None else dict(CLASS_LIMITS[cls]) if cls else {}
        rows = []
        for h in self.hops:
            for k, v in lim.items():
                val = h.get(k)
                if val is None or not np.isfinite(val):
                    continue
                rows.append({"hop": h["hop"], "metric": k, "value": abs(val), "limit": v, "passed": abs(val) <= v})
        end = self.nodes[-1]
        out: Dict[str, Any] = {"class": cls if limits is None else None, "limits": lim, "checks": rows,
                               "hops_passed": all(r["passed"] for r in rows)}
        if budget:
            out["budget"] = {"limit": budget, "value": end["max_te"], "passed": end["max_te"] <= budget,
                             "margin": budget - end["max_te"]}
        out["passed"] = out["hops_passed"] and (out.get("budget", {}).get("passed", True))
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.scenario.name, "hops": self.scenario.hops, "servo": self.scenario.servo,
                "warmup": self.warmup, "lock_time": lock_time(self.scenario),
                "sync_rate": self.scenario.sync_rate,
                "delay_rate": self.scenario.delay_rate or self.scenario.sync_rate, "duration": self.scenario.duration,
                "asymmetries": self.asymmetries, "nodes": self.nodes, "per_hop": self.hops}


def lock_time(sc: ChainScenario) -> float:
    """Estimated settling time of the chain's servos (s)."""
    servo = make_servo(sc.servo, **sc.servo_options)
    return servo.lock_time(1.0 / sc.sync_rate) if hasattr(servo, "lock_time") else 300.0


def effective_warmup(sc: ChainScenario) -> float:
    if sc.warmup is not None:
        return float(sc.warmup)
    return float(min(max(300.0, lock_time(sc)), sc.duration / 2))


def _link_delays(link: Link, n: int, rel: np.ndarray, rng) -> Tuple[np.ndarray, np.ndarray]:
    """Master→slave and slave→master delays of one link at each sync."""
    if link.trace is not None:
        to_m, from_m = link.trace.delays(rel, rng)  # to reference (slave→master), from reference (master→slave)
        ok = np.isfinite(to_m) & np.isfinite(from_m)
        fill_s, fill_m = np.nanmedian(to_m), np.nanmedian(from_m)
        return np.where(ok, from_m, fill_m), np.where(ok, to_m, fill_s)
    if link.pdv is not None:
        ms = replace(link.pdv, base=link.delay).sample(n, rng)
        sm = replace(link.pdv, base=link.delay).sample(n, rng)
    else:
        ms, sm = np.full(n, link.delay), np.full(n, link.delay)
    return ms, sm


def _run_slave(master: np.ndarray, t: np.ndarray, osc: np.ndarray, ms: np.ndarray, sm: np.ndarray, asym: float,
               sc: ChainScenario, rng) -> np.ndarray:
    n = t.size
    ts = 1.0 / sc.sync_rate
    servo = make_servo(sc.servo, **sc.servo_options)
    servo.reset(ts)
    noise = sc.link.timestamp_noise
    nz = rng.normal(0.0, noise, (n, 4)) if noise else np.zeros((n, 4))
    dr = sc.delay_rate if sc.delay_rate is not None else sc.sync_rate
    every = max(1, int(round(sc.sync_rate / dr))) if dr > 0 else n + 1
    mpd: Deque[float] = deque(maxlen=max(1, sc.delay_filter))
    ms_eff = ms + asym / 2  # asymmetry: master→slave longer by asym than slave→master
    sm_eff = sm - asym / 2
    x = np.empty(n)
    x[0] = osc[0]
    freq = 0.0
    for k in range(n):
        if k:
            x[k] = x[k - 1] + (osc[k] - osc[k - 1]) + freq * ts
        d21 = ms_eff[k] + x[k] - master[k] + nz[k, 1] - nz[k, 0]  # t2 - t1
        if k % every == 0:
            d43 = sm_eff[k] - x[k] + master[k] + nz[k, 3] - nz[k, 2]  # t4 - t3
            mpd.append((d21 + d43) / 2)
        q = sorted(mpd)
        h = len(q) // 2
        offset = d21 - (q[h] if len(q) % 2 else 0.5 * (q[h - 1] + q[h]))
        freq, step = servo.sample(offset, float(t[k]))
        if step:
            x[k] -= offset
    return x


def simulate_chain(sc: Optional[ChainScenario] = None, metrics: bool = True) -> ChainResult:
    """Run a chain; ``te[i]`` is the time error of node ``i`` (0 = grandmaster)."""
    sc = ChainScenario() if sc is None else sc
    if sc.hops < 1:
        raise ValueError("a chain needs at least one boundary clock")
    if sc.servo not in SERVOS:
        raise ValueError(f"unknown servo {sc.servo!r}; choose from {', '.join(SERVOS)}")
    rng = np.random.default_rng(sc.seed)
    ts = 1.0 / sc.sync_rate
    t = np.arange(0.0, sc.duration, ts)
    n = t.size
    gm = rng.normal(0.0, sc.gm_noise, n) if sc.gm_noise else np.zeros(n)
    te = [gm]
    asyms = []
    for _ in range(sc.hops):
        osc_model = replace(sc.oscillator, freq_offset=sc.oscillator.freq_offset
                            + (rng.uniform(-sc.freq_spread, sc.freq_spread) if sc.freq_spread else 0.0))
        osc = osc_model.phase(t, rng)
        a = sc.link.asymmetry + (rng.uniform(-sc.asymmetry_spread, sc.asymmetry_spread) if sc.asymmetry_spread else 0)
        ms, sm = _link_delays(sc.link, n, t, rng)
        te.append(_run_slave(te[-1], t, osc, ms, sm, a, sc, rng))
        asyms.append(float(a))
    res = ChainResult(sc, t, te, asyms)
    if metrics:
        _metrics(res)
    return res


def _te_metrics(t: np.ndarray, x: np.ndarray, warmup: float, tau0: float) -> Dict[str, float]:
    from .timeerror import time_error

    keep = t >= warmup
    s = TimeSeries(t[keep] + 1.7e9, x[keep])
    r = time_error(s, tau0=tau0, input_is_te=True, cte_window=min(1000.0, max(1.0, (t[keep][-1] - t[keep][0]) / 2)))
    m = dict(r.metrics())
    if r.mtie is not None:
        ok = r.mtie.taus <= 1000.0
        m["dte_l_mtie"] = float(np.nanmax(r.mtie.dev[ok])) if ok.any() else float("nan")
    m["rms"] = float(np.sqrt(np.mean(x[keep] ** 2)))
    return {k: float(v) for k, v in m.items()}


def _metrics(res: ChainResult) -> None:
    sc = res.scenario
    tau0 = 1.0 / sc.sync_rate
    warm = effective_warmup(sc)
    if res.t[-1] <= warm + 10 * tau0:
        raise ValueError("duration must exceed the warm-up")
    res.nodes = [dict(node=i, **_te_metrics(res.t, res.te[i], warm, tau0)) for i in range(1, len(res.te))]
    res.hops = [dict(hop=i, asymmetry=res.asymmetries[i - 1],
                     **_te_metrics(res.t, res.te[i] - res.te[i - 1], warm, tau0))
                for i in range(1, len(res.te))]


def chain_from_dict(d: dict, base_dir: str = ".") -> ChainScenario:
    """A :class:`ChainScenario` from a dict (TOML ``[chain]``, ``[link]``, ``[oscillator]`` tables)."""
    d = dict(d.get("chain", d))
    link = dict(d.pop("link", {}))
    if "pdv" in link:
        link["pdv"] = PathModel(**link["pdv"])
    if "trace" in link:
        from .trace import trace_path_from_dict

        link["trace"] = trace_path_from_dict(link["trace"], base_dir)
    kw: Dict[str, Any] = {"link": Link(**link)}
    if "oscillator" in d:
        kw["oscillator"] = ClockModel(**d.pop("oscillator"))
    return ChainScenario(**d, **kw)
