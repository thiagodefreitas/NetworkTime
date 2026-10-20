# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""3.8 sources (#21): PHC against the system clock, OCP Time Card, ClockBound, fbclock, ptp4l ports.

The kernel ioctl, the client library and the commands are replaced by fakes that follow the
layouts of include/uapi/linux/ptp_clock.h, clock-bound-ffi/include/clockbound.h, ptpcheck
fbclock's text output and pmc's PORT_DATA_SET responses.
"""

import os

import pytest

from ntpstats import hwclocks as H
from ntpstats import sources
from ntpstats.bounds import parse_bounds
from ntpstats.metrics import Registry
from ntpstats.parsers import load
from ntpstats.sources import LocalWatch, SourceError

TAI_UTC = 37


def filled(samples):
    """A ptp_sys_offset_extended as the kernel fills it: [(t1, phc, t2) in ns]."""
    buf = H.sys_offset_request(len(samples))
    for i, triple in enumerate(samples):
        for k, ns in enumerate(triple):
            H._CLOCK_TIME.pack_into(buf, H._EXT_HEADER.size + (3 * i + k) * H._CLOCK_TIME.size,
                                    ns // 1_000_000_000, ns % 1_000_000_000, 0)
    return bytes(buf)


def test_ioctl_layout_matches_the_kernel_header():
    assert H._EXT_SIZE == 16 + 25 * 3 * 16 == 1216
    assert H.PTP_SYS_OFFSET_EXTENDED == 0xC4C03D09  # _IOWR('=', 9, struct ptp_sys_offset_extended)
    with pytest.raises(ValueError):
        H.sys_offset_request(26)


def test_shortest_window_wins_and_tai_is_removed():
    s = 1_761_000_000 * 1_000_000_000
    buf = filled([(s, s + TAI_UTC * 10**9 + 2_500, s + 3_000),           # window 3 us
                  (s + 10_000, s + TAI_UTC * 10**9 + 10_700, s + 11_000),  # window 1 us: midpoint 10_500
                  (s + 20_000, s + TAI_UTC * 10**9 + 0, s + 25_000)])
    sys_ns, diff, window = H.parse_sys_offset(buf)
    assert (sys_ns, diff, window) == (s + 10_500, TAI_UTC * 10**9 + 200, 1_000)
    d = H.phc_sample(sys_ns, diff, window)
    assert d["offset"] == pytest.approx(200e-9) and d["whole_seconds"] == 37 and d["read_window"] == 1e-6
    assert H.phc_sample(sys_ns, diff, window, tai_utc=36)["offset"] == pytest.approx(1 + 200e-9)


def test_read_phc_through_a_fake_ioctl(monkeypatch, tmp_path):
    import fcntl

    dev = tmp_path / "ptp9"
    dev.write_bytes(b"")
    s = 1_761_000_000 * 1_000_000_000

    def ioctl(fd, req, buf, mutate):
        assert req == H.PTP_SYS_OFFSET_EXTENDED and len(buf) == 1216 and H._EXT_HEADER.unpack_from(buf)[0] == 9
        buf[:] = filled([(s, s + TAI_UTC * 10**9 - 400, s + 1_000)] * 9)
        return 0

    monkeypatch.setattr(fcntl, "ioctl", ioctl)
    d = H.sample_phc([str(dev)])
    assert d["offset"] == pytest.approx(-900e-9) and d["device"] == str(dev)
    with pytest.raises(SourceError, match="cannot open"):
        H.sample_phc([str(tmp_path / "missing")])


def test_timecard_sysfs(monkeypatch, tmp_path):
    card = tmp_path / "ocp0"
    card.mkdir()
    for k, v in {"gnss_sync": "LOST @ 2026-10-20T10:00:00", "clock_source": "GNSS", "utc_tai_offset": "37",
                 "clock_status_offset": "-12", "clock_status_drift": "3", "serialnum": "fb:01:02"}.items():
        (card / k).write_text(v + "\n")
    (tmp_path / "ptp3").mkdir()
    os.symlink(tmp_path / "ptp3", card / "ptp")
    st = H.timecard_status(str(card))
    assert st["gnss_sync"] == 0 and st["gnss_lost"] == "2026-10-20T10:00:00" and st["device"] == "/dev/ptp3"
    assert (st["fw_offset"], st["fw_drift"], st["utc_tai_offset"]) == (-12, 3, 37)
    seen = {}
    monkeypatch.setattr(H, "read_phc", lambda dev: seen.setdefault("dev", dev) and (10**18, 37 * 10**9 + 50, 900))
    d = H.sample_timecard([str(card)])
    assert seen["dev"] == "/dev/ptp3" and d["offset"] == pytest.approx(50e-9) and d["clock_source"] == "GNSS"
    (card / "gnss_sync").write_text("SYNC\n")
    assert H.timecard_status(str(card))["gnss_sync"] == 1
    with pytest.raises(SourceError, match="ptp_ocp"):
        H.timecard_status(str(tmp_path / "nope"))


class FakeClockBound:
    """clockbound_open/clockbound_now with the C signatures of clockbound.h."""

    def __init__(self, earliest, latest, status=1):
        self.e, self.la, self.status = earliest, latest, status

    def clockbound_now(self, ctx, res, err):
        r = res._obj
        r.earliest.tv_sec, r.earliest.tv_nsec = divmod(self.e, 10**9)
        r.latest.tv_sec, r.latest.tv_nsec = divmod(self.la, 10**9)
        r.clock_status = self.status
        return None


def test_clockbound_sample_and_watch_log_reads_as_bounds(monkeypatch, tmp_path):
    import time as _time

    now = _time.time_ns()
    monkeypatch.setitem(H._CB, "lib", FakeClockBound(now - 40_000, now + 60_000, 1))
    monkeypatch.setitem(H._CB, "ctx", 1)
    d = sources.sample_clockbound()
    assert d["bound"] == pytest.approx(50e-6) and d["status"] == "synchronized"
    assert abs(d["offset"] - 10e-6) < 1e-3  # the centre is 10 us after the system clock read
    out = tmp_path / "cb.csv"
    LocalWatch("clockbound", 0.0, out_path=str(out), count=3).run()
    (b,) = load(str(out))
    assert b.source_format == "bounds" and len(b) == 3 and b.extra["bound"][0] == pytest.approx(50e-6)
    assert H.clockbound_sample(0, 10, 100, 300, 3)["status"] == "disrupted"
    monkeypatch.setitem(H._CB, "lib", FakeClockBound(now, now, 0))
    assert sources.sample_clockbound()["synchronized"] == 0


def test_clockbound_missing_library(monkeypatch):
    monkeypatch.setattr(H, "_CB", {})
    monkeypatch.setenv("NTPSTATS_LIBCLOCKBOUND", "/nonexistent/libclockbound.so")
    with pytest.raises(SourceError, match="cannot load"):
        sources.sample_clockbound()


def test_fbclock_text_and_sample(monkeypatch):
    out = "TrueTime:\n\tEarliest: 1761000000000000000\n\tLatest: 1761000000000020000\n\tWOU=20000 ns\n"
    assert H.parse_fbclock(out) == (1761000000000000000, 1761000000000020000)
    monkeypatch.setattr(H, "_run", lambda cmd: out)
    d = sources.sample_fbclock()
    assert d["bound"] == pytest.approx(10e-6) and d["earliest"] == "1761000000.000000000"
    with pytest.raises(SourceError):
        H.parse_fbclock("no data")


PMC_PORTS = """sending: GET PORT_DATA_SET
\t001122.fffe.334455-1 seq 2 RESPONSE MANAGEMENT PORT_DATA_SET
\t\tportIdentity            001122.fffe.334455-1
\t\tportState               SLAVE
\t\tlogMinDelayReqInterval  0
\t\tpeerMeanPathDelay       0
\t001122.fffe.334455-2 seq 2 RESPONSE MANAGEMENT PORT_DATA_SET
\t\tportIdentity            001122.fffe.334455-2
\t\tportState               MASTER
\t001122.fffe.334455-3 seq 2 RESPONSE MANAGEMENT PORT_DATA_SET
\t\tportIdentity            001122.fffe.334455-3
\t\tportState               FAULTY
"""


def test_ptp4l_port_states(monkeypatch):
    from tests.test_sources29 import PMC

    assert H.parse_port_states(PMC_PORTS) == [(1, "SLAVE"), (2, "MASTER"), (3, "FAULTY")]
    monkeypatch.setattr(sources, "_run", lambda cmd: PMC + PMC_PORTS)
    d = sources.sample_pmc()
    assert d["offset"] == pytest.approx(12e-9) and d["port_states"] == "1:SLAVE 2:MASTER 3:FAULTY"
    assert (d["ports"], d["slave_port"], d["faulty_ports"]) == (3, 1, 1)
    monkeypatch.setattr(sources, "_run", lambda cmd: PMC)
    assert sources.sample_pmc()["port_states"] == ""


def test_exporter_uses_the_service_bound():
    reg = Registry()
    reg.observe_watch("clockbound", {"time": 1.0, "offset": 2e-6, "bound": 50e-6})
    line = next(ln for ln in reg.render().splitlines() if ln.startswith("ntpstats_offset_bound_seconds{"))
    assert float(line.split()[-1]) == pytest.approx(52e-6)


def test_bounds_parser_reads_exact_edges():
    (b,) = parse_bounds(["unix_time,offset,earliest,latest", "1761000000.000000,0,1760999999.999990000,1761000000.000030000"])
    assert b.offset[0] == pytest.approx(10e-6) and b.extra["bound"][0] == pytest.approx(20e-6)
