# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Anomaly and change-point detection (issue #23), scored against known ground truth."""

import numpy as np
import pytest

from ntpstats import events as E
from ntpstats.series import TimeSeries


def noisy(n=4000, tau0=16.0, sigma=1e-6, seed=0, delay=None):
    rng = np.random.default_rng(seed)
    t = 1.8e9 + np.arange(n) * tau0
    x = rng.normal(0, sigma, n)
    extra = {}
    if delay is not None:
        extra["delay"] = delay + rng.exponential(2e-4, n)
    return t, x, extra


def test_phase_step_and_spike_are_told_apart():
    t, x, _ = noisy()
    x[1000:] += 50e-6  # step
    x[3000] += 80e-6  # spike
    ev = E.detect(TimeSeries(t, x))
    kinds = {(e.kind, round((e.time - t[0]) / 16)) for e in ev}
    assert ("phase_step", 1000) in kinds and ("spike", 3000) in kinds
    step = next(e for e in ev if e.kind == "phase_step")
    assert step.magnitude == pytest.approx(50e-6, rel=0.1)
    assert sum(e.kind in ("phase_step", "spike") for e in ev) == 2  # no false alarms


def test_frequency_change_location_and_size():
    t, x, _ = noisy(sigma=2e-6)
    rel = t - t[0]
    x = x + np.where(rel > rel[2000], (rel - rel[2000]) * 1e-6, 0.0)  # +1 ppm from sample 2000
    ev = [e for e in E.detect(TimeSeries(t, x)) if e.kind == "frequency_change"]
    assert len(ev) == 1
    assert abs(ev[0].time - t[2000]) < 40 * 16
    assert ev[0].magnitude == pytest.approx(1e-6, rel=0.1)


def test_no_events_on_stationary_noise():
    for seed in range(5):
        t, x, extra = noisy(seed=seed, delay=0.020)
        assert E.detect(TimeSeries(t, x, extra=extra)) == []


def test_route_change_and_asymmetry_hint():
    t, x, extra = noisy(delay=0.020)
    extra["delay"][2000:] += 0.006  # 6 ms longer round trip ...
    x[2000:] -= 0.003  # ... all of it in one direction: offset moves by half of it
    ev = E.detect(TimeSeries(t, x, extra=extra))
    fl = [e for e in ev if e.kind == "delay_floor_change"]
    assert len(fl) == 1 and fl[0].magnitude == pytest.approx(0.006, rel=0.05)
    assert fl[0].detail["asymmetry_ratio"] == pytest.approx(-1.0, abs=0.1)
    step = [e for e in ev if e.kind == "phase_step"]
    assert step and step[0].detail["path_changed"] is True


def test_offset_change_without_path_change_is_flagged():
    t, x, extra = noisy(delay=0.020)
    x[2000:] += 200e-6
    step = [e for e in E.detect(TimeSeries(t, x, extra=extra)) if e.kind == "phase_step"][0]
    assert step.detail["path_changed"] is False and "spoofing" in step.detail["hint"]


def test_leap_smear_signature():
    tau0 = 64.0
    n = int(3 * 86400 / tau0)
    t = 1.8e9 + np.arange(n) * tau0
    rel = t - t[0]
    y = np.where((rel >= 86400) & (rel < 2 * 86400), E.LEAP_SMEAR_PPM * 1e-6, 0.0)
    x = np.cumsum(y) * tau0 + np.random.default_rng(3).normal(0, 1e-6, n)
    ev = E.detect(TimeSeries(t, x))
    sm = [e for e in ev if e.kind == "leap_smear"]
    assert len(sm) == 1 and sm[0].detail["hours"] == pytest.approx(24, abs=0.5)


def test_simulated_route_change_detected():
    import copy

    from ntpstats.simulate import PRESETS, PathEvent, simulate_ntp

    sc = copy.deepcopy(PRESETS["lan"])
    sc.duration = 6 * 3600
    sc.seed = 5
    sc.forward.events.append(PathEvent(start=3 * 3600, base_delta=2e-3))
    s, _ = simulate_ntp(sc)
    fl = [e for e in E.detect(s) if e.kind == "delay_floor_change"]
    assert len(fl) == 1 and abs(fl[0].time - s.t[0] - 3 * 3600) < 20 * 16 * 16
    assert fl[0].magnitude == pytest.approx(2e-3, rel=0.1)


def test_as_dict_and_summary():
    t, x, _ = noisy()
    x[1000:] += 50e-6
    ev = E.detect(TimeSeries(t, x))
    assert E.summary(ev) == {"phase_step": 1}
    d = ev[0].as_dict()
    assert d["kind"] == "phase_step" and d["unit"] == "s" and d["end"] is None
