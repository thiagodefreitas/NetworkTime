# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Time-error metrics (issue #20)."""

import math

import numpy as np
import pytest

from ntpstats.masks import load_mask
from ntpstats.series import TimeSeries
from ntpstats.timeerror import check, load_limits, lowpass, time_error


def series_te(te, tau0=1.0, t0=1.8e9):
    """A TimeSeries in ntpstats convention (reference - local) holding TE = local - reference."""
    te = np.asarray(te, dtype=float)
    return TimeSeries(t=t0 + np.arange(te.size) * tau0, offset=-te, name="te")


def test_constant_time_error():
    r = time_error(series_te(np.full(3000, 12e-9)))
    assert r.cte == pytest.approx(12e-9) and r.max_abs_te == pytest.approx(12e-9)
    assert r.max_abs_tel == pytest.approx(12e-9)
    assert r.dte_l_pp == pytest.approx(0, abs=1e-18) and r.dte_h_pp == pytest.approx(0, abs=1e-18)
    assert r.cte_windows.shape == (3, 2) and r.max_abs_cte_window == pytest.approx(12e-9)


def test_sign_convention_and_input_is_te():
    s = series_te(np.full(100, 5e-9))
    assert time_error(s).cte == pytest.approx(5e-9)
    assert time_error(s, input_is_te=True).cte == pytest.approx(-5e-9)


def test_lowpass_step_response_and_bandwidth():
    tau0, hz = 0.01, 0.1
    x = np.ones(3000)
    y = lowpass(np.concatenate(([0.0], x)), tau0, hz)[1:]
    tc = 1 / (2 * math.pi * hz)  # time constant, s
    k = int(round(tc / tau0))
    assert y[k - 1] == pytest.approx(1 - math.exp(-1), rel=0.02)
    # sinusoid at the corner frequency: amplitude 1/sqrt(2)
    t = np.arange(200_000) * tau0
    y = lowpass(np.sin(2 * math.pi * hz * t), tau0, hz)
    assert np.max(np.abs(y[-20_000:])) == pytest.approx(1 / math.sqrt(2), rel=0.01)


def test_high_and_low_frequency_split():
    t = np.arange(20_000) * 1.0
    slow = 20e-9 * np.sin(2 * math.pi * t / 2000.0)  # 0.0005 Hz: passes the 0.1 Hz filter
    fast = 10e-9 * (-1) ** np.arange(t.size)  # Nyquist: removed by the filter
    r = time_error(series_te(slow + fast + 5e-9))
    assert r.cte == pytest.approx(5e-9, abs=1e-10)
    # a first-order filter sampled at 1 Hz passes a / (2 - a) of the Nyquist component
    a = 1 - math.exp(-2 * math.pi * 0.1 * 1.0)
    g = a / (2 - a)
    assert r.dte_l_pp == pytest.approx(40e-9 + 2 * 10e-9 * g, rel=0.01)
    assert r.dte_h_pp == pytest.approx(2 * 10e-9 * (1 - g), rel=0.05)
    assert r.max_abs_te == pytest.approx(35e-9, rel=0.01)
    assert r.mtie is not None and r.tdev is not None and r.tdev.lo is not None


def test_gaps_restart_filter_and_are_skipped():
    te = np.full(2000, 3e-9)
    t = 1.8e9 + np.arange(2000.0)
    keep = (t < 1.8e9 + 800) | (t > 1.8e9 + 1200)
    s = TimeSeries(t=t[keep], offset=-te[keep], name="gappy")
    r = time_error(s, max_gap=3)
    assert r.n == keep.sum() and np.isnan(r.te).any()
    assert r.max_abs_tel == pytest.approx(3e-9)


def test_slow_sampling_warns():
    r = time_error(series_te(np.zeros(100), tau0=16.0))
    assert any("too long" in w for w in r.warnings)


def test_limits_file_units_and_errors():
    lim = load_limits("# limits chosen by the user\nmetric,value\nmax_te, 30ns\ncte_window 10e-9\ndte_h_pp;70 ns\n")
    assert lim == {"max_te": pytest.approx(30e-9), "cte_window": pytest.approx(10e-9),
                   "dte_h_pp": pytest.approx(70e-9)}
    with pytest.raises(ValueError):
        load_limits("max_tee, 1ns")
    with pytest.raises(ValueError):
        load_limits("max_te, 1 furlong")


def test_check_limits_and_masks():
    rng = np.random.default_rng(4)
    r = time_error(series_te(8e-9 + rng.normal(0, 1e-9, 5000)))
    ok = check(r, {"max_te": 30e-9, "cte": 10e-9}, [load_mask("tau,mtie\n1,40e-9\n1000,40e-9\n")])
    assert ok["passed"] is True and len(ok["checks"]) == 3
    bad = check(r, {"cte": 5e-9})
    assert bad["passed"] is False and bad["checks"][0]["margin"] < 0
    assert check(r)["passed"] is None
    other = check(r, masks=[load_mask("tau,oadev\n1,1e-9\n10,1e-9\n")])
    assert other["checks"][0]["passed"] is None


def test_from_ptp_capture():
    from ptp_util import pcapng_ns, scenario

    from ntpstats.ptp import parse_ptp

    (s,) = parse_ptp(pcapng_ns(scenario(n=400, x_ns=250)), "cap")
    r = time_error(s)
    assert r.cte == pytest.approx(250e-9, abs=1e-12) and r.dte_h_pp == pytest.approx(0, abs=1e-12)
