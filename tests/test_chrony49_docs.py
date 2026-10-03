"""chrony log formats checked against the example lines of the chrony 4.9 documentation (chrony.conf(5), log)."""

import pytest

from ntpstats.parsers import load_one

# Each example "actually appears as a single line in the file" (chrony.conf(5)); joined here.
MEASUREMENTS = ("2016-11-09 05:40:50 203.0.113.15    N  2 111 111 1111  10 10 1.0 "
                "-4.966e-03  2.296e-01  1.577e-05  1.615e-01  7.446e-03 CB00717B 4B D K")
TRACKING = ("2017-08-22 13:22:36 203.0.113.15     2     -3.541      0.075 -8.621e-06 N "
            "2  2.940e-03 -2.084e-04  1.534e-02  3.472e-04  8.304e-03")
STATISTICS = ("2016-08-10 05:40:50 203.0.113.15     6.261e-03 -3.247e-03 "
              "2.220e-03  1.874e-06  1.080e-06 7.8e-02  16   0   8  0.00")


def _write(tmp_path, name, line):
    p = tmp_path / name
    p.write_text(line + "\n")
    return str(p)


def test_measurements_example_line(tmp_path):
    path = _write(tmp_path, "measurements.log", MEASUREMENTS)
    s = load_one(path)
    assert s.source_format == "chrony-measurements"
    # "the estimated local clock error (theta in RFC 5905). Positive indicates that the local clock is slow"
    assert s.offset[0] == pytest.approx(-4.966e-03)
    assert s.extra["delay"][0] == pytest.approx(2.296e-01)
    assert s.extra["root_delay"][0] == pytest.approx(1.615e-01)
    assert s.meta["peer"] == "203.0.113.15"
    # "4B D K": basic (not interleaved) server response, daemon transmit and kernel receive timestamps
    assert (s.extra["interleaved"][0], s.extra["tx_timestamp"][0], s.extra["rx_timestamp"][0]) == (0, 0, 1)
    assert s.meta["timestamping"].startswith("hardware both ways 0%")


def test_tracking_example_line(tmp_path):
    path = _write(tmp_path, "tracking.log", TRACKING)
    s = load_one(path)
    assert s.source_format == "chrony-tracking"
    # "positive indicates the clock is fast of UTC": negated to reference - local
    assert s.offset[0] == pytest.approx(8.621e-06)
    assert s.extra["frequency_ppm"][0] == pytest.approx(-3.541)
    assert s.extra["root_delay"][0] == pytest.approx(1.534e-02)
    assert s.extra["max_error"][0] == pytest.approx(8.304e-03)


def test_statistics_example_line(tmp_path):
    path = _write(tmp_path, "statistics.log", STATISTICS)
    s = load_one(path)
    assert s.source_format == "chrony-statistics"
    # "estimated offset of the source (positive means the local clock is estimated to be fast)": negated
    assert s.offset[0] == pytest.approx(3.247e-03)
    assert s.extra["std_dev"][0] == pytest.approx(6.261e-03)
