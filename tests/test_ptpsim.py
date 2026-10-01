# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""PTP servos and boundary-clock chains against cases with a known answer."""

import numpy as np
import pytest

from ntpstats import ptpsim as P
from ntpstats.simulate import ClockModel, PathModel
from ntpstats.trace import DelayTrace, TracePath

QUIET = ClockModel(freq_offset=0.0, drift=0.0, white_fm_adev1=0.0, rw_fm_adev1=0.0, initial_offset=1e-3)


def _sc(**kw):
    base = dict(hops=1, duration=600.0, sync_rate=4.0, delay_rate=4.0, oscillator=QUIET, freq_spread=0.0,
                link=P.Link(timestamp_noise=0.0), warmup=200.0, seed=1)
    base.update(kw)
    return P.ChainScenario(**base)


def test_linuxptp_default_gains():
    kp, ki = P.PIServo().gains(1 / 16)
    assert kp == pytest.approx(0.7 * (1 / 16) ** -0.3) and ki == pytest.approx(0.3 * (1 / 16) ** 0.4)
    kp1, ki1 = P.PIServo().gains(1.0)
    assert (kp1, ki1) == (pytest.approx(0.7), pytest.approx(0.3))


@pytest.mark.parametrize("servo", P.SERVOS)
def test_servo_steps_then_locks_out_a_frequency_offset(servo):
    sc = _sc(servo=servo, oscillator=ClockModel(**{**QUIET.__dict__, "freq_offset": 3e-6}))
    r = P.simulate_chain(sc)
    x = r.te[1]  # powered up 1 ms off: stepped at the first (linreg) or second (pi) sample
    assert np.max(np.abs(x[r.t > 100])) < 1e-9  # stepped, then the 3 ppm offset is tracked out
    assert r.nodes[0]["max_te"] < 1e-9


def test_asymmetry_adds_half_per_hop():
    r = P.simulate_chain(_sc(hops=5, link=P.Link(asymmetry=40e-9, timestamp_noise=0.0)))
    assert [n["cte"] for n in r.nodes] == pytest.approx([20e-9 * k for k in range(1, 6)], rel=1e-3)
    assert [h["cte"] for h in r.hops] == pytest.approx([20e-9] * 5, rel=1e-3)


def test_asymmetry_spread_is_drawn_per_hop():
    r = P.simulate_chain(_sc(hops=4, asymmetry_spread=50e-9))
    assert len(set(r.asymmetries)) == 4 and all(abs(a) <= 50e-9 for a in r.asymmetries)
    assert r.nodes[-1]["cte"] == pytest.approx(sum(r.asymmetries) / 2, rel=1e-3, abs=1e-12)


def test_noise_accumulates_along_the_chain():
    sc = P.ChainScenario(hops=8, duration=900.0, sync_rate=8.0, delay_rate=8.0, warmup=200.0, seed=3)
    r = P.simulate_chain(sc)
    rms = [n["rms"] for n in r.nodes]
    assert rms[-1] > 2 * rms[0]
    assert all(np.isfinite(v) for h in r.hops for v in (h["max_te"], h["dte_l_mtie"], h["dte_h_pp"]))


def test_pdv_between_boundary_clocks_costs_accuracy():
    clean = P.simulate_chain(_sc(hops=2, link=P.Link(timestamp_noise=4e-9)))
    pdv = P.simulate_chain(_sc(hops=2, link=P.Link(timestamp_noise=4e-9, pdv=PathModel(queue_mean=2e-6, load=0.5))))
    assert pdv.nodes[-1]["max_te"] > 3 * clean.nodes[-1]["max_te"]


def test_trace_link_replays_captured_delays():
    rng = np.random.default_rng(0)
    n = 400
    trace = DelayTrace(np.arange(n) * 0.25, 1e-6 + rng.exponential(50e-9, n), 1e-6 + rng.exponential(50e-9, n))
    r = P.simulate_chain(_sc(hops=1, link=P.Link(trace=TracePath(trace, mode="bootstrap", block=10.0))))
    assert 1e-9 < r.nodes[0]["max_te"] < 1e-6


