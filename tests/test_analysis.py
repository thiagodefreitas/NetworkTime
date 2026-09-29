# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
import numpy as np
import pytest

from ntpstats import analysis, filters, network
from ntpstats.series import TimeSeries
from ntpstats.simulate import PRESETS, ClockModel, Scenario, simulate_ntp


def linear_series(n=500, slope=2e-6, noise=1e-5, seed=0):
    rng = np.random.default_rng(seed)
    t = 1.7e9 + 64.0 * np.arange(n)
    return TimeSeries(t, slope * (t - t[0]) + 1e-3 + rng.normal(0, noise, n), name="lin")


def test_summary_trend_and_percentiles():
    s = linear_series()
    r = analysis.summary(s)
    assert r["samples"] == 500
    assert r["offset_slope_ppm"] == pytest.approx(2.0, rel=1e-2)
    assert r["offset_slope_robust_ppm"] == pytest.approx(2.0, rel=2e-2)
    assert r["residual_rms"] == pytest.approx(1e-5, rel=0.15)
    assert r["percentiles"]["p5"] < r["percentiles"]["p50"] < r["percentiles"]["p95"]
    assert r["regularity"] == 1.0 and r["gaps"] == 0


def test_theil_sen_resists_outliers():
    s = linear_series(noise=1e-7)
    y = s.offset.copy()
    y[::7] += 0.05  # 14 % gross outliers
    lsq, _ = analysis.linear_fit(s.t, y)
    ts = analysis.theil_sen_slope(s.t, y)
    assert abs(ts - 2e-6) < abs(lsq - 2e-6)
    assert ts == pytest.approx(2e-6, rel=1e-2)


def test_outlier_removal_after_detrending():
    s = linear_series(noise=1e-6)
    y = s.offset.copy()
    y[[10, 200, 400]] += 1e-3
    s2 = TimeSeries(s.t, y)
    mask = analysis.mad_outliers(s2.offset, 5, s2.t)
    assert set(np.flatnonzero(mask)) == {10, 200, 400}
    assert analysis.remove_outliers(s2).meta["outliers_removed"] == 3


def test_detrend_quadratic():
    t = np.linspace(0, 1e5, 400)
    x = 1e-3 + 1e-6 * t + 1e-12 * t ** 2
    assert np.max(np.abs(analysis.detrend(t, x, "quadratic"))) < 1e-9
    assert np.max(np.abs(analysis.detrend(t, x, "linear"))) > 1e-4


def test_compare():
    a = TimeSeries(np.arange(10.0), np.ones(10) * 2)
    b = TimeSeries(np.arange(10.0), np.ones(10))
    c = analysis.compare(a, b)
    assert c["bias"] == 1 and c["rms"] == 1


def test_format_seconds():
    assert analysis.format_seconds(1.5e-6) == "1.5 µs"
    assert analysis.format_seconds(-0.02) == "-20 ms"


# ------------------------------------------------------------- filters/network
@pytest.fixture(scope="module")
def sim():
    sc = Scenario(duration=12 * 3600, seed=4)
    return simulate_ntp(sc)


def test_filters_beat_raw_measurements(sim):
    meas, truth = sim
    raw = analysis.compare(meas, truth)["rms"]
    kf = analysis.compare(filters.kalman_series(meas, delay_weighting=False), truth)["rms"]
    kfd = analysis.compare(filters.kalman_series(meas), truth)["rms"]
    md = analysis.compare(network.min_delay_filter(meas), truth)["rms"]
    assert kf < raw / 2
    assert kfd < kf  # delay weighting helps
    assert md < raw / 4


def test_rts_smoother_reduces_error_on_symmetric_path():
    sc = Scenario(duration=6 * 3600, poll=16, seed=9, clock=ClockModel(freq_offset=1e-6))
    sc.backward = sc.forward  # symmetric -> no unremovable bias
    meas, truth = simulate_ntp(sc)
    kf = analysis.compare(filters.kalman_series(meas), truth)["rms"]
    rts = analysis.compare(filters.kalman_series(meas, smooth=True), truth)["rms"]
    assert rts <= kf * 1.05


def test_kalman_estimates_frequency(sim):
    meas, _ = sim
    res = filters.kalman(meas, smooth=True)
    # ClockModel default: local clock 5 ppm fast => offset slope -5 ppm
    assert np.median(res.freq) == pytest.approx(-5e-6, abs=0.3e-6)


def test_network_metrics(sim):
    meas, _ = sim
    d = network.delay_stats(meas)
    assert d["delay_min"] == pytest.approx(0.010, rel=0.01)  # 5 ms + 5 ms base
    assert 0 < d["floor_fraction"] < 1
    t, fpp = network.floor_packet_percentage(meas, window=3600)
    assert fpp.size == 12 and np.all((fpp >= 0) & (fpp <= 100))
    q, x, bound = network.wedge(meas)
    assert np.all(bound == q / 2)


def test_network_requires_delay():
    with pytest.raises(ValueError):
        network.delay_stats(TimeSeries(np.arange(5.0), np.zeros(5)))


def test_presets_run():
    for name, sc in PRESETS.items():
        from dataclasses import replace
        m, tr = simulate_ntp(replace(sc, duration=3600, seed=1))
        assert len(m) > 10 and "true_offset" in m.extra
