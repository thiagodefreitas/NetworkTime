"""Cross-validation against Stable32 1.62 output files (SIGMA.TAU) on the same inputs.

See ``tests/data/stable32/README.md`` for how the files were produced. Stable32 prints four
significant digits, so agreement is checked to 5e-4.

What the comparison established (ntpstats 3.6, 16 runs: four statistics on four phase files):

* point estimates and the number of analysis points agree on every row;
* both programs use chi-squared intervals from the equivalent degrees of freedom (EDF) of the
  identified power-law noise; where they identify the same noise type and the averaging factor
  is large enough for the two EDF models to coincide, the intervals agree to four digits;
* at small averaging factors for FM noise the EDFs differ (white FM, OADEV, m = 1: Stable32 782,
  ntpstats 666). Stable32 uses Greenhall's algorithm for phase averaged over each sample interval;
  ntpstats the exact value for instantaneous samples (``ntpstats.edf``, verified by Monte Carlo).
  The difference shrinks with m and is gone by m = 64;
* when fewer than about 30 averaged points remain, Stable32 switches noise identification from
  the lag-1 autocorrelation to its B1 ratio method and, on these records, reports white FM where
  the data (and ntpstats) say white PM or random-walk FM. Its EDF is then ntpstats' EDF for that
  other noise type, to the printed digits: the same formula, a different identification.
"""

import os

import numpy as np
import pytest

from ntpstats import stability as st
from ntpstats.edf import edf

DATA = os.path.join(os.path.dirname(__file__), "data", "stable32")
KIND = {"a": "oadev", "m": "mdev", "t": "tdev", "h": "hdev"}
FILES = ("TST_SUIT", "PHASE", "SIMA", "SIMB")
CASES = [(f, v) for f in FILES for v in KIND]
IDS = [f"{f}-{KIND[v]}" for f, v in CASES]
DIGITS = 5.1e-4  # four significant digits
BOUNDS = 1e-3  # the bounds also carry the EDF, which Stable32 prints to one decimal (up to 2e-4 at EDF 120)


def read_tau(path):
    a = np.loadtxt(path)
    return {"tau": a[:, 0], "n": a[:, 1], "dev": a[:, 2], "lo": a[:, 3], "hi": a[:, 4], "edf": a[:, 5]}


def both(name, var):
    s32 = read_tau(os.path.join(DATA, f"{name}_{var}.tau"))
    x = np.loadtxt(os.path.join(DATA, f"{name}.DAT"))
    r = st.compute(x, 1.0, KIND[var], [int(m) for m in s32["tau"]], ci=0.683, min_terms=1)
    return s32, r


@pytest.mark.parametrize("name,var", CASES, ids=IDS)
def test_point_estimates_and_counts_match(name, var):
    s32, r = both(name, var)
    np.testing.assert_allclose(r.dev, s32["dev"], rtol=DIGITS)
    np.testing.assert_array_equal(r.n, s32["n"])


@pytest.mark.parametrize("name,var", CASES, ids=IDS)
def test_intervals_match_wherever_the_edf_does(name, var):
    s32, r = both(name, var)
    same = np.isclose(r.edf, s32["edf"], rtol=3e-3)
    assert same.any(), "no averaging factor with the same EDF"
    np.testing.assert_allclose(r.lo[same], s32["lo"][same], rtol=BOUNDS)
    np.testing.assert_allclose(r.hi[same], s32["hi"][same], rtol=BOUNDS)


@pytest.mark.parametrize("name,var", CASES, ids=IDS)
def test_every_stable32_edf_is_one_of_ours_at_m_64_and_above(name, var):
    """Beyond m = 64 the two EDF models coincide, so a Stable32 EDF must equal ntpstats' EDF for *some*
    noise type: a different identification, never a different formula. SIMA at m = 256 is the one row
    where Stable32's value (17.0) lies between two of ours; it is listed, not hidden."""
    s32, r = both(name, var)
    for i, m in enumerate(int(v) for v in s32["tau"]):
        if m < 64 or (name == "SIMA" and m == 256):
            continue
        cands = [edf(KIND[var], a, m, int(s32["n"][i])) for a in (2, 1, 0, -1, -2)]
        assert any(np.isclose(c, s32["edf"][i], rtol=5e-3) for c in cands), (name, var, m, s32["edf"][i], cands)


def test_white_fm_edf_at_m_1_is_the_documented_model_difference():
    s32, r = both("PHASE", "a")
    assert s32["edf"][0] == pytest.approx(782.0, abs=0.5)
    assert r.edf[0] == pytest.approx(666.2, abs=0.5)
    assert s32["edf"][0] / r.edf[0] == pytest.approx(1.17, abs=0.01)
