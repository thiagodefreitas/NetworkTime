# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Delay traces: extraction recovers known one-way delays; replay reproduces the network."""

import os

import numpy as np
import pytest

from ntpstats import trace as tr
from ntpstats.bench import load_scenarios, run_bench, summarize
from ntpstats.series import TimeSeries
from ntpstats.simulate import PRESETS, Scenario, simulate_ntp

DATA = os.path.join(os.path.dirname(__file__), "..", "examples", "data")


def _synthetic(n=4000, poll=16.0, seed=1, asym=0.0):
    rng = np.random.default_rng(seed)
    t = 1.7e9 + poll * np.arange(n)
    rel = t - t[0]
    theta = 3e-3 + 2e-7 * rel + 2e-4 * np.sin(rel / 20000)  # wandering true offset (reference - local)
    df = 2e-3 + asym + rng.exponential(1e-3, n) * (rng.random(n) < 0.5)
    db = 2e-3 + rng.exponential(2e-3, n) * (rng.random(n) < 0.5)
    s = TimeSeries(t, theta + (df - db) / 2, name="syn", extra={"delay": df + db})
    return s, df, db


def test_extraction_recovers_one_way_delays():
    s, df, db = _synthetic()
    t = tr.from_series(s)
    err_f, err_b = t.to_ref - df, t.from_ref - db
    assert np.median(np.abs(err_f)) < 20e-6 and np.median(np.abs(err_b)) < 20e-6  # vs 1-2 ms of queueing
    assert np.percentile(np.abs(err_f), 95) < 100e-6
    st = t.stats()
    assert st["to_ref"]["floor"] == pytest.approx(2e-3, abs=50e-6)
    assert st["from_ref"]["p99"] == pytest.approx(np.percentile(db, 99), rel=0.05)


def test_asymmetry_is_an_assumption_not_a_measurement():
    s, df, db = _synthetic(asym=1e-3)
    blind = tr.from_series(s)  # equal floors assumed: the 1 ms is split in two
    told = tr.from_series(s, asymmetry=1e-3)
    assert np.nanmin(blind.to_ref) == pytest.approx(np.nanmin(blind.from_ref), abs=50e-6)
    assert np.median(np.abs(told.to_ref - df)) < 20e-6


def test_linear_and_none_detrend():
    s, df, db = _synthetic()
    lin = tr.from_series(s, detrend="linear")
    assert np.median(np.abs(lin.to_ref - df)) < 300e-6  # the sine is not removed by a line
    s0 = TimeSeries(s.t, (df - db) / 2, extra={"delay": df + db})
    none = tr.from_series(s0, detrend="none")
    np.testing.assert_allclose(none.to_ref, df, atol=1e-12)
    with pytest.raises(ValueError):
        tr.from_series(s, detrend="spline")


def test_csv_round_trip(tmp_path):
    s, _, _ = _synthetic(n=300)
    t = tr.from_series(s)
    p = tmp_path / "t.csv"
    p.write_text(t.to_csv())
    back = tr.load_trace(str(p))
    np.testing.assert_allclose(back.to_ref, t.to_ref, rtol=1e-12)
    np.testing.assert_allclose(back.from_ref, t.from_ref, rtol=1e-12)


@pytest.mark.parametrize("name", ["ptp-capture.pcapng", "ntp-capture.pcap", "chrony-measurements.log",
                                  "peerstats.example"])
def test_real_inputs(name):
    t = tr.load_trace(os.path.join(DATA, name))
    st = t.stats()
    assert st["exchanges"] > 10 and st["to_ref"]["floor"] >= 0 and st["from_ref"]["median"] > 0


def test_series_without_delay_is_refused():
    with pytest.raises(ValueError, match="round-trip"):
        tr.from_series(TimeSeries(np.arange(10.0), np.zeros(10)))


def test_replay_loops_in_time_order():
    s, df, db = _synthetic(n=100, poll=10.0)
    path = tr.TracePath(tr.from_series(s), mode="replay")
    rel = np.arange(0.0, 2000.0, 10.0)
    f, b = path.delays(rel, np.random.default_rng(0))
    np.testing.assert_allclose(f[:100], path.trace.to_ref)
    np.testing.assert_allclose(f[100:], path.trace.to_ref)  # looped


