# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Stable32 data files and the allantools-compatible API (issue #33)."""

import io
import json
import os

import numpy as np
import pytest
from test_reference_nist import NBS9, TABLE31, nist1000, to_phase

from ntpstats import parsers
from ntpstats import stability as st
from ntpstats.compat import allantools as at
from ntpstats.interop import read_stable32, write_stable32
from ntpstats.series import TimeSeries

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_stable32_frequency_file_with_header_and_comments():
    text = "NBS Monograph 140 Annex 8.E\n# comment\n" + "\n".join(str(v) for v in NBS9) + "\n"
    s = read_stable32(text, data_type="freq", tau0=1.0)
    assert len(s) == 10 and s.offset[0] == 0.0
    r = st.compute(s.offset, 1.0, "adev", [1, 2], ci=None, min_terms=1)
    np.testing.assert_allclose(r.dev, [91.22945, 115.8082], rtol=5e-7)


def test_stable32_mjd_timetags_and_column_choice():
    mjd = 60000 + np.arange(5) / 86400.0
    text = "".join(f"{m:.10f}, {7.0 + i}, {i * 1e-9:.3e}\n" for i, m in enumerate(mjd))
    s = read_stable32(text)  # last column, MJD timetags
    np.testing.assert_allclose(np.diff(s.t), 1.0, atol=1e-5)
    np.testing.assert_allclose(s.offset, np.arange(5) * 1e-9)
    s2 = read_stable32(text, column=1)
    np.testing.assert_allclose(s2.offset, 7.0 + np.arange(5))


def test_stable32_zero_frequency_is_a_gap():
    y = [1e-9, 2e-9, 0.0, 1e-9, 2e-9]
    s = read_stable32("\n".join(map(str, y)) + "\n", data_type="freq", tau0=10.0)
    assert np.isnan(s.offset[3]) and np.isfinite(s.offset[4])


def test_stable32_needs_tau0_without_timetags():
    with pytest.raises(ValueError):
        read_stable32("1e-9\n2e-9\n")


@pytest.mark.parametrize("data_type", ["phase", "freq"])
def test_stable32_round_trip(tmp_path, data_type):
    rng = np.random.default_rng(3)
    t = 1.7e9 + np.arange(200) * 16.0
    s = TimeSeries(t=t, offset=np.cumsum(rng.normal(0, 1e-9, t.size)), name="x")
    path = tmp_path / f"x.{data_type}"
    rows = write_stable32(s, path, data_type=data_type)
    back = read_stable32(str(path), data_type=data_type)
    assert rows == (200 if data_type == "phase" else 199)
    a = st.compute(s.offset, 16.0, "oadev", [1, 4, 16], ci=None).dev
    b = st.compute(back.offset, 16.0, "oadev", [1, 4, 16], ci=None).dev
    np.testing.assert_allclose(a, b, rtol=1e-9)
    np.testing.assert_allclose(back.t[0], t[0], atol=1e-4)


def test_stable32_write_marks_phase_gap_by_missing_timetag():
    t = np.concatenate((np.arange(10), np.arange(20, 30))) * 1.0 + 1.7e9
    s = TimeSeries(t=t, offset=np.arange(20) * 1e-9, name="gappy")
    buf = io.StringIO()
    write_stable32(s, buf, max_gap=2.0)
    assert len(buf.getvalue().splitlines()) == 20
    with pytest.raises(ValueError):
        write_stable32(s, io.StringIO(), timetags=False, max_gap=2.0)


def test_loader_formats(tmp_path):
    p = tmp_path / "nbs.dat"
    p.write_text("\n".join(str(v) for v in NBS9) + "\n")
    s = parsers.load(str(p), fmt="stable32-freq", tau0=1.0)[0]
    assert s.source_format == "stable32-freq" and len(s) == 10
    with pytest.raises(parsers.ParseError):
        parsers.load(str(p), fmt="stable32-phase")  # no timetags, no tau0


# ---------------------------------------------------------------- allantools API
def test_allantools_api_shapes_and_frequency_input():
    y = nist1000()
    taus, devs, errs, ns = at.oadev(y, rate=1.0, data_type="freq", taus=[1, 10, 100])
    np.testing.assert_allclose(taus, [1, 10, 100])
    np.testing.assert_allclose(devs, TABLE31["oadev"], rtol=5e-7)
    np.testing.assert_allclose(errs, devs / np.sqrt(ns))
    assert at.adev(y, data_type="freq")[0][0] == 1.0  # default octave grid


def test_allantools_non_overlapping_hadamard_matches_sp1065():
    # SP 1065 tables 30/31 "Hadamard Deviation" (non-overlapping)
    _, d9, _, _ = at.hdev(np.array(NBS9, float), data_type="freq", taus=[1, 2])
    np.testing.assert_allclose(d9, [70.80607, 116.7980], rtol=5e-7)
    _, d, _, _ = at.hdev(to_phase(nist1000()), taus=[1, 10, 100])
    np.testing.assert_allclose(d, [2.943883e-01, 1.052754e-01, 3.910861e-02], rtol=5e-7)


def test_allantools_mtotdev_is_raw():
    x = to_phase(nist1000())
    _, d, _, _ = at.mtotdev(x, taus=[10])
    assert d[0] == pytest.approx(TABLE31["mtot"][1] * np.sqrt(0.73), rel=5e-7)


def test_allantools_api_matches_frozen_allantools_values():
    ref = json.load(open(os.path.join(DATA, "reference_deviations.json")))
    x = np.loadtxt(os.path.join(DATA, "reference_phase.txt"))
    rate = 1.0 / ref["tau0"]
    fns = {"adev": at.adev, "oadev": at.oadev, "mdev": at.mdev, "tdev": at.tdev, "hdev": at.ohdev, "mtie": at.mtie}
    for kind, r in ref["results"].items():
        taus, devs, _, _ = fns[kind](x, rate=rate, taus=np.array(r["taus"]))
        common = np.isin(np.round(r["taus"], 6), np.round(taus, 6))
        np.testing.assert_allclose(devs, np.array(r["dev"])[common], rtol=1e-9, err_msg=kind)


def test_allantools_htotdev_not_implemented():
    with pytest.raises(NotImplementedError):
        at.htotdev([0.0, 1.0, 2.0])
