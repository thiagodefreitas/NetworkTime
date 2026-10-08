# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Validation against an independent reference (ntpstats validate): synthetic campaigns with a known truth."""

import json

import numpy as np
import pytest

from ntpstats.cli import main
from ntpstats.parsers import load
from ntpstats.refcheck import synthetic_campaign, truth_at, validate
from ntpstats.series import TimeSeries


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    d = tmp_path_factory.mktemp("campaign")
    p = synthetic_campaign(str(d), hours=3, seed=2)
    return p, load(p["refclocks"])[0], load(p["tracking"])[0], load(p["measurements"])


def test_truth_interpolation_respects_gaps():
    ref = TimeSeries(np.array([0.0, 1.0, 2.0, 10.0, 11.0]), np.array([0.0, 1.0, 2.0, 10.0, 11.0]))
    x = truth_at(ref, np.array([-1.0, 0.0, 0.5, 2.0, 5.0, 10.5, 11.0, 12.0]), max_gap=4.0)
    assert np.isnan(x[0]) and x[1] == 0.0 and x[2] == 0.5 and x[3] == 2.0
    assert np.isnan(x[4])  # inside the 8 s gap
    assert x[5] == 10.5 and x[6] == 11.0 and np.isnan(x[7])


def test_clock_bound_servers_and_estimators(campaign):
    _, ref, tr, meas = campaign
    r = validate(ref, tr, meas, warmup=1800)
    # the clock's error is the reference itself
    late = ref.t >= ref.t[0] + 1800
    raw = ref.extra["raw_error"][late]  # chrony's raw column: the system clock as applications read it
    assert r.clock["rms"] == pytest.approx(np.sqrt(np.mean(raw ** 2)))
    assert r.meta["reference_column"] == "raw"
    cooked = validate(ref, estimators=None, warmup=1800, reference_column="cooked")
    assert cooked.clock["rms"] == pytest.approx(np.sqrt(np.mean(ref.offset[late] ** 2)))
    assert "tdev" in r.clock and "mtie" in r.clock
    # chrony's maximum error (1.35 ms) holds against a clock wandering by tens of microseconds
    b = r.bound
    assert b["source"].startswith("max error") and b["violations"] == 0 and r.passed
    assert b["self_estimate"]["rms"] == pytest.approx(5e-6, rel=0.3)  # the daemon's estimate had 5 us of noise
    # servers: error + mean asymmetry as bias; the falseticker leaves its correctness interval every time
    srv = {s["peer"]: s for s in r.servers}
    assert srv["192.0.2.1"]["bias"] == pytest.approx(2e-4, abs=3e-5)
    assert srv["192.0.2.2"]["bias"] == pytest.approx(-2e-3, abs=4e-4)
    for peer in ("192.0.2.1", "192.0.2.2", "198.51.100.3"):
        assert srv[peer]["within_bound"] == 1.0
    assert srv["203.0.113.4"]["within_bound"] == 0.0 and srv["203.0.113.4"]["worst_ratio"] > 3
    # estimators: sorted by RMS; the delay-aware ones on the best server beat its raw offsets
    rms = [e["rms"] for e in r.estimators]
    assert rms == sorted(rms)
    best = {(e["estimator"], e["peer"]): e["rms"] for e in r.estimators}
    assert best[("hull", "192.0.2.1")] < best[("raw", "192.0.2.1")]
    assert best[("rfc5905", "all")] < best[("median", "all")]  # selection drops the falseticker
    assert json.loads(json.dumps(r.as_dict(), default=float))["passed"] is True


def test_a_dishonest_bound_fails(tmp_path):
    p = synthetic_campaign(str(tmp_path), hours=2, seed=3, falseticker=False, bound_scale=0.01)  # claims 13.5 us
    r = validate(load(p["refclocks"])[0], load(p["tracking"])[0], estimators=None)
    assert not r.passed and r.bound["violation_rate"] > 0.3 and r.bound["worst_ratio"] > 1
    assert r.bound["unit"] == "samples" and r.bound["checked"] > 30 * r.bound["updates"]  # every 1 Hz sample
    assert validate(load(p["refclocks"])[0], load(p["tracking"])[0], estimators=None,
                    max_violation_rate=1.0).passed


def test_cli(campaign, capsys):
    p, *_ = campaign
    args = ["validate", p["refclocks"], "--tracking", p["tracking"], "--measurements", p["measurements"],
            "--warmup", "30m", "-e", "raw,hull,rfc5905"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "FALSETICKER" in out and "PASS" in out and "hull" in out and "TDEV" in out
    assert main(args + ["--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert {e["estimator"] for e in d["estimators"]} == {"raw", "hull", "rfc5905"}
    neg = ["validate", p["refclocks"], "--negate-reference", "--warmup", "30m", "-e", "none", "--json"]
    assert main(neg) == 0
    assert json.loads(capsys.readouterr().out)["clock"]["bias"] == pytest.approx(-d["clock"]["bias"])
