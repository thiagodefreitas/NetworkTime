# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
import io
import os

import numpy as np
import pytest

from ntpstats.parsers import ParseError, detect_format, load, load_one
from ntpstats.series import mjd_to_unix

EX = os.path.join(os.path.dirname(__file__), os.pardir, "examples", "data")

# Line layouts copied from the ntpd 4.2.8 and chrony 4.x documentation.
LOOPSTATS = """\
50935 75440.031 0.000006019 13.778190 0.000351733 0.0133806 6
50935 75505.031 0.000005120 13.778200 0.000350000 0.0133000 6
50935 75570.031 -0.000001000 13.778210 0.000340000 0.0132000 6
garbage line
"""
PEERSTATS = """\
48773 10847.650 127.127.4.1 9714 -0.001605376 0.000000000 0.001424877 0.000958674
48773 10847.650 192.0.2.1 9414 0.002605376 0.010000000 0.001424877 0.000958674
48773 10911.650 127.127.4.1 9714 -0.001505376 0.000000000 0.001424877 0.000958674
48773 10975.650 127.127.4.1 9714 -0.001405376 0.000000000 0.001424877 0.000958674
"""
RAWSTATS = """\
50928 2132.543 128.4.1.1 128.4.1.20 3102453281.584327000 3102453281.586228000 3102453332.540806000 3102453332.541458000
"""
CHRONY_TRACKING = """\
====================================================================================================================
   Date (UTC) Time     IP Address   St   Freq ppm   Skew ppm     Offset L Co  Offset sd Rem. corr. Root delay Root disp. Max. error
====================================================================================================================
2017-08-22 13:22:36 203.0.113.15     2     -3.541      0.075 -8.621e-06 N  2  2.940e-06 -2.084e-07  1.534e-02  3.472e-04  8.304e-03
2017-08-22 13:23:40 203.0.113.15     2     -3.540      0.074 -4.000e-06 N  2  2.940e-06 -2.084e-07  1.534e-02  3.472e-04  8.304e-03
2017-08-22 13:24:44 203.0.113.15     2     -3.539      0.074  2.000e-06 N  2  2.940e-06 -2.084e-07  1.534e-02  3.472e-04  8.304e-03
"""
CHRONY_MEAS = """\
========================================================================================================================
   Date (UTC) Time     IP Address   L St 123 567 ABCD  LP RP Score    Offset  Peer del. Peer disp.  Root del. Root disp. Refid     MTxRx
========================================================================================================================
2016-11-09 05:40:50 203.0.113.15    N  2 111 111 1111  10 10 1.0  -4.966e-03  2.296e-01  1.577e-05  1.615e-01  7.446e-03 CB00717B 4B D K
2016-11-09 05:41:54 203.0.113.15    N  2 111 111 1111  10 10 1.0  -4.900e-03  2.290e-01  1.577e-05  1.615e-01  7.446e-03 CB00717B 4B D K
2016-11-09 05:41:55 198.51.100.1    N  1 111 111 1111  10 10 1.0   1.000e-04  2.000e-02  1.577e-05  1.615e-01  7.446e-03 47505300 4B D K
"""
CHRONY_STATS = """\
2016-08-10 05:40:50 203.0.113.15     6.261e-03 -3.247e-03  2.220e-03  1.874e-06  1.080e-06 7.8e-02  16   0   8  0.00
2016-08-10 05:41:54 203.0.113.15     6.261e-03 -3.100e-03  2.220e-03  1.874e-06  1.080e-06 7.8e-02  16   0   8  0.00
"""


def test_mjd_conversion():
    assert mjd_to_unix(40587, 0) == 0
    assert mjd_to_unix(55973, 789.37) == pytest.approx(1329350400 + 789.37)


@pytest.mark.parametrize("text,fmt", [
    (LOOPSTATS, "loopstats"), (PEERSTATS, "peerstats"), (RAWSTATS, "rawstats"),
    (CHRONY_TRACKING, "chrony-tracking"), (CHRONY_MEAS, "chrony-measurements"),
    (CHRONY_STATS, "chrony-statistics"), ("1,2\n3,4\n", "csv"),
    ("x INFO Logged: [off, 46.38, time, 1338047915.2]\n", "gsoc2012"),
])
def test_detect(text, fmt):
    assert detect_format(text.splitlines()) == fmt


