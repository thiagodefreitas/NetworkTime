# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
import sys

import pytest

from ntpstats import sources
from ntpstats.parsers import load_one

TRACKING = "A29FC87B,162.159.200.123,4,1727605862.123456789,0.000012345,-0.000001234,0.000023456,-12.345,-0.001,0.050,0.012345678,0.000456789,64.4,Normal\n"
SOURCESTATS = "192.0.2.10,20,11,1234,-0.012,0.034,+0.000004321,0.000012000\nbad,row\n"
NTPQ_RV = """associd=0 status=0615 leap_none, sync_ntp, 1 event, clock_sync,
version="ntpd 4.2.8p18@1.4062-o", processor="x86_64", system="Linux/6.1.0",
leap=00, stratum=2, precision=-24, rootdelay=12.345, rootdisp=3.210,
refid=192.0.2.1, reftime=ea1b2c3d.12345678  Tue, Sep 29 2026 10:00:00.071,
clock=ea1b2c40.00000000  Tue, Sep 29 2026 10:00:03.000, peer=12345, tc=6,
mintc=3, offset=-0.123456, frequency=-12.345, sys_jitter=0.045678,
clk_jitter=0.012, clk_wander=0.003
"""


def test_parse_chronyc_tracking_signs():
    d = sources.parse_chronyc_tracking(TRACKING)
    assert d["offset"] == pytest.approx(1.2345e-5)  # System time, positive = local slow
    assert d["last_offset"] == pytest.approx(1.234e-6)  # negated (positive = local fast in chrony)
    assert d["frequency_ppm"] == pytest.approx(-12.345) and d["leap"] == "Normal"
    assert d["root_delay"] == pytest.approx(0.012345678)


def test_parse_chronyc_sourcestats():
    (s,) = sources.parse_chronyc_sourcestats(SOURCESTATS)
    assert s["name"] == "192.0.2.10" and s["offset"] == pytest.approx(-4.321e-6)


def test_parse_ntpq_rv_units():
    d = sources.parse_ntpq_rv(NTPQ_RV)
    assert d["offset"] == pytest.approx(-0.123456e-3)  # ms -> s, ntpd convention kept
    assert d["frequency_ppm"] == pytest.approx(-12.345)
    assert d["rootdelay"] == pytest.approx(12.345e-3) and d["refid"] == "192.0.2.1"
    with pytest.raises(sources.SourceError):
        sources.parse_ntpq_rv("associd=0 status=0615")


def test_local_watch_with_fake_chronyc(tmp_path):
    fake = tmp_path / "chronyc.py"
    fake.write_text(f"import sys\nassert sys.argv[1:] == ['-c', 'tracking']\nprint({TRACKING!r}, end='')\n")
    out = tmp_path / "watch.csv"
    got = []
    w = sources.LocalWatch("chrony", interval=0.01, out_path=str(out), on_sample=got.append,
                           count=3, cmd=[sys.executable, str(fake)])
    w.run()
    assert len(got) == 3
    s = load_one(str(out))
    assert len(s) == 3 and s.offset[0] == pytest.approx(1.2345e-5) and "frequency_ppm" in s.extra


def test_missing_binary_is_reported():
    errs = []
    w = sources.LocalWatch("ntpd", interval=0.01, count=1, cmd=["definitely-not-ntpq-xyz"],
                           on_error=lambda src, e: errs.append(e))
    w.run()
    assert errs and "not found" in str(errs[0])
