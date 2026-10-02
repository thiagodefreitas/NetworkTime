# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Reference algorithms added in 2.17: Huygens-style convex hull, ntpd-rs-style combination."""

import numpy as np
import pytest

from ntpstats import estimators as E
from ntpstats.bench import load_scenarios, run_bench, score, summarize
from ntpstats.series import TimeSeries
from ntpstats.simulate import PRESETS, simulate_multi


def _linear_clock(n=600, poll=16.0, seed=0):
    rng = np.random.default_rng(seed)
    t = 1.7e9 + poll * np.arange(n)
    theta = 2e-3 + 3e-6 * (t - t[0])  # 3 ppm frequency offset
    df = 1e-3 + rng.exponential(2e-3, n) * (rng.random(n) < 0.6)
    db = 1e-3 + rng.exponential(2e-3, n) * (rng.random(n) < 0.6)
    meas = TimeSeries(t, theta + (df - db) / 2, extra={"delay": df + db})
    return meas, TimeSeries(t, theta)


def test_margin_line_finds_the_separating_line():
    t = np.linspace(-100, 0, 40)
    line = 1e-3 + 2e-6 * t
    a, b, m = E._margin_line(t, line + 5e-4, line - 5e-4)
    assert a == pytest.approx(1e-3, abs=1e-9) and b == pytest.approx(2e-6, rel=1e-4) and m == pytest.approx(5e-4)


def test_hull_recovers_a_linear_clock_through_queueing():
    meas, truth = _linear_clock()
    est = E.convex_hull(meas)
    err = score(est, truth, warmup=64 * 16.0)
    raw = score(meas, truth, warmup=64 * 16.0)
    assert err["rms"] < 20e-6 < raw["rms"] / 50  # µs against ms of queueing
    assert len(est) == len(meas)


def test_hull_is_causal_and_takes_a_time_window():
    meas, _ = _linear_clock(n=200)
    a = E.convex_hull(meas, samples=32)
    b = E.convex_hull(TimeSeries(meas.t[:100], meas.offset[:100], extra={"delay": meas.extra["delay"][:100]}),
                      samples=32)
    np.testing.assert_allclose(a.offset[:100], b.offset)  # later samples never change earlier estimates
    w = E.convex_hull(meas, window=600.0)
    assert np.isfinite(w.offset).all()
    with pytest.raises(ValueError, match="delay"):
        E.convex_hull(TimeSeries(meas.t, meas.offset))


def test_hull_beats_the_clock_filter_with_symmetric_floors():
    rows = summarize(run_bench(load_scenarios(["internet"]), ["mindelay", "hull"], seeds=(1, 2)))
    by = {r["estimator"]: r["rms"] for r in rows}
    assert by["hull"] < by["mindelay"] / 3


def test_kalman_combine_rejects_falsetickers():
    meas, truth = simulate_multi(PRESETS["falseticker"].__class__(**{**PRESETS["falseticker"].__dict__, "seed": 3}))
    est = E.kalman_combine(meas)
    err = score(est, truth, warmup=1800)
    assert err["max_abs"] < 5e-3  # one server is 40 ms off and another steps by 100 ms


def test_new_estimators_are_registered():
    av = E.available()
    assert "hull" in av and not av["hull"].multi
    assert "kalman-combine" in av and av["kalman-combine"].multi
