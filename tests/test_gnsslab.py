"""gpsd JSON (PPS/TOFF, live) and TAPR TICC output."""

import json
import socket
import threading

import numpy as np
import pytest

from ntpstats.cli import main
from ntpstats.gnsslab import parse_gpsd, parse_ticc, sample_gpsd
from ntpstats.parsers import load
from ntpstats.sources import LocalWatch

T0 = 1_790_000_000


def _pps(k, err_ns, qerr_ps=None, dev="/dev/ttyACM0", cls="PPS"):
    """gpsd PPS/TOFF: the system clock time-stamps the edge ``err_ns`` late (so GNSS - clock = -err)."""
    o = {"class": cls, "device": dev, "real_sec": T0 + k, "real_nsec": 0, "clock_sec": T0 + k,
         "clock_nsec": err_ns, "precision": -20, "shm": "NTP2"}
    if err_ns < 0:
        o["clock_sec"], o["clock_nsec"] = T0 + k - 1, 1_000_000_000 + err_ns
    if qerr_ps is not None:
        o["qErr"] = qerr_ps
    return json.dumps(o)


def _gpsd_log(n=200, saw_ns=4):
    lines = ['{"class":"VERSION","release":"3.25","rev":"3.25","proto_major":3,"proto_minor":15}']
    for k in range(n):
        saw = ((k * 0.37) % 1 - 0.5) * 2 * saw_ns
        lines.append(_pps(k, int(round(1500 + saw)), qerr_ps=-saw * 1000))
        lines.append(_pps(k, 120_000_000 + 1000 * k, cls="TOFF"))
        lines.append('{"class":"TPV","device":"/dev/ttyACM0","mode":3,"time":"2026-09-21T14:13:20.000Z"}')
    return lines


def test_gpsd_pps_and_toff():
    pps, toff = parse_gpsd(_gpsd_log())
    assert pps.meta["message"] == "PPS" and toff.meta["message"] == "TOFF"
    assert pps.source_format == "gpsd" and pps.meta["device"] == "/dev/ttyACM0"
    assert np.median(pps.offset) == pytest.approx(-1.5e-6, abs=5e-9)  # the clock is late: GNSS - clock < 0
    assert toff.offset[0] == pytest.approx(-0.12)
    assert "qerr" in pps.extra and pps.extra["precision"][0] == -20
    neg = parse_gpsd([_pps(0, -800)])[0]
    assert neg.offset[0] == pytest.approx(800e-9)  # clock ahead of the edge, across the second boundary


def test_gpsd_detected_and_sawtooth_from_its_own_qerr(tmp_path, capsys):
    p = tmp_path / "gpspipe.json"
    p.write_text("\n".join(_gpsd_log()) + "\n")
    assert [s.source_format for s in load(str(p))] == ["gpsd", "gpsd"]
    assert main(["sawtooth", str(p), "--peer", "PPS"]) == 0
    out = capsys.readouterr().out
    assert "paired with qErr" in out and "sign" in out


@pytest.fixture
def fake_gpsd():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    got = []

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with c:
                c.sendall(b'{"class":"VERSION","release":"3.25"}\n')
                got.append(c.recv(1024))
                c.sendall((_pps(0, 120_000_000, cls="TOFF") + "\n").encode())
                c.sendall((_pps(1, 2500, qerr_ps=-1200) + "\n").encode())

    threading.Thread(target=serve, daemon=True).start()
    yield f"127.0.0.1:{srv.getsockname()[1]}", got
    srv.close()


def test_live_gpsd_sample_and_watch(fake_gpsd, tmp_path):
    addr, got = fake_gpsd
    d = sample_gpsd([addr])
    assert d["source"] == "PPS" and d["offset"] == pytest.approx(-2.5e-6) and d["qerr"] == pytest.approx(-1.2e-9)
    assert b'"pps":true' in got[0]
    out = tmp_path / "w.csv"
    LocalWatch("gpsd", interval=0.01, out_path=str(out), count=2, cmd=[addr]).run()
    (s,) = load(str(out))
    assert len(s) == 2 and s.offset[0] == pytest.approx(-2.5e-6)


def test_ticc_single_channel_phase_with_wrap_and_picoseconds():
    # a PPS 3e-11 fast against the TICC reference, 100 ps of white noise, started 999_990 s after power-on
    # and printed with WRAP=6, so the seconds roll over from 999999 to 0
    rng = np.random.default_rng(1)
    k = np.arange(30)
    phase = 3e-11 * k + rng.normal(0, 100e-12, k.size)
    lines = ["# TICC firmware", "# chA PPS"]
    for i in k:
        sec, frac = divmod(999_990 + int(i), 1)[0] % 1_000_000, 0.123456789012 + phase[i]
        lines.append(f"{sec}.{int(round(frac * 1e12)):012d} chA")
    (s,) = load("\n".join(lines) + "\n")
    assert s.source_format == "ticc" and s.meta["period_s"] == 1.0
    assert np.allclose(s.offset, phase - phase[0], atol=2e-12)
    assert np.all(np.diff(s.t) > 0)  # unwrapped


def test_ticc_two_channels_and_interval_mode():
    lines = []
    for i in range(10):
        lines.append(f"{i + 5}.{100000000000 + 7 * i:012d} chA")
        lines.append(f"{i + 5}.{100000250000:012d} chB")
    series = {s.meta["peer"]: s for s in parse_ticc(lines)}
    assert set(series) == {"chA", "chB", "chA - chB"}
    assert series["chA - chB"].offset == pytest.approx(-250e-9 + 7e-12 * np.arange(10), abs=1e-15)
    (iv,) = load("0.000000123456\n0.000000123460\n-0.000000000010\n", fmt="ticc")
    assert iv.meta["mode"] == "time interval" and iv.offset[2] == pytest.approx(-10e-12)
