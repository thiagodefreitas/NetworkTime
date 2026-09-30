# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Spectra, power-law noise fit (#25), N-cornered hat (#27) and holdover prediction (#26)."""

import json

import numpy as np
import pytest

from ntpstats import hat, holdover, spectrum
from ntpstats import noisefit as nf
from ntpstats.cli import main
from ntpstats.series import TimeSeries
from ntpstats.simulate import ClockModel, powerlaw_phase, scenario_from_dict
from ntpstats.stability import compute

T0 = 1.8e9


def h(q, a, tau0=1.0):
    return nf.h_from_q(q, a, tau0)


# ------------------------------------------------------------------ spectra
def test_white_noise_psd_levels_and_gaps():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1e-9, 1 << 15)  # white PM, sigma 1 ns, tau0 = 1 s
    sp = spectrum.phase_psd(x, 1.0)
    assert np.median(sp.psd) == pytest.approx(2 * 1e-18, rel=0.05)  # one-sided: 2 sigma^2 tau0
    x[5000:5100] = np.nan  # a gap splits the data; still one estimate
    sp2 = spectrum.phase_psd(x, 1.0)
    assert sp2.meta["stretches"] == 2 and np.median(sp2.psd) == pytest.approx(2e-18, rel=0.06)
    mt = spectrum.phase_psd(x[:4096], 1.0, method="multitaper")
    assert np.median(mt.psd) == pytest.approx(2e-18, rel=0.15) and mt.dof[0] == 10
    assert sp.lf_dbc(10e6)[0] == pytest.approx(10 * np.log10((2 * np.pi * 1e7) ** 2 * sp.psd[0] / 2))


def test_frequency_psd_matches_model_for_wfm_and_rwfm():
    for a, q in ((0, 1e-20), (-2, 1e-28)):
        x = nf.simulate({a: h(q, a)}, 1 << 15, 1.0, seed=2)
        sp = spectrum.log_bins(spectrum.frequency_psd(x, 1.0))
        model = nf.spectrum_basis("y", sp.f, a, 1.0) * h(q, a)
        ratio = sp.psd[3:-2] / model[3:-2]
        assert np.median(ratio) == pytest.approx(1.0, rel=0.25)


# ------------------------------------------------------------------ noise model
def test_basis_matches_textbook_formulas_for_large_m():
    m = 512
    assert nf.basis("oadev", m, 0, 1.0) == pytest.approx(1 / (2 * m))  # h0 / 2 tau
    assert nf.basis("oadev", m, -1, 1.0) == pytest.approx(2 * np.log(2), rel=1e-3)
    assert nf.basis("oadev", m, -2, 1.0) == pytest.approx(2 * np.pi ** 2 / 3 * m, rel=1e-4)
    assert nf.basis("oadev", m, 2, 1.0) == pytest.approx(3 * 0.5 / (4 * np.pi ** 2 * m * m))
    assert nf.basis("tdev", 8, 0, 1.0) == pytest.approx(nf.basis("mdev", 8, 0, 1.0) * 64 / 3)


def test_fit_recovers_mixture_and_predicts_curve():
    truth = {2: h(1e-18, 2), 0: h(1e-20, 0), -2: h(1e-25, -2)}  # corners near 20 s and 500 s
    x = nf.simulate(truth, 1 << 14, 1.0, seed=3)
    r = compute(x, 1.0, "oadev")
    f = nf.fit([r], ci=0.95)
    assert set(f.active) == {2, 0, -2}
    for a, v in truth.items():
        assert f.h[a] == pytest.approx(v, rel=0.5)
    assert np.allclose(f.predict("oadev", r.taus), r.dev, rtol=0.35)
    assert any(c["from"] == "white PM" for c in f.corners)
    # spectrum and MDEV inputs work too
    f2 = nf.fit([compute(x, 1.0, "mdev")], [spectrum.log_bins(spectrum.frequency_psd(x, 1.0))])
    assert f2.h[0] == pytest.approx(truth[0], rel=0.5)


