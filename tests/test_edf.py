# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""EDF validated against Monte Carlo and closed forms."""

import numpy as np
import pytest

from ntpstats import stability as st
from ntpstats.edf import edf
from ntpstats.simulate import powerlaw_phase


def test_white_fm_closed_form():
    # OADEV, m=1, white FM: second differences are an MA(1) with rho=-1/2 -> EDF = 2n/3.
    assert edf("oadev", 0, 1, 510) == pytest.approx(2 * 510 / 3, rel=2e-3)


def test_white_pm_nonoverlapping_is_terms_scaled():
    # ADEV white PM: terms at stride m are 2-dependent with rho1=-2/3, rho2=1/6.
    M = 100
    expected = M * M / (M + 2 * ((M - 1) * (2 / 3) ** 2 + (M - 2) * (1 / 6) ** 2))
    assert edf("adev", 2, 4, M) == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("kind", ["oadev", "mdev", "hdev"])
@pytest.mark.parametrize("alpha", [2, 0, -1, -2])
def test_edf_matches_monte_carlo(kind, alpha):
    N, m, R = 256, 4, 500
    v = []
    for r in range(R):
        x = powerlaw_phase(4 * N, alpha, 1.0, rng=1000 * (alpha + 3) + r)[-N:]
        res = st.compute(x, 1.0, kind, [m], ci=None)
        v.append(res.dev[0] ** 2)
        n = int(res.n[0])
    v = np.array(v)
    mc = 2 * v.mean() ** 2 / v.var()
    # 500 realisations: sampling error of the MC EDF is roughly +-10 %
    assert edf(kind, alpha, m, n) == pytest.approx(mc, rel=0.2)


def test_ci_coverage_mdev_flicker_fm():
    hits, trials = 0, 150
    # "true" MDEV from one very long realisation
    ref = st.compute(powerlaw_phase(1 << 17, -1, 1.0, rng=5), 1.0, "mdev", [8], ci=None).dev[0]
    for seed in range(trials):
        x = powerlaw_phase(2048, -1, 1.0, rng=seed + 77)[-512:]
        r = st.compute(x, 1.0, "mdev", [8], ci=0.683)
        hits += r.lo[0] <= ref <= r.hi[0]
    assert 0.5 < hits / trials < 0.9


def _sp1065_avar_edf(alpha, N, m):
    """NIST SP 1065 Table 5: the approximate overlapping-AVAR EDF formulas (Stable32's simple method)."""
    if alpha == 2:
        return (N + 1) * (N - 2 * m) / (2 * (N - m))
    if alpha == 1:
        return np.exp(np.sqrt(np.log((N - 1) / (2 * m)) * np.log((2 * m + 1) * (N - 1) / 4)))
    if alpha == 0:
        return (3 * (N - 1) / (2 * m) - 2 * (N - 2) / N) * 4 * m * m / (4 * m * m + 5)
    if alpha == -1:
        return 2 * (N - 2) ** 2 / (2.3 * N - 4.9) if m == 1 else 5 * N * N / (4 * m * (N + 3 * m))
    return (N - 2) / m * ((N - 1) ** 2 - 3 * m * (N - 1) + 4 * m * m) / (N - 3) ** 2


@pytest.mark.parametrize("alpha,tol", [(2, 0.05), (1, 0.2), (0, 0.05), (-1, 0.1), (-2, 0.1)])
def test_exact_edf_agrees_with_sp1065_approximations(alpha, tol):
    """#28: the exact discrete EDF stays within the accuracy of SP 1065's published approximations."""
    from ntpstats.edf import edf

    N = 1025
    for m in (1, 2, 4, 8, 16, 32, 64):
        assert edf("oadev", alpha, m, N - 2 * m) == pytest.approx(_sp1065_avar_edf(alpha, N, m), rel=tol)