def test_loopstats_columns_and_bad_lines():
    (s,) = load(LOOPSTATS)
    assert len(s) == 3 and s.meta["skipped_lines"] == 1
    assert s.offset[0] == pytest.approx(6.019e-6)
    assert s.extra["frequency_ppm"][0] == pytest.approx(13.77819)
    assert s.t[0] == pytest.approx(mjd_to_unix(50935, 75440.031))


def test_peerstats_split_and_sys_peer_selection():
    series = load(PEERSTATS)
    assert {s.meta["peer"] for s in series} == {"127.127.4.1", "192.0.2.1"}
    best = load_one(io.StringIO(PEERSTATS))
    assert best.meta["peer"] == "127.127.4.1" and best.meta["sys_peer_fraction"] == 1.0
    assert load_one(io.StringIO(PEERSTATS), peer="192.0.2").offset[0] == pytest.approx(0.002605376)
    with pytest.raises(ParseError):
        load_one(io.StringIO(PEERSTATS), peer="10.9.9.9")


def test_rawstats_offset_delay():
    (s,) = load(RAWSTATS)
    t1, t2, t3, t4 = 3102453281.584327, 3102453281.586228, 3102453332.540806, 3102453332.541458
    assert s.offset[0] == pytest.approx(((t2 - t1) + (t3 - t4)) / 2, abs=1e-6)
    assert s.extra["delay"][0] == pytest.approx((t4 - t1) - (t3 - t2), abs=1e-6)


def test_chrony_sign_is_normalised():
    (tr,) = load(CHRONY_TRACKING)
    assert tr.offset[0] == pytest.approx(8.621e-6)  # chrony -8.621e-06 -> ntpd convention
    assert tr.extra["frequency_ppm"][0] == pytest.approx(-3.541)
    assert tr.extra["max_error"][0] == pytest.approx(8.304e-3)
    meas = load(CHRONY_MEAS)
    by_peer = {s.meta["peer"]: s for s in meas}
    assert by_peer["203.0.113.15"].offset[0] == pytest.approx(4.966e-3)
    assert by_peer["203.0.113.15"].extra["delay"][0] == pytest.approx(0.2296)
    (st,) = load(CHRONY_STATS)
    assert st.offset[0] == pytest.approx(3.247e-3)


def test_csv_header_and_single_column():
    (s,) = load("unix_time,offset,delay\n10,0.001,0.02\n20,0.002,0.03\n5,0.0,0.01\n")
    assert list(s.t) == [5, 10, 20]  # sorted
    assert "delay" in s.extra
    with pytest.raises(ParseError):
        load("0.1\n0.2\n0.3\n")
    (s,) = load("0.1\n0.2\n0.3\n", tau0=16)
    assert list(s.t) == [0, 16, 32]


def test_same_simulated_peer_agrees_across_formats():
    pe = load_one(os.path.join(EX, "peerstats.example"), peer="192.0.2.10")
    ch = load_one(os.path.join(EX, "chrony-measurements.log"), peer="192.0.2.10")
    raw = load_one(os.path.join(EX, "rawstats.example"))
    n = len(raw)
    np.testing.assert_allclose(pe.offset, ch.offset, rtol=1e-3, atol=1e-6)  # chrony prints 4 significant digits
    np.testing.assert_allclose(pe.offset[:n], raw.offset, atol=2e-6)


def test_legacy_2012_files():
    (lp,) = load(os.path.join(EX, "loopstats.2012"))
    assert len(lp) == 52 and lp.source_format == "loopstats"
    (lg,) = load(os.path.join(EX, "estimators-2012.log"))
    assert lg.source_format == "gsoc2012" and len(lg) > 300


def test_unknown_mjd_log():
    with pytest.raises(ParseError):
        detect_format(["55973 789.370 127.127.20.0 $GPRMC,foo"])