def test_bootstrap_intervals_cover_truth():
    """Acceptance (#25): the fitted coefficients fall within their intervals in >= 90 % of runs."""
    runs = 16
    for truth in ({2: h(1e-18, 2), 0: h(1e-20, 0)}, {0: h(1e-20, 0), -1: h(1e-21, -1)}):
        hits = {a: 0 for a in truth}
        for s in range(runs):
            f = nf.fit_phase(nf.simulate(truth, 4096, 1.0, 700 + s), 1.0, ci=0.95, bootstrap=40, seed=s)
            for a, v in truth.items():
                hits[a] += f.lo[a] <= v <= f.hi[a]
        assert all(k / runs >= 0.9 for k in hits.values()), hits


def test_drift_is_not_taken_for_random_walk_fm():
    rng_x = nf.simulate({0: h(1e-20, 0)}, 20000, 1.0, seed=4) + 0.5 * 1e-13 * np.arange(20000.0) ** 2
    plain = nf.fit_phase(rng_x, 1.0, bootstrap=0)
    with_d = nf.fit_phase(rng_x, 1.0, bootstrap=0, drift=True)
    assert plain.h[-2] > 0 and with_d.h[-2] == 0
    assert with_d.drift == pytest.approx(1e-13, rel=0.2)


def test_fitted_model_drives_the_simulator(tmp_path, capsys):
    truth = {2: h(4e-18, 2), 0: h(1e-20, 0)}
    t = T0 + np.arange(8192.0)
    s = TimeSeries(t, nf.simulate(truth, t.size, 1.0, seed=5), name="osc")
    p = tmp_path / "osc.csv"
    p.write_text("unix_time,offset\n" + "".join(f"{a:.1f},{b:.12e}\n" for a, b in zip(s.t, s.offset)))
    toml = tmp_path / "clock.toml"
    assert main(["noise", str(p), "--bootstrap", "0", "--scenario", str(toml), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)[0]
    assert float(doc["h"]["0"]) == pytest.approx(truth[0], rel=0.4)
    tomllib = pytest.importorskip("tomllib")
    clock = tomllib.loads(toml.read_text())["clock"]
    sim = ClockModel(**clock).phase(t, rng=9)
    f = nf.fit_phase(sim, 1.0, bootstrap=0)
    assert f.h[0] == pytest.approx(truth[0], rel=0.4)
    sc = scenario_from_dict({"clock": clock})
    assert sc.clock.h_alpha
    assert main(["noise", str(p), "--bootstrap", "0"]) == 0
    assert "white FM" in capsys.readouterr().out
    assert main(["spectrum", str(p), "--kind", "x", "--carrier", "10e6"]) == 0
    assert "L_dbc_hz" in capsys.readouterr().out


# ------------------------------------------------------------------ hat
def _clocks(levels, n=8192, seed=0, common=1e-7, shared=0.0):
    rng = np.random.default_rng(seed)
    client = powerlaw_phase(n, 0, common, rng)
    corr = powerlaw_phase(n, 0, shared, rng) if shared else 0.0
    rows = [powerlaw_phase(n, 0, lv, rng) - client for lv in levels]
    if shared:
        rows[0] = rows[0] + corr
        rows[1] = rows[1] + corr
    return np.array(rows)


def test_hat_recovers_individual_noise():
    """Acceptance (#27): sources with known, different noise are recovered within the intervals."""
    levels = [2e-9, 5e-9, 1e-8]
    cover = np.zeros(3)
    for s in range(10):
        X = _clocks(levels, seed=s)
        for m in ("gcov", "nch"):
            r = hat.hat(X, 1.0, method=m, ci=0.95)
            truth = np.array(levels)[:, None] / np.sqrt(r.taus)[None, :]
            if m == "gcov":
                cover += ((r.lo <= truth) & (truth <= r.hi)).mean(axis=1)
    assert np.all(cover / 10 >= 0.85)
    r3 = hat.hat(_clocks(levels, seed=1), 1.0, method="3ch")
    rg = hat.hat(_clocks(levels, seed=1), 1.0, method="gcov")
    assert np.allclose(r3.var, rg.var, rtol=1e-9)  # identical estimates for three sources
    assert np.allclose(r3.dev[2, :4], 1e-8 / np.sqrt(r3.taus[:4]), rtol=0.2)


def test_hat_flags_negative_and_correlated_cases():
    r = hat.hat(_clocks([1e-10, 1e-8, 1e-8], seed=2), 1.0, method="3ch")
    assert r.negative[0].any() and r.meta["negative_variances"] > 0
    assert np.all(r.lo[0][r.negative[0]] == 0)
    # correlated noise shared by sources 0 and 1 is removed from both and pushed onto source 2
    rc = hat.hat(_clocks([1e-9, 1e-9, 1e-9], seed=3, shared=5e-9), 1.0, method="gcov")
    assert np.nanmedian(rc.dev[2] * np.sqrt(rc.taus)) > 3e-9
    with pytest.raises(ValueError):
        hat.hat(_clocks([1e-9] * 4), 1.0, method="3ch")


def test_hat_cli_from_monitor_style_logs(tmp_path, capsys):
    X = _clocks([2e-9, 5e-9, 1e-8], n=4096, seed=4)
    paths = []
    for i, row in enumerate(X):
        p = tmp_path / f"s{i}.csv"
        t = T0 + np.arange(row.size) + 0.3 * i  # servers queried at slightly different times
        p.write_text("unix_time,offset\n" + "".join(f"{a:.3f},{b:.12e}\n" for a, b in zip(t, row)))
        paths.append(str(p))
    assert main(["hat", *paths, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["method"] == "gcov" and len(doc["sources"]) == 3
    assert main(["hat", *paths]) == 0
    assert "Groslambert" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["hat", *paths[:2]])


# ------------------------------------------------------------------ holdover
def test_holdover_envelope_is_calibrated_with_known_noise():
    """Acceptance (#26): the 95 % envelope contains the truth in 95 +- 3 % of trials (known model)."""
    truth = {2: h(1e-18, 2), 0: h(1e-20, 0), -2: h(1e-26, -2)}
    inside = []
    for s in range(120):
        x = nf.simulate(truth, 4000, 1.0, s)
        res, pred, xs, steps = holdover._core(x[:2000], 1.0, 2000, truth, "frequency", None, 0.95, 10, None,
                                              False)
        act = np.array([pred.tie(xs, int(k), x[1999 + int(k)]) for k in steps])
        inside.append((act >= res.lo) & (act <= res.hi))
    assert np.mean(inside) == pytest.approx(0.95, abs=0.03)


def test_holdover_drift_mean_and_time_to_violation():
    truth = {0: h(1e-20, 0)}
    x = nf.simulate(truth, 20000, 1.0, 7) + 0.5 * 1e-12 * np.arange(20000.0) ** 2
    r = holdover.predict(x, 1.0, 86400, model="frequency", limits=[1e-6], uncertainty=0)
    assert r.meta["drift_in_mean"] and r.drift == pytest.approx(1e-12, rel=0.1)
    # mean TIE follows the drift the frequency-only holdover cannot correct: 1/2 D t^2 plus the lag of the fit
    assert r.mean[-1] > 0.5 * 1e-12 * 86400 ** 2
    tt = r.limits["1e-06"]
    assert tt["envelope"] is not None and tt["envelope"] <= tt["mean"]
    rd = holdover.predict(x, 1.0, 86400, model="drift", limits=[1e-6], uncertainty=0)
    assert np.all(rd.mean == 0) and (rd.limits["1e-06"]["envelope"] or 1e9) > tt["envelope"]


def test_holdover_backtest_and_cli(tmp_path, capsys):
    truth = {2: h(1e-18, 2), 0: h(1e-20, 0)}
    x = nf.simulate(truth, 40000, 1.0, 8)
    bt = holdover.backtest(x, 1.0, 3600, trials=15, h=truth)
    assert bt["coverage"] == pytest.approx(0.95, abs=0.06)
    t = T0 + np.arange(20000.0)
    p = tmp_path / "gnssdo.csv"
    p.write_text("unix_time,offset\n" + "".join(f"{a:.1f},{b:.12e}\n" for a, b in zip(t, -x[:20000])))
    assert main(["holdover", str(p), "--limit", "1.1us", "--horizon", "2h", "--uncertainty", "5",
                 "--backtest", "5", "--min-holdover", "1h"]) == 0
    out = capsys.readouterr().out
    assert "may be exceeded after" in out and "backtest" in out and "[PASS]" in out
    assert main(["holdover", str(p), "--limit", "10ns", "--horizon", "6h", "--uncertainty", "0",
                 "--min-holdover", "6h", "--json"]) == 3
    doc = json.loads(capsys.readouterr().out)[0]
    assert doc["min_holdover_met"] is False and doc["limits"]["1e-08"]["envelope"] < 6 * 3600
