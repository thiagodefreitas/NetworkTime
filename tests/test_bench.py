# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
import json
import os
import re
from dataclasses import replace

import numpy as np
import pytest

from ntpstats import estimators as E
from ntpstats import stability as st
from ntpstats.analysis import compare
from ntpstats.bench import load_scenarios, run_bench, score, summarize, to_csv
from ntpstats.report import bench_report, dataset_report
from ntpstats.series import TimeSeries
from ntpstats.simulate import (PRESETS, ClockModel, PathEvent, PathModel, Scenario, ServerSpec,
                               scenario_from_dict, simulate_multi, simulate_ntp)

EX = os.path.join(os.path.dirname(__file__), os.pardir, "examples")


# ------------------------------------------------------------ simulator
def test_flicker_fm_floor():
    t = np.arange(0, 2 ** 15, 1.0)
    x = ClockModel(freq_offset=0, drift=0, white_fm_adev1=0, rw_fm_adev1=0, flicker_fm_adev=1e-10).phase(t, 3)
    r = st.compute(x, 1.0, "oadev", [64, 256, 1024], ci=None)
    # flat ADEV floor; a single flicker realisation scatters ~+-40 % at long tau
    np.testing.assert_allclose(r.dev, 1e-10, rtol=0.5)
    assert abs(np.polyfit(np.log10(r.taus), np.log10(r.dev), 1)[0]) < 0.15


def test_temperature_cycle():
    t = np.arange(0, 86400, 60.0)
    c = ClockModel(freq_offset=0, drift=0, white_fm_adev1=0, rw_fm_adev1=0, tempco=1e-7, temp_amplitude=2.0)
    x = c.phase(t, 1)
    y = np.diff(x) / 60
    assert y.max() == pytest.approx(2e-7, rel=0.01) and y.min() == pytest.approx(-2e-7, rel=0.01)


def test_route_change_event_shifts_delay():
    sc = Scenario(duration=7200, poll=16, seed=2, clock=ClockModel(),
                  forward=PathModel(base=5e-3, queue_mean=0, load=0, events=[PathEvent(start=3600, base_delta=4e-3)]),
                  backward=PathModel(base=5e-3, queue_mean=0, load=0), server_noise=0)
    m, truth = simulate_ntp(sc)
    rel = m.t - m.t[0]
    assert np.allclose(m.extra["delay"][rel < 3600], 10e-3) and np.allclose(m.extra["delay"][rel >= 3600], 14e-3)
    err = m.offset - m.extra["true_offset"]
    assert np.allclose(err[rel >= 3600], 2e-3)  # unobservable asymmetry: half the one-way step


def test_outage_event_drops_packets():
    sc = Scenario(duration=3600, poll=16, seed=1, forward=PathModel(events=[PathEvent(start=1000, end=2000, loss=1.0)]))
    m, _ = simulate_ntp(sc)
    rel = m.t - m.t[0]
    assert not np.any((rel > 1000) & (rel < 2000 - 16))


def test_multi_server_and_falsetickers():
    ms, truth = simulate_multi(replace(PRESETS["falseticker"], seed=1, duration=6 * 3600))
    assert len(ms) == 4 and [m.meta["falseticker"] for m in ms] == [False, False, True, True]
    assert abs(np.median(ms[2].offset - ms[2].extra["true_offset"]) - 40e-3) < 5e-3


def test_scenario_toml_files():
    scen = load_scenarios([os.path.join(EX, "scenarios", "wan-route-change.toml"),
                           os.path.join(EX, "scenarios", "pool-with-falsetickers.toml"), "lan"])
    names = [n for n, _ in scen]
    assert names == ["wan-route-change", "pool-with-falsetickers", "lan"]
    assert scen[0][1].forward.events[0].base_delta == 4e-3
    assert len(scen[1][1].servers) == 5 and scen[1][1].servers[4].step == -80e-3
    with pytest.raises(ValueError):
        load_scenarios(["no-such-scenario"])


