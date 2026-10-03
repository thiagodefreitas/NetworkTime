"""Exchange-level PTP in the simulator and the bench, and the ptp4l / SPTP-style client models."""

from dataclasses import replace

import numpy as np
import pytest

from ntpstats.bench import run_bench, summarize
from ntpstats.estimators import available, ptp4l, sptp
from ntpstats.simulate import PRESETS, ClockModel, PathModel, Scenario, scenario_from_dict, simulate_multi, simulate_ntp


def _ideal(**kw):
    base = dict(duration=1800, poll=1.0, protocol="ptp", seed=3, server_noise=0.0,
                clock=ClockModel(freq_offset=5e-6, white_fm_adev1=0.0, rw_fm_adev1=0.0, white_pm=0.0),
                forward=PathModel(base=5e-6, queue_mean=0.0, load=0.0),
                backward=PathModel(base=5e-6, queue_mean=0.0, load=0.0))
    base.update(kw)
    return Scenario(**base)


def test_ptp_series_columns_and_delay_requests():
    meas, _ = simulate_ntp(_ideal(delay_interval=4.0))
    assert meas.meta["protocol"] == "ptp" and meas.meta["delay_every"] == 4
    sm = meas.extra["sm"]
    assert np.isfinite(sm[::4]).all() and np.isnan(sm[1::4]).all()
    # symmetric, queue-free, noise-free path: the slave's offset is exactly the truth
    assert np.allclose(meas.offset, meas.extra["true_offset"], atol=1e-15)
    assert np.allclose(meas.extra["delay"], 10e-6)
    # ms = d - theta with the ntpd sign convention
    assert np.allclose(meas.extra["ms"], 5e-6 - meas.extra["true_offset"])


def test_asymmetric_queueing_biases_raw_offset_and_transparent_clocks_remove_it():
    path = dict(forward=PathModel(base=5e-6, queue_mean=2e-6, load=0.5),
                backward=PathModel(base=5e-6, queue_mean=8e-6, load=0.8))
    raw, _ = simulate_ntp(_ideal(**path))
    tc, _ = simulate_ntp(_ideal(transparent=1.0, **path))
    e_raw = raw.offset - raw.extra["true_offset"]
    e_tc = tc.offset - tc.extra["true_offset"]
    assert np.std(e_raw) > 1e-6
    assert np.max(np.abs(e_tc)) < 1e-15  # every queueing delay corrected


def test_ptp4l_locks_on_clean_exchanges():
    meas, truth = simulate_ntp(_ideal())
    est = ptp4l(meas)
    late = est.t > est.t[0] + 600
    err = est.offset[late] - np.interp(est.t[late], truth.t, truth.offset)
    assert np.max(np.abs(err)) < 1e-9
    lr = ptp4l(meas, servo="linreg")
    late = lr.t > lr.t[0] + 600
    assert np.max(np.abs(lr.offset[late] - np.interp(lr.t[late], truth.t, truth.offset))) < 1e-9


def test_sptp_uses_complete_exchanges_and_discards_queueing_outliers():
    sc = _ideal(delay_interval=2.0, forward=PathModel(base=5e-6, queue_mean=20e-6, load=0.1),
                backward=PathModel(base=5e-6, queue_mean=20e-6, load=0.1), server_noise=5e-9)
    meas, truth = simulate_ntp(sc)
    est = sptp(meas)
    assert est.meta["discarded"] > 0
    assert len(est) <= np.isfinite(meas.extra["sm"]).sum()
    late = est.t > est.t[0] + 600
    err = est.offset[late] - np.interp(est.t[late], truth.t, truth.offset)
    assert np.sqrt(np.mean(err ** 2)) < 5e-6


def test_ptp_clients_also_run_on_ntp_series():
    meas, truth = simulate_ntp(replace(PRESETS["lan"], duration=3 * 3600, seed=2))
    for est in (ptp4l(meas), sptp(meas)):
        assert len(est) > 100 and np.isfinite(est.offset).all()


def test_registered_and_benchmarked():
    names = available()
    assert {"ptp4l", "sptp"} <= set(names)
    sc = replace(PRESETS["ptp-tc"], duration=1800)
    rows = run_bench([("ptp-tc", sc)], ["raw", "mindelay", "ptp4l", "sptp"], seeds=[1], warmup=300)
    table = {r["estimator"]: r for r in summarize(rows)}
    assert all(np.isfinite(r["rms"]) for r in table.values())
    assert table["mindelay"]["rms"] < table["raw"]["rms"]


def test_multi_server_ptp_and_scenario_file_keys():
    sc = scenario_from_dict({"protocol": "ptp", "poll": 0.5, "delay_interval": 2, "transparent": 0.5,
                             "duration": 600, "seed": 1})
    assert (sc.protocol, sc.poll, sc.delay_interval, sc.transparent) == ("ptp", 0.5, 2, 0.5)
    meas, truth = simulate_multi(sc)
    assert meas[0].meta["delay_every"] == 4 and "ms" in meas[0].extra


def test_unknown_protocol():
    with pytest.raises(ValueError, match="protocol"):
        simulate_ntp(_ideal(protocol="ntpv5"))