def test_check_against_class_and_budget():
    r = P.simulate_chain(_sc(hops=3, link=P.Link(asymmetry=60e-9, timestamp_noise=0.0)))
    c = r.check(cls="B")  # 30 ns of cTE per hop: class B allows 20 ns
    assert not c["hops_passed"] and not c["passed"]
    assert any(row["metric"] == "cte" and not row["passed"] for row in c["checks"])
    assert c["budget"]["passed"]  # 90 ns at the end is well inside 1.1 µs
    ok = r.check(limits={"cte": 50e-9}, budget=None)
    assert ok["passed"] and "budget" not in ok
    assert P.CLASS_LIMITS["C"]["cte"] < P.CLASS_LIMITS["B"]["cte"] < P.CLASS_LIMITS["A"]["cte"]


def test_series_and_dict_and_from_dict():
    r = P.simulate_chain(_sc(hops=2))
    s = r.series(2)
    np.testing.assert_allclose(s.offset, -r.te[2])
    d = r.as_dict()
    assert d["hops"] == 2 and len(d["nodes"]) == 2 and len(d["per_hop"]) == 2
    sc = P.chain_from_dict({"chain": {"hops": 3, "servo": "linreg", "link": {"asymmetry": 1e-9, "pdv": {"queue_mean": 1e-7}},
                                      "oscillator": {"freq_offset": 1e-6}}})
    assert sc.hops == 3 and sc.link.pdv.queue_mean == 1e-7 and sc.oscillator.freq_offset == 1e-6


def test_bad_input():
    with pytest.raises(ValueError):
        P.simulate_chain(_sc(hops=0))
    with pytest.raises(ValueError):
        P.simulate_chain(_sc(servo="pid"))
    with pytest.raises(ValueError, match="warm-up"):
        P.simulate_chain(_sc(duration=100.0, warmup=200.0))


def test_cli_chain(tmp_path, capsys):
    import json

    from ntpstats.cli import main

    assert main(["chain", "--hops", "2", "--duration", "8m", "--sync-rate", "4", "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert "end of chain" in out and "overall: PASS" in out
    rc = main(["chain", "--hops", "2", "--duration", "8m", "--sync-rate", "4", "--asymmetry", "60ns",
               "--json", "--csv", str(tmp_path / "te.csv")])
    d = json.loads(capsys.readouterr().out)
    assert rc == 3 and not d["verdict"]["passed"] and d["delay_rate"] == 4
    assert (tmp_path / "te.csv").read_text().startswith("t,te_node1,te_node2")
    lim = tmp_path / "lim.txt"
    lim.write_text("cte,40ns\n")
    assert main(["chain", "--hops", "1", "--duration", "8m", "--sync-rate", "4", "--asymmetry", "60ns",
                 "--limits", str(lim), "--budget", "100ns"]) == 0


def test_gain_peaking_accumulates_and_a_narrow_loop_avoids_it():
    """linuxptp's single-slave PI gains peak near their bandwidth; cascaded, the peaks multiply.

    A narrower, well-damped loop (about 0.05 Hz, the range G.8273.2 sets for chains) keeps the
    dynamic TE of a long chain small once locked (it needs a longer warm-up).
    """
    kw = dict(hops=12, duration=2400.0, warmup=1200.0, sync_rate=4.0, seed=1)
    default = P.simulate_chain(P.ChainScenario(**kw))
    narrow = P.simulate_chain(P.ChainScenario(**kw, servo_options={"kp": 0.3, "ki": 0.0056 / 4}))
    d = [n["dte_l_mtie"] for n in default.nodes]
    assert d[-1] > 5 * d[0]  # super-linear growth along the chain
    assert narrow.nodes[-1]["dte_l_mtie"] < d[-1] / 4