def test_scenario_from_dict_preset_override():
    sc = scenario_from_dict({"preset": "lan", "duration": 600, "clock": {"freq_offset": 1e-6}})
    assert sc.duration == 600 and sc.poll == PRESETS["lan"].poll and sc.clock.freq_offset == 1e-6


# ----------------------------------------------------------- estimators
@pytest.fixture(scope="module")
def internet():
    return simulate_multi(replace(PRESETS["internet"], seed=5, duration=12 * 3600))


@pytest.mark.parametrize("name", ["kalman", "kalman-dw", "rts-dw", "mindelay", "regression", "feedforward"])
def test_single_server_estimators_beat_raw(internet, name):
    ms, truth = internet
    raw = score(ms[0], truth, 1800)["rms"]
    assert score(E.run(name, ms), truth, 1800)["rms"] < raw / 2


def test_rfc5905_rejects_falsetickers():
    ms, truth = simulate_multi(replace(PRESETS["falseticker"], seed=2, duration=12 * 3600))
    comb = score(E.run("rfc5905", ms), truth, 1800)
    med = score(E.run("median", ms), truth, 1800)
    assert comb["rms"] < 1e-3 and comb["rms"] < med["rms"]


def test_registry_and_entry_points(monkeypatch):
    class Plug(E.Estimator):
        name = "plug"

        def fit(self, s):
            return s

    class EP:
        name = "plug"

        def load(self):
            return Plug

    class EPS(list):
        def select(self, group):
            return self if group == "ntpstats.estimators" else []

    monkeypatch.setattr("importlib.metadata.entry_points", lambda: EPS([EP()]))
    monkeypatch.delitem(E._REGISTRY, "plug", raising=False)
    assert "plug" in E.available()
    with pytest.raises(KeyError):
        E.get("nope")
    E._REGISTRY.pop("plug", None)


# ----------------------------------------------------------- bench + report
def test_bench_rows_summary_csv():
    scen = load_scenarios(["lan"])
    rows = run_bench(scen, ["raw", "mindelay", "rfc5905"], seeds=[1, 2], duration=3600, warmup=600)
    assert len(rows) == 6 and {r["estimator"] for r in rows} == {"raw", "mindelay", "rfc5905"}
    table = summarize(rows)
    assert table[0]["runs"] == 2 and table[-1]["estimator"] == "raw"  # sorted by RMS
    assert to_csv(rows).splitlines()[0].startswith("scenario,seed,estimator")


def test_bench_survives_failing_estimator():
    class Boom(E.Estimator):
        name = "boom"

        def fit(self, s):
            raise RuntimeError("bad plugin")

    E.register(Boom())
    try:
        rows = run_bench(load_scenarios(["lan"]), ["boom"], seeds=[1], duration=1800, warmup=0)
        assert "bad plugin" in rows[0]["error"] and np.isnan(rows[0]["rms"])
    finally:
        E._REGISTRY.pop("boom")


def _self_contained(doc: str):
    assert "uPlot" in doc and "const REPORT=" in doc
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?://', doc)
    payload = doc.split("const REPORT=", 1)[1]
    return json.JSONDecoder().raw_decode(payload)[0]


def test_dataset_report(tmp_path):
    from ntpstats.parsers import load

    path = os.path.join(EX, "data", "peerstats.example")
    doc = dataset_report(load(path), kinds=("oadev", "tdev"), inputs=[path])
    rep = _self_contained(doc)
    assert rep["meta"]["inputs"][0]["path"] == "peerstats.example" and len(rep["meta"]["inputs"][0]["sha256"]) == 64
    assert {c["kind"] for c in rep["charts"]} >= {"time", "loglog", "scatter"}


def test_bench_report():
    rows = run_bench(load_scenarios(["lan"]), ["raw", "mindelay"], seeds=[1], duration=1800, warmup=0)
    rep = _self_contained(bench_report(rows, summarize(rows), params={"seeds": [1]}))
    assert rep["meta"]["parameters"]["seeds"] == [1] and len(rep["meta"]["rows"]) == 2