def test_bootstrap_keeps_distribution_and_pairs():
    s, df, db = _synthetic(n=4000)
    trace = tr.from_series(s)
    path = tr.TracePath(trace, mode="bootstrap", block=1600.0)
    rel = np.arange(0.0, 4000 * 16.0, 16.0)
    f1, b1 = path.delays(rel, np.random.default_rng(1))
    f2, _ = path.delays(rel, np.random.default_rng(2))
    assert not np.array_equal(f1, f2)
    for q in (10, 50, 90, 99):
        assert np.percentile(f1, q) == pytest.approx(np.percentile(trace.to_ref, q), rel=0.15, abs=20e-6)
    pairs = set(zip(trace.to_ref.round(12), trace.from_ref.round(12)))
    assert all((a, b) in pairs for a, b in zip(f1[:200].round(12), b1[:200].round(12)))  # directions stay together


def test_scale_multiplies_queueing_only():
    s, _, _ = _synthetic(n=500)
    trace = tr.from_series(s)
    f, b = tr.TracePath(trace, scale=2.0).delays(trace.t, np.random.default_rng(0))
    floor = np.nanmin(trace.to_ref)
    np.testing.assert_allclose(f - floor, 2 * (trace.to_ref - floor), atol=1e-15)


def test_lost_exchanges_become_packet_loss():
    s, df, db = _synthetic(n=200, poll=16.0)
    trace = tr.from_series(s)
    trace.to_ref[50:60] = np.nan
    sc = Scenario(duration=200 * 16.0, poll=16.0, seed=1, trace=tr.TracePath(trace))
    meas, _ = simulate_ntp(sc)
    assert len(meas) == 190


def test_replayed_trace_scores_like_the_original_network():
    """Round trip: delays extracted from a simulated run, replayed, give the same estimator errors."""
    sc = Scenario(**{**PRESETS["internet"].__dict__, "duration": 2 * 86400.0, "seed": 5})
    meas, _ = simulate_ntp(sc)
    trace = tr.from_series(meas)
    replay = Scenario(**{**sc.__dict__, "trace": tr.TracePath(trace)})
    a = summarize(run_bench([("model", sc)], ["raw", "mindelay"], seeds=(5,), warmup=3600))
    b = summarize(run_bench([("trace", replay)], ["raw", "mindelay"], seeds=(5,), warmup=3600))
    for ra, rb in zip(sorted(a, key=lambda r: r["estimator"]), sorted(b, key=lambda r: r["estimator"])):
        assert rb["rms"] == pytest.approx(ra["rms"], rel=0.25), ra["estimator"]


def test_scenario_file_and_cli_spec(tmp_path):
    s, _, _ = _synthetic(n=400)
    (tmp_path / "net.csv").write_text(tr.from_series(s).to_csv())
    (tmp_path / "sc.toml").write_text('name = "replayed"\nduration = 3200\npoll = 16\n'
                                      '[trace]\nfile = "net.csv"\nmode = "bootstrap"\nblock = 320\n')
    (name, sc), = load_scenarios([str(tmp_path / "sc.toml")])
    assert name == "replayed" and sc.trace.mode == "bootstrap"
    (name2, sc2), = load_scenarios([f"trace:{tmp_path / 'net.csv'}"])
    assert sc2.poll == pytest.approx(16.0) and sc2.trace.mode == "replay"
    rows = run_bench([(name, sc), (name2, sc2)], ["raw"], seeds=(1,), warmup=0)
    assert all(np.isfinite(r["rms"]) for r in rows)
    with pytest.raises(ValueError, match="unknown"):
        tr.trace_path_from_dict({"file": "net.csv", "colour": 1}, str(tmp_path))


def test_cli_trace_and_bench(tmp_path, capsys):
    from ntpstats.cli import main

    out = tmp_path / "t.csv"
    assert main(["trace", os.path.join(DATA, "chrony-measurements.log"), "--peer", "192.0.2.10",
                 "--csv", str(out)]) == 0
    text = capsys.readouterr().out
    assert "to reference" in text and "from reference" in text and "cannot measure" in text
    assert main(["trace", os.path.join(DATA, "ptp-capture.pcapng"), "--json"]) == 0
    import json

    assert json.loads(capsys.readouterr().out)["exchanges"] > 100
    assert main(["bench", f"trace:{out}", "-e", "raw,mindelay", "--seeds", "1", "--warmup", "0"]) == 0
    assert "mindelay" in capsys.readouterr().out


def test_short_trace_still_removes_a_drifting_offset():
    # 10 minutes, shorter than one default detrend window: the drift must not leak into the delays
    import numpy as np

    from ntpstats.series import TimeSeries
    from ntpstats.trace import from_series

    t = 1.79e9 + np.arange(600.0)
    theta = 4e-6 + 2e-9 * (t - t[0])
    s = TimeSeries(t, theta, extra={"delay": np.full(600, 4e-6)})
    for mode in ("floor", "linear"):
        tr = from_series(s, detrend=mode)
        assert np.ptp(tr.to_ref) < 1e-9 and np.ptp(tr.from_ref) < 1e-9
