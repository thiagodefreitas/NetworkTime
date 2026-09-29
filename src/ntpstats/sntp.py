# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Minimal, dependency-free SNTP (RFC 5905 / RFC 4330) client for measurements.

Improvements over the ``ntplib`` 0.1.9 copy used in 2012:

* Client data minimisation (draft-ietf-ntp-data-minimization): the transmit
  timestamp is a random nonce, not the local clock, so requests do not leak
  the client's time; the true T1 is kept locally. The server's echoed
  origin timestamp must match the nonce (anti-spoofing / stale reply check).
* NTP era handling: 32-bit NTP seconds roll over in 2036; timestamps are
  mapped to the era nearest the local clock.
* Kiss-o'-Death (stratum 0: RATE, DENY, RSTR...) and unsynchronised
  (LI=3) replies are reported instead of being treated as time.
* High-resolution local timestamps (``time.time_ns``) taken as close to the
  socket calls as Python allows.

This is a *measurement* client. It never sets the clock. Authenticated time
(NTS, RFC 8915) is not implemented here; use chrony/NTPsec for that and
analyse their logs with :mod:`ntpstats.parsers`.
"""

from __future__ import annotations

import os
import socket
import struct
import time
from dataclasses import asdict, dataclass
from typing import Optional

NTP_UNIX_DELTA = 2208988800
_ERA = 1 << 32
_PACKET = struct.Struct("!BBbbII4sQQQQ")

KOD_CODES = {
    "DENY": "access denied by server",
    "RSTR": "access restricted by server",
    "RATE": "rate exceeded - poll less often",
    "INIT": "server association not yet synchronised",
    "STEP": "server step change",
}


class NTPError(Exception):
    pass


class KissOfDeath(NTPError):
    def __init__(self, code: str):
        super().__init__(f"Kiss-o'-Death {code}: {KOD_CODES.get(code, 'unknown code')}")
        self.code = code


@dataclass
class NTPResult:
    server: str
    address: str
    t1: float  # client transmit, POSIX s
    t2: float  # server receive
    t3: float  # server transmit
    t4: float  # client receive
    offset: float  # ((t2 - t1) + (t3 - t4)) / 2, s (server - local)
    delay: float  # (t4 - t1) - (t3 - t2), s
    stratum: int
    leap: int
    version: int
    poll: int
    precision: float  # s
    root_delay: float  # s
    root_dispersion: float  # s
    refid: str

    def as_dict(self) -> dict:
        return asdict(self)


def _ntp_to_unix(raw: int, ref_unix: float) -> float:
    sec = raw >> 32
    frac = (raw & 0xFFFFFFFF) / _ERA
    base = sec + frac - NTP_UNIX_DELTA
    era = round((ref_unix - base) / _ERA)
    return base + era * _ERA


def _short(v: int) -> float:
    return (v >> 16) + (v & 0xFFFF) / 65536.0


def _refid(stratum: int, raw: bytes) -> str:
    if stratum <= 1:
        return raw.rstrip(b"\0").decode("ascii", errors="replace")
    if stratum < 16:
        return ".".join(str(b) for b in raw)  # IPv4, or hash of IPv6 address
    return raw.hex()


def query(
    server: str,
    port: int = 123,
    timeout: float = 2.0,
    version: int = 4,
    family: int = 0,
) -> NTPResult:
    """Send one client-mode request and return the measured offset/delay."""
    infos = socket.getaddrinfo(server, port, family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    if not infos:
        raise NTPError(f"cannot resolve {server}")
    fam, _, _, _, addr = infos[0]
    nonce = int.from_bytes(os.urandom(8), "big")
    pkt = bytearray(48)
    pkt[0] = (0 << 6) | (version << 3) | 3  # LI=0, VN, mode 3 (client)
    struct.pack_into("!Q", pkt, 40, nonce)

    with socket.socket(fam, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t1_ns = time.time_ns()
        sock.sendto(bytes(pkt), addr)
        deadline = time.monotonic() + timeout
        while True:
            try:
                data, src = sock.recvfrom(1024)
            except socket.timeout as exc:
                raise NTPError(f"timeout waiting for {server}") from exc
            t4_ns = time.time_ns()
            if len(data) >= 48 and data[24:32] == nonce.to_bytes(8, "big"):
                break  # matching reply
            if time.monotonic() > deadline:
                raise NTPError(f"no matching reply from {server}")

    (b0, stratum, poll, prec, rdelay, rdisp, refid, _ref, org, rec, xmt) = _PACKET.unpack(data[:48])
    leap, vn, mode = b0 >> 6, (b0 >> 3) & 7, b0 & 7
    if mode not in (4, 5):
        raise NTPError(f"unexpected mode {mode} in reply")
    if stratum == 0:
        raise KissOfDeath(refid.rstrip(b"\0").decode("ascii", errors="replace"))
    if leap == 3 or stratum >= 16:
        raise NTPError("server is not synchronised (LI=3 / stratum 16)")
    if xmt == 0:
        raise NTPError("server transmit timestamp is zero")

    t1 = t1_ns / 1e9
    t4 = t4_ns / 1e9
    t2 = _ntp_to_unix(rec, t1)
    t3 = _ntp_to_unix(xmt, t1)
    # Differences computed from the ns integers where possible for precision.
    offset = ((t2 - t1) + (t3 - t4)) / 2.0
    delay = (t4_ns - t1_ns) / 1e9 - (t3 - t2)
    return NTPResult(
        server=server,
        address=str(src[0]),
        t1=t1, t2=t2, t3=t3, t4=t4,
        offset=offset,
        delay=delay,
        stratum=stratum,
        leap=leap,
        version=vn,
        poll=poll,
        precision=2.0 ** prec,
        root_delay=_short(rdelay),
        root_dispersion=_short(rdisp),
        refid=_refid(stratum, refid),
    )


def best_of(server: str, count: int = 4, spacing: float = 2.0, **kw) -> Optional[NTPResult]:
    """Take ``count`` samples and return the minimum-delay one (the classic
    NTP clock-filter heuristic: least delay = least queueing asymmetry)."""
    best = None
    for i in range(count):
        if i:
            time.sleep(spacing)
        try:
            r = query(server, **kw)
        except KissOfDeath:
            raise
        except (NTPError, OSError):
            continue
        if best is None or r.delay < best.delay:
            best = r
    return best
