"""u-blox UBX timing messages and the PPS sawtooth correction."""

import numpy as np
import pytest
from ubx_util import gps_week_tow, nav_clock, nav_timeutc, tim_tp, unix

from ntpstats.parsers import load
from ntpstats.series import TimeSeries
from ntpstats.ubx import apply_qerr, frames, is_ubx, parse_ubx

T0 = unix(2026, 9, 21, 12, 0, 0)


def _log(n=60, nmea=True):
    out = b""
    for k in range(n):
        t = T0 + k
        _, tow = gps_week_tow(t)
        itow = int(round(tow * 1000))
        out += nav_clock(itow, clkb_ns=12.5 + 0.1 * k, clkd_ns_s=270, tacc_ns=5, facc_ps_s=60)
        if nmea:
            out += b"$GNRMC,120000.00,A,4807.038,N,01131.000,E,0.0,0.0,210926,,,A*55\r\n"
        out += nav_timeutc(itow, t)
        out += tim_tp(t + 1, qerr_ps=1000 * ((k * 2.16) % 8 - 4))
    return out


def test_frames_checksums_and_noise():
    data = b"junk\xb5\x62\x01" + _log(3) + b"\xb5\x62\x01\x22\x14\x00broken"
    assert sum(1 for _ in frames(data)) == 9
    assert is_ubx(data) and not is_ubx(b"$GNRMC,just,nmea\r\n")


def test_parse_clock_and_qerr():
    clock, tp = parse_ubx(_log(), "rx.ubx")
    assert clock.meta["message"] == "UBX-NAV-CLOCK" and clock.meta["timing"] == "NAV-TIMEUTC"
    assert clock.t[0] == pytest.approx(T0) and len(clock) == 60
    assert clock.offset[0] == pytest.approx(12e-9, abs=1e-12)  # clkB is an integer number of ns
    assert clock.extra["clock_drift"][0] == pytest.approx(270e-9)
    assert clock.extra["time_accuracy"][0] == pytest.approx(5e-9)
    assert clock.extra["freq_accuracy"][0] == pytest.approx(60e-12)
    assert tp.meta["message"] == "UBX-TIM-TP"
    assert tp.t[0] == pytest.approx(T0 + 1, abs=1e-6)  # GPS time base converted to UTC
    assert tp.offset[1] == pytest.approx(1e-12 * round(1000 * (2.16 % 8 - 4)))


def test_timing_without_timeutc_uses_the_tim_tp_week():
    data = b"".join(nav_clock(int(round(gps_week_tow(T0 + k)[1] * 1000)), 10, 270) + tim_tp(T0 + k + 1, 0)
                    for k in range(5))
    clock, _ = parse_ubx(data)
    assert clock.meta["timing"].startswith("GPS week") and clock.t[0] == pytest.approx(T0)


def test_utc_time_base_pulses():
    (tp,) = parse_ubx(tim_tp(T0, 500, utc_base=True) + tim_tp(T0 + 1, 400, utc_base=True))
    assert tp.t[0] == pytest.approx(T0, abs=1e-6)


def test_load_detects_ubx_files_and_bytes(tmp_path):
    p = tmp_path / "receiver.ubx"
    p.write_bytes(_log(10))
    assert [s.source_format for s in load(str(p))] == ["ubx", "ubx"]
    assert len(load(_log(10))) == 2


@pytest.mark.parametrize("truth_sign", [1, -1])
def test_apply_qerr_removes_the_sawtooth(truth_sign):
    rng = np.random.default_rng(3)
    n = 600
    t = T0 + np.arange(n, dtype=float)
    saw = ((np.arange(n) * 0.27 * 8 / 8) % 1 - 0.5) * 8e-9  # 8 ns quantization sawtooth
    qerr = TimeSeries(t + 0.001, -truth_sign * saw + rng.normal(0, 50e-12, n))
    pps = TimeSeries(t, saw + rng.normal(0, 0.3e-9, n) + 1e-9 * np.sin(np.arange(n) / 200))
    out = apply_qerr(pps, qerr)
    assert out.meta["qerr_sign"] == truth_sign and out.meta["matched"] == n
    assert out.meta["diff_rms_after"] < 0.25 * out.meta["diff_rms_before"]
    assert np.std(out.offset - 1e-9 * np.sin(np.arange(n) / 200)) < 0.5e-9
    fixed = apply_qerr(pps, qerr, sign=-truth_sign)
    assert fixed.meta["sign_choice"] == "given" and fixed.meta["diff_rms_after"] > out.meta["diff_rms_after"]


def test_apply_qerr_needs_overlap():
    with pytest.raises(ValueError, match="same period"):
        apply_qerr(TimeSeries(T0 + np.arange(10.0), np.zeros(10)), TimeSeries(T0 + 1e5 + np.arange(10.0), np.zeros(10)))
