# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""SNTP client against a local fake server (no Internet access needed)."""

import socket
import struct
import threading
import time

import pytest

from ntpstats import sntp
from ntpstats.monitor import Monitor

NTP_DELTA = 2208988800


def to_ntp(t):
    sec = int(t) + NTP_DELTA
    return (sec << 32) | int((t % 1) * 2 ** 32)


class FakeServer(threading.Thread):
    def __init__(self, offset=0.25, mode="ok"):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.offset = offset
        self.mode = mode
        self.requests = []

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(512)
            except OSError:
                return
            self.requests.append(data)
            t2 = time.time() + self.offset
            client_xmt = data[40:48]
            stratum, refid = 2, bytes([192, 0, 2, 1])
            org = client_xmt
            if self.mode == "kod":
                stratum, refid = 0, b"RATE"
            if self.mode == "unsync":
                stratum = 16
            if self.mode == "spoof":
                # first a reply with the wrong origin, then the right one
                bad = self._pkt(stratum, refid, b"\x00" * 8, t2)
                self.sock.sendto(bad, addr)
            self.sock.sendto(self._pkt(stratum, refid, org, t2), addr)

    def _pkt(self, stratum, refid, org, t2):
        t3 = time.time() + self.offset
        head = struct.pack("!BBbbII4s", (0 << 6) | (4 << 3) | 4, stratum, 6, -20, 0x00010000, 0x00008000, refid)
        return head + struct.pack("!Q", to_ntp(t2 - 1)) + org + struct.pack("!QQ", to_ntp(t2), to_ntp(t3))

    def close(self):
        self.sock.close()


@pytest.fixture
def server(request):
    srv = FakeServer(**getattr(request, "param", {}))
    srv.start()
    yield srv
    srv.close()


def test_query_offset_delay_and_privacy(server):
    r = sntp.query("127.0.0.1", port=server.port)
    assert r.offset == pytest.approx(0.25, abs=0.01)
    assert 0 <= r.delay < 0.05
    assert r.stratum == 2 and r.refid == "192.0.2.1"
    assert r.root_delay == pytest.approx(1.0) and r.root_dispersion == pytest.approx(0.5)
    # data minimisation: transmit timestamp is a random nonce, not our clock
    assert server.requests[0][40:48] != b"\0" * 8
    assert server.requests[0][16:40] == b"\0" * 24  # no ref/org/rec leaked


@pytest.mark.parametrize("server", [{"mode": "kod"}], indirect=True)
def test_kiss_of_death(server):
    with pytest.raises(sntp.KissOfDeath) as exc:
        sntp.query("127.0.0.1", port=server.port)
    assert exc.value.code == "RATE"


@pytest.mark.parametrize("server", [{"mode": "unsync"}], indirect=True)
def test_unsynchronised_server(server):
    with pytest.raises(sntp.NTPError):
        sntp.query("127.0.0.1", port=server.port)


@pytest.mark.parametrize("server", [{"mode": "spoof"}], indirect=True)
def test_mismatched_origin_is_ignored(server):
    r = sntp.query("127.0.0.1", port=server.port)
    assert r.offset == pytest.approx(0.25, abs=0.01)


def test_timeout():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    try:
        with pytest.raises(sntp.NTPError):
            sntp.query("127.0.0.1", port=s.getsockname()[1], timeout=0.2)
    finally:
        s.close()


def test_era_rollover():
    # Feb 2036: NTP seconds wrap to era 1.
    t = 2085978496 + 100.0  # POSIX time just after the rollover
    raw = ((int(t) + NTP_DELTA) % (1 << 32)) << 32
    assert sntp._ntp_to_unix(raw, t) == pytest.approx(int(t))


def test_monitor_writes_csv(server, tmp_path, monkeypatch):
    real = sntp.query
    monkeypatch.setattr("ntpstats.monitor.query", lambda host: real(host, port=server.port))
    out = tmp_path / "mon.csv"
    m = Monitor(["127.0.0.1"], interval=0.05, out_path=str(out), count=3)
    m.run()
    lines = out.read_text().splitlines()
    assert lines[0].startswith("unix_time,offset,delay")
    assert len(lines) == 4
    from ntpstats.parsers import load_one
    s = load_one(str(out))
    assert len(s) == 3 and s.offset.mean() == pytest.approx(0.25, abs=0.01)
