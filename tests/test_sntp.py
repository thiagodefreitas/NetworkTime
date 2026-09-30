# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
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


# ------------------------------------------------------------------ NTPv5
class FakeV5Server(FakeServer):
    """Answers draft-09 NTPv5 requests and the v4 'NTP5DRFT' upgrade probe."""

    def __init__(self, offset=0.25, timescale=0, synced=True):
        super().__init__(offset=offset)
        self.timescale = timescale
        self.synced = synced

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(2048)
            except OSError:
                return
            self.requests.append(data)
            vn = (data[0] >> 3) & 7
            t2 = time.time() + self.offset + (37 if self.timescale == 1 else 0)
            if vn == 5:
                cookie = data[24:32]
                hdr = bytearray(48)
                hdr[0] = (0 << 6) | (5 << 3) | 4
                hdr[1], hdr[2], hdr[3] = 1, 4, -20 & 0xFF
                struct.pack_into("!II", hdr, 4, int(0.001 * 2 ** 28), int(0.002 * 2 ** 28))
                struct.pack_into("!BBH", hdr, 12, self.timescale, 0, 0x1 if self.synced else 0)
                hdr[16:24] = b"S" * 8
                hdr[24:32] = cookie
                struct.pack_into("!QQ", hdr, 32, to_ntp(t2), to_ntp(t2 + 1e-5))
                self.sock.sendto(bytes(hdr) + sntp._ef(sntp.EF_DRAFT_ID, sntp.NTPV5_DRAFT.encode()), addr)
            else:
                reply = bytearray(self._pkt(2, bytes([192, 0, 2, 1]), data[40:48], t2))
                if data[16:24] == sntp.NTPV5_UPGRADE:
                    reply[16:24] = sntp.NTPV5_UPGRADE
                self.sock.sendto(bytes(reply), addr)


@pytest.fixture
def v5server(request):
    srv = FakeV5Server(**getattr(request, "param", {}))
    srv.start()
    yield srv
    srv.close()


def test_ntpv5_query(v5server):
    r = sntp.query("127.0.0.1", port=v5server.port, version=5)
    assert r.version == 5 and r.timescale == "utc" and r.draft == sntp.NTPV5_DRAFT
    assert r.offset == pytest.approx(0.25, abs=0.01)
    # 4.28 fixed point: 2^-28 s ~ 3.7 ns resolution
    assert r.root_delay == pytest.approx(0.001, abs=4e-9) and r.root_dispersion == pytest.approx(0.002, abs=4e-9)
    req = v5server.requests[0]
    assert (req[0] >> 3) & 7 == 5 and len(req) == 76  # header + draft-id EF
    assert req[24:32] != b"\0" * 8 and req[32:48] == b"\0" * 16


@pytest.mark.parametrize("v5server", [{"timescale": 1}], indirect=True)
def test_ntpv5_tai_timescale(v5server):
    r = sntp.query_v5("127.0.0.1", port=v5server.port)
    assert r.timescale == "tai" and r.offset == pytest.approx(0.25, abs=0.01)


@pytest.mark.parametrize("v5server", [{"synced": False}], indirect=True)
def test_ntpv5_unsynchronised(v5server):
    with pytest.raises(sntp.NTPError):
        sntp.query_v5("127.0.0.1", port=v5server.port)


def test_ntpv5_upgrade_probe(v5server, server):
    assert sntp.supports_v5("127.0.0.1", port=v5server.port) is True
    assert sntp.supports_v5("127.0.0.1", port=server.port) is False


def test_ntpv5_era_mapping():
    # Era 1 begins 2036-02-07; a v5 timestamp with era=1 must map past 2036.
    assert sntp._ntp_to_unix(0, 2085978496 + 10) == pytest.approx(2085978496)


def test_falls_back_to_next_address(server, monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *a, **k):
        good = real("127.0.0.1", port, socket.AF_INET, socket.SOCK_DGRAM)
        bad = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("256.0.0.1", port))]  # unusable
        return bad + good

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    r = sntp.query("dual-stack.example", port=server.port)
    assert r.offset == pytest.approx(0.25, abs=0.01)


class InterleavedServer(threading.Thread):
    """RFC 9769 server whose basic-mode transmit timestamps are 2 ms late (software timestamping)."""

    def __init__(self, offset=0.25, supports=True):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.offset, self.supports = offset, supports
        self.saved = {}  # rx raw -> precise tx raw

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(512)
            except OSError:
                return
            t2 = to_ntp(time.time() + self.offset).to_bytes(8, "big")
            org, rx, xmt = data[24:32], data[32:40], data[40:48]
            precise = to_ntp(time.time() + self.offset).to_bytes(8, "big")
            if self.supports and rx != xmt and org in self.saved:
                out_org, out_tx = rx, self.saved.pop(org)
            else:
                out_org, out_tx = xmt, to_ntp(time.time() + self.offset + 0.002).to_bytes(8, "big")
            self.saved[t2] = precise
            head = struct.pack("!BBbbII4s", (4 << 3) | 4, 2, 6, -20, 0x00010000, 0x00008000, bytes([192, 0, 2, 1]))
            self.sock.sendto(head + t2 + out_org + t2 + out_tx, addr)

    def close(self):
        self.sock.close()


@pytest.mark.parametrize("supports", [True, False])
def test_interleaved_mode(supports):
    from ntpstats.sntp import query_interleaved

    srv = InterleavedServer(supports=supports)
    srv.start()
    try:
        r = query_interleaved("127.0.0.1", port=srv.port, timeout=2, spacing=0.05)
    finally:
        srv.close()
    assert r.interleaved is supports
    if supports:  # precise transmit time: no 1 ms bias from the late basic-mode timestamp
        assert r.offset == pytest.approx(0.25, abs=5e-4)
    else:
        assert r.offset == pytest.approx(0.251, abs=5e-4)
