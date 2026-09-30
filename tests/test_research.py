# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Research data sources (#34): CGGTTS, RINEX clock, Circular T, RIPE Atlas, NTP Pool."""

import gzip

import numpy as np
import pytest
from research_util import cggtts_pair, circular_t, ntppool, rinex_clock, ripe_atlas

from ntpstats import research
from ntpstats.cli import main
from ntpstats.parsers import detect_format, load, load_one


def test_cggtts_refsys_series_and_checksums():
    a, _, _ = cggtts_pair()
    assert detect_format(a.splitlines()) == "cggtts"
    (s,) = load(a)
    assert s.source_format == "cggtts" and len(s) == 40 and s.meta["lab"] == "LABA"
    assert s.extra["satellites"][0] == 4 and s.meta["bad_checksums"] == 0
    assert s.offset[0] == pytest.approx(-48e-9, abs=1e-9)
    assert np.all(np.diff(s.t) == 960)  # 16-minute schedule, stamped at the track midpoint
    bad = a.replace("G05 FF", "G06 FF", 1)  # corrupt one line: its checksum no longer matches
    tr = research.cggtts_tracks(bad.splitlines())
    assert tr["bad_checksums"] == 1


@pytest.mark.parametrize("mode", ["cv", "aiv"])
def test_common_view_recovers_lab_difference(mode):
    a, b, truth = cggtts_pair()
    s = research.common_view(a.splitlines(), b.splitlines(), mode=mode)
    assert len(s) == 40 and s.meta["quantity"] == "REF(LABA) - REF(LABB)"
    assert np.allclose(s.offset, truth, atol=0.8e-9 if mode == "cv" else 2.5e-9)
    assert np.mean(s.offset - truth) == pytest.approx(0, abs=0.3e-9)
    if mode == "cv":
        assert s.extra["satellites"][0] == 4


def test_cv_cli(tmp_path, capsys):
    a, b, truth = cggtts_pair()
    pa, pb = tmp_path / "a.cggtts", tmp_path / "b.cggtts.gz"
    pa.write_text(a)
    with gzip.open(pb, "wt") as fh:
        fh.write(b)
    out = tmp_path / "ab.csv"
    assert main(["cv", str(pa), str(pb), "-o", str(out)]) == 0
    s = load_one(str(out))
    assert np.allclose(s.offset, truth, atol=0.8e-9)
    assert main(["stability", str(out), "-k", "tdev"]) == 0


def test_rinex_clock(tmp_path):
    text = rinex_clock()
    assert detect_format(text.splitlines()) == "rinex-clock"
    p = tmp_path / "x.clk.gz"
    with gzip.open(p, "wt") as fh:  # IGS products are distributed gzipped
        fh.write(text)
    ss = load(str(p))
    names = {s.meta["peer"]: s for s in ss}
    assert set(names) == {"LABA", "G01"} and names["G01"].meta["clock_type"] == "satellite"
    r = names["LABA"]
    assert len(r) == 48 and r.offset[1] - r.offset[0] == pytest.approx(1e-12)
    assert r.t[1] - r.t[0] == 300 and r.meta["time_scale"] == "GPS"


def test_circular_t_concatenated_issues():
    labs = [("LABA", "Somewhere", lambda m: 0.1 * (m - 61000)), ("LABB", "Elsewhere", lambda m: None if m == 61005 else -3.0)]
    text = circular_t(500, 61000, labs) + circular_t(501, 61030, labs)
    assert detect_format(text.splitlines()) == "circular-t"
    ss = {s.meta["lab"]: s for s in load(text)}
    a = ss["LABA"]
    assert len(a) == 12 and a.meta["issues"] == 2 and a.meta["u"] == pytest.approx(2e-9)
    assert a.offset[3] == pytest.approx(1.5e-9) and a.t[1] - a.t[0] == 5 * 86400
    assert len(ss["LABB"]) == 11  # "-" is a missing value


def test_ripe_atlas_and_group_summary():
    text = ripe_atlas() + "\n"
    assert detect_format(text.splitlines()) == "ripe-atlas"
    ss = load(text)
    assert len(ss) == 2 and {s.meta["probe"] for s in ss} == {1001, 1002}
    s = ss[0]
    assert s.offset[0] == pytest.approx(0.0015)  # Atlas reports local - server; ntpstats uses server - local
    assert s.extra["delay"][0] == pytest.approx(0.02) and s.t[0] == pytest.approx(1_790_000_000.02)
    g = research.group_summary(ss, by="peer")
    assert g[0]["peer"] == "192.0.2.123" and g[0]["series"] == 2 and g[0]["samples"] == 30


def test_ntppool_monitors():
    text = ntppool()
    assert detect_format(text.splitlines()) == "ntppool"
    ss = {s.meta["monitor"]: s for s in load(text)}
    assert set(ss) == {"mon-a", "mon-b"} and len(ss["mon-a"]) == 10  # the error row has no offset
    assert ss["mon-a"].extra["delay"][0] == pytest.approx(0.0125)
