# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Stability estimators vs. textbook definitions, frozen independent reference
values and analytic power-law results. No third-party stability library is needed."""

import json
import os

import numpy as np
import pytest

from ntpstats import stability as st
from ntpstats.series import TimeSeries
from ntpstats.simulate import powerlaw_phase

DATA = os.path.join(os.path.dirname(__file__), "data")


# ---- straightforward reference implementations (NIST SP 1065 equations)
def naive_oadev(x, m, tau0):
    N = len(x)
    tau = m * tau0
    s = sum((x[i + 2 * m] - 2 * x[i + m] + x[i]) ** 2 for i in range(N - 2 * m))
    return np.sqrt(s / (2 * tau ** 2 * (N - 2 * m)))


def naive_mdev(x, m, tau0):
    N = len(x)
    tau = m * tau0
    tot = 0.0
    for j in range(N - 3 * m + 1):
        inner = sum(x[i + 2 * m] - 2 * x[i + m] + x[i] for i in range(j, j + m))
        tot += inner ** 2
    return np.sqrt(tot / (2 * m ** 2 * tau ** 2 * (N - 3 * m + 1)))


def naive_hdev(x, m, tau0):
    N = len(x)
    tau = m * tau0
    s = sum((x[i + 3 * m] - 3 * x[i + 2 * m] + 3 * x[i + m] - x[i]) ** 2 for i in range(N - 3 * m))
    return np.sqrt(s / (6 * tau ** 2 * (N - 3 * m)))


def naive_mtie(x, m):
    return max(max(x[i: i + m + 1]) - min(x[i: i + m + 1]) for i in range(len(x) - m))


@pytest.fixture(scope="module")
def phase():
    rng = np.random.default_rng(7)
    return np.cumsum(rng.normal(size=300)) * 1e-9 + rng.normal(size=300) * 3e-9


@pytest.mark.parametrize("m", [1, 2, 3, 5, 8, 13, 40])
def test_against_textbook_definitions(phase, m):
    tau0 = 2.5
    assert st.compute(phase, tau0, "oadev", [m], ci=None).dev[0] == pytest.approx(naive_oadev(phase, m, tau0), rel=1e-12)
    assert st.compute(phase, tau0, "mdev", [m], ci=None).dev[0] == pytest.approx(naive_mdev(phase, m, tau0), rel=1e-12)
    assert st.compute(phase, tau0, "tdev", [m], ci=None).dev[0] == pytest.approx(
        m * tau0 / np.sqrt(3) * naive_mdev(phase, m, tau0), rel=1e-12)
    assert st.compute(phase, tau0, "hdev", [m], ci=None).dev[0] == pytest.approx(naive_hdev(phase, m, tau0), rel=1e-12)
    assert st.compute(phase, tau0, "mtie", [m]).dev[0] == pytest.approx(naive_mtie(phase, m), rel=1e-12)


def test_non_overlapping_adev_is_decimated_oadev(phase):
    m, tau0 = 4, 1.0
    assert st.compute(phase, tau0, "adev", [m], ci=None).dev[0] == pytest.approx(
        naive_oadev(phase[::m], 1, m * tau0), rel=1e-12)


def test_frozen_independent_reference():
    """Values computed once with an independent implementation (allantools
    2024.06) and stored in tests/data, so the check needs no extra package."""
    ref = json.load(open(os.path.join(DATA, "reference_deviations.json")))
    x = np.loadtxt(os.path.join(DATA, "reference_phase.txt"))
    for kind, r in ref["results"].items():
        ours = st.compute(x, ref["tau0"], kind, ref["m"], ci=None)
        common = np.intersect1d(np.round(ours.taus, 6), np.round(r["taus"], 6))
        a = ours.dev[np.isin(np.round(ours.taus, 6), common)]
        b = np.array(r["dev"])[np.isin(np.round(r["taus"], 6), common)]
        assert len(common) >= 5, kind
        np.testing.assert_allclose(a, b, rtol=1e-9, err_msg=kind)


@pytest.mark.parametrize("alpha,kind,slope", [
    (2, "oadev", -1.0),    # white PM
    (0, "oadev", -0.5),    # white FM
    (-2, "oadev", 0.5),    # random-walk FM
    (2, "mdev", -1.5),     # MDEV separates white PM ...
    (1, "mdev", -1.0),     # ... from flicker PM
    (0, "tdev", 0.5),      # TDEV of white FM
])
def test_power_law_slopes(alpha, kind, slope):
    x = powerlaw_phase(2 ** 15, alpha, 1.0, rng=42)
    r = st.compute(x, 1.0, kind, [4, 8, 16, 32, 64, 128], ci=None)
    fit = np.polyfit(np.log10(r.taus), np.log10(r.dev), 1)[0]
    assert fit == pytest.approx(slope, abs=0.12)


@pytest.mark.parametrize("alpha", [2, 1, 0, -1, -2])
def test_noise_identification(alpha):
    x = powerlaw_phase(2 ** 14, alpha, 1.0, rng=alpha + 10)
    assert st.noise_alpha(x, 1) == alpha
    assert st.noise_alpha(x, 8) == alpha


def test_confidence_interval_covers_truth():
    # White FM with ADEV(tau) = 1/sqrt(tau): count coverage over many realisations.
    hits, trials = 0, 200
    for seed in range(trials):
        x = powerlaw_phase(512, 0, 1.0, rng=seed)
        r = st.compute(x, 1.0, "oadev", [4], ci=0.683)
        true = 1.0 / np.sqrt(4.0)
        hits += r.lo[0] <= true <= r.hi[0]
    assert 0.55 < hits / trials < 0.85  # nominal 68.3 %


def test_gaps_are_not_bridged():
    t = np.concatenate([np.arange(0, 500.0), np.arange(900.0, 1400.0)])
    x = np.random.default_rng(0).normal(size=t.size) * 1e-6
    s = TimeSeries(t, x)
    grid, xg, tau0 = s.to_uniform()
    assert tau0 == 1.0
    assert np.isnan(xg).sum() == 400  # grid points 500..899 lie strictly inside the gap
    (r,) = st.series_stability(s, kinds=("oadev",))
    full = st.compute(np.concatenate([x[:500], x[500:]]), 1.0, "oadev", [1], ci=None)
    # With the gap respected the m=1 estimate uses fewer terms than the naive concat.
    assert r.n[0] < full.n[0]
    assert np.all(np.isfinite(r.dev))


def test_tau_grids():
    assert list(st.tau_multipliers(100, "octave")) == [1, 2, 4, 8, 16, 32]
    assert list(st.tau_multipliers(100, "decade")) == [1, 2, 5, 10, 20]
    assert list(st.tau_multipliers(20, "all"))[-1] == 9
    assert list(st.tau_multipliers(100, [3, 1, 3])) == [1, 3]
    with pytest.raises(ValueError):
        st.tau_multipliers(100, "weird")


def test_invalid_kind():
    with pytest.raises(ValueError):
        st.compute(np.zeros(10), 1.0, "nope")


# ---- 2.1 estimators
def naive_totdev(x, m, tau0):
    N = len(x)
    ext = {i: x[i] for i in range(N)}
    for j in range(1, N - 1):
        ext[-j] = 2 * x[0] - x[j]
        ext[N - 1 + j] = 2 * x[N - 1] - x[N - 1 - j]
    s = sum((ext[i - m] - 2 * ext[i] + ext[i + m]) ** 2 for i in range(1, N - 1))
    return np.sqrt(s / (2 * (m * tau0) ** 2 * (N - 2)))


def naive_theo1(x, m, tau0):
    N = len(x)
    h = m // 2
    s = 0.0
    for i in range(N - m):
        for d in range(h):
            s += ((x[i] - x[i - d + h]) + (x[i + m] - x[i + d + h])) ** 2 / (h - d)
    return np.sqrt(s / (0.75 * (N - m) * (m * tau0) ** 2))


@pytest.mark.parametrize("m", [1, 2, 5, 16, 60])
def test_totdev_textbook(phase, m):
    assert st.compute(phase, 2.0, "totdev", [m], ci=None).dev[0] == pytest.approx(naive_totdev(phase, m, 2.0), rel=1e-12)


@pytest.mark.parametrize("m", [2, 4, 10, 64])
def test_theo1_textbook(phase, m):
    r = st.compute(phase, 2.0, "theo1", [m], ci=None)
    assert r.taus[0] == pytest.approx(0.75 * m * 2.0)
    assert r.dev[0] == pytest.approx(naive_theo1(phase, m, 2.0), rel=1e-12)


def test_theo1_unbiased_for_white_fm():
    x = powerlaw_phase(1 << 14, 0, 1.0, rng=8)
    r = st.compute(x, 1.0, "theo1", [16, 64, 256], ci=None)
    np.testing.assert_allclose(r.dev, 1 / np.sqrt(r.taus), rtol=0.1)


def test_tierms_random_walk():
    x = powerlaw_phase(1 << 14, 0, 1.0, rng=9)
    r = st.compute(x, 1.0, "tierms", [1, 16, 64], ci=None)
    np.testing.assert_allclose(r.dev, np.sqrt([1, 16, 64]), rtol=0.1)


def test_dynamic_detects_change():
    rng = np.random.default_rng(1)
    x = np.concatenate([rng.normal(0, 1e-6, 4000), rng.normal(0, 1e-5, 4000)])
    s = TimeSeries(np.arange(x.size, dtype=float), x)
    d = st.dynamic(s, "oadev", window=1000, step=500)
    assert d.dev.shape[0] == 15
    assert np.nanmean(d.dev[-3:, 0]) > 5 * np.nanmean(d.dev[:3, 0])


def test_mask_check():
    from ntpstats.masks import check, load_mask

    m = load_mask("# tau limit\ntau,limit\n1,1e-6\n100,1e-8\n")
    assert m.limit_at(np.array([10.0]))[0] == pytest.approx(1e-7)
    assert np.isnan(m.limit_at(np.array([1000.0]))[0])
    x = powerlaw_phase(4096, 2, 1e-6, rng=2)  # white PM: ADEV(1 s) ~ 1.7e-6 > 1e-6
    r = st.compute(x, 1.0, "oadev", "octave")
    c = check(r, m)
    assert c["passed"] is False and c["used_upper_bound"]
    c2 = check(r, load_mask("1,1\n1000,1\n"))
    assert c2["passed"] is True
