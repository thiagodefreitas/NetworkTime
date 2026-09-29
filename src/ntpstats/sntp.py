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

* Experimental **NTPv5** (draft-ietf-ntp-ntpv5-09): 48-octet v5 header with
  client/server cookies, timescale, era and flags, the draft-identification
  extension field, and the NTPv4 -> v5 upgrade probe (reference timestamp
  ``NTP5DRFT``). Interoperable with ntpd-rs' experimental v5 support.

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

NTPV5_DRAFT = "draft-ietf-ntp-ntpv5-09"
NTPV5_UPGRADE = b"NTP5DRFT"  # reference timestamp used to negotiate v5 (draft-09)
EF_DRAFT_ID = 0xF5FF
TIMESCALES = {0: "utc", 1: "tai", 2: "ut1", 3: "leap-smeared-utc"}
#: TAI - UTC in seconds (unchanged since 2017-01-01; leap seconds end by 2035)
TAI_UTC = 37

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
    timescale: str = "utc"  # NTPv5: utc, tai, ut1, leap-smeared-utc
    era: int = 0
    flags: int = 0  # NTPv5 flags word (0x1 synchronized, 0x2 interleaved, 0x4 authNAK)
    draft: str = ""  # NTPv5 draft identification echoed by the server
    auth: str = ""  # "nts" when the exchange was authenticated with NTS (RFC 8915)

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


def _udp_socket(server, port, family):
    """First address of ``server`` that this host can actually send to
    (falls back from IPv6 to IPv4 and vice versa)."""
    try:
        infos = socket.getaddrinfo(server, port, family, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    except socket.gaierror as exc:
        raise NTPError(f"cannot resolve {server}: {exc}") from exc
    errors = []
    for fam, _, _, _, addr in infos:
        try:
            sock = socket.socket(fam, socket.SOCK_DGRAM)
        except OSError as exc:
            errors.append(f"{addr[0]}: {exc.strerror or exc}")
            continue
        try:
            sock.connect(addr)  # fails early for unreachable families/routes
            return sock, addr
        except OSError as exc:
            sock.close()
            errors.append(f"{addr[0]}: {exc.strerror or exc}")
    raise NTPError(f"no usable address for {server} ({'; '.join(errors) or 'none resolved'})")


def _exchange(server, port, timeout, family, payload: bytes, match):
    sock, addr = _udp_socket(server, port, family)
    with sock:
        sock.settimeout(timeout)
        t1_ns = time.time_ns()
        sock.send(payload)
        deadline = time.monotonic() + timeout
        while True:
            try:
                data = sock.recv(2048)
                src = addr
            except socket.timeout as exc:
                raise NTPError(f"timeout waiting for {server}") from exc
            t4_ns = time.time_ns()
            if len(data) >= 48 and match(data):
                return data, src, t1_ns, t4_ns
            if time.monotonic() > deadline:
                raise NTPError(f"no matching reply from {server}")


def _v4_request(version: int, nonce: bytes, reference: bytes = b"\0" * 8) -> bytes:
    pkt = bytearray(48)
    pkt[0] = (0 << 6) | (version << 3) | 3  # LI=0, VN, mode 3 (client)
    pkt[16:24] = reference
    pkt[40:48] = nonce
    return bytes(pkt)


def _ef(type_id: int, value: bytes) -> bytes:
    """NTPv5 extension field: length excludes padding; value padded to 4 octets."""
    ef = struct.pack("!HH", type_id, 4 + len(value)) + value
    return ef + b"\0" * ((4 - len(ef) % 4) % 4)


def _parse_efs(data: bytes) -> dict:
    out, off = {}, 48
    while off + 4 <= len(data):
        t, ln = struct.unpack_from("!HH", data, off)
        if ln < 4 or off + ln > len(data):
            break
        out[t] = data[off + 4: off + ln]
        off += (ln + 3) & ~3
    return out


def query(
    server: str,
    port: int = 123,
    timeout: float = 2.0,
    version: int = 4,
    family: int = 0,
) -> NTPResult:
    """Send one client-mode request and return the measured offset/delay.

    ``version=5`` uses the experimental NTPv5 format (see :func:`query_v5`).
    """
    if version == 5:
        return query_v5(server, port=port, timeout=timeout, family=family)
    nonce = os.urandom(8)
    data, src, t1_ns, t4_ns = _exchange(server, port, timeout, family, _v4_request(version, nonce),
                                        lambda d: d[24:32] == nonce)

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


def query_v5(server: str, port: int = 123, timeout: float = 2.0, family: int = 0,
             tai_utc: float = TAI_UTC) -> NTPResult:
    """Experimental NTPv5 query (draft-ietf-ntp-ntpv5-09).

    Header: LI|VN|Mode, Stratum, Poll, Precision, Root Delay and Root
    Dispersion (unsigned 4.28 fixed point, seconds), Timescale, Era, Flags,
    Server Cookie, Client Cookie, Receive and Transmit Timestamps. The
    random client cookie replaces the v4 origin timestamp. Timestamps are
    mapped with the era field; a TAI response is converted to UTC with
    ``tai_utc``.
    """
    cookie = os.urandom(8)
    pkt = bytearray(48)
    pkt[0] = (0 << 6) | (5 << 3) | 3
    pkt[24:32] = cookie
    payload = bytes(pkt) + _ef(EF_DRAFT_ID, NTPV5_DRAFT.encode())
    data, src, t1_ns, t4_ns = _exchange(server, port, timeout, family, payload,
                                        lambda d: (d[0] >> 3) & 7 == 5 and d[24:32] == cookie)
    b0, stratum, poll, prec = struct.unpack_from("!BBbb", data, 0)
    rdelay, rdisp = struct.unpack_from("!II", data, 4)
    tscale, era, flags = struct.unpack_from("!BBH", data, 12)
    rec, xmt = struct.unpack_from("!QQ", data, 32)
    leap, mode = b0 >> 6, b0 & 7
    if mode != 4:
        raise NTPError(f"unexpected mode {mode} in NTPv5 reply")
    efs = _parse_efs(data)
    draft = efs.get(EF_DRAFT_ID, b"").rstrip(b"\0").decode("ascii", errors="replace")
    if flags & 0x4:
        raise NTPError("NTPv5 authNAK from server")
    if stratum == 0:
        raise KissOfDeath("V5" if poll < 127 else "DENY")
    if not flags & 0x1 or leap == 3:
        raise NTPError("server is not synchronised (NTPv5 flags)")
    if xmt == 0:
        raise NTPError("server transmit timestamp is zero")

    def ts(raw):
        return (raw >> 32) + (raw & 0xFFFFFFFF) / _ERA - NTP_UNIX_DELTA + era * _ERA

    t1, t4 = t1_ns / 1e9, t4_ns / 1e9
    t2, t3 = ts(rec), ts(xmt)
    timescale = TIMESCALES.get(tscale, f"unknown({tscale})")
    if timescale == "tai":
        t2 -= tai_utc
        t3 -= tai_utc
    return NTPResult(
        server=server,
        address=str(src[0]),
        t1=t1, t2=t2, t3=t3, t4=t4,
        offset=((t2 - t1) + (t3 - t4)) / 2.0,
        delay=(t4_ns - t1_ns) / 1e9 - (t3 - t2),
        stratum=stratum,
        leap=leap,
        version=5,
        poll=poll,
        precision=2.0 ** prec,
        root_delay=rdelay / 2.0 ** 28,
        root_dispersion=rdisp / 2.0 ** 28,
        refid="",
        timescale=timescale,
        era=era,
        flags=flags,
        draft=draft,
    )


def supports_v5(server: str, port: int = 123, timeout: float = 2.0, family: int = 0) -> bool:
    """Probe for NTPv5 support: an NTPv4 request whose reference timestamp is
    ``NTP5DRFT``; a v5-capable server echoes it in its v4 response."""
    nonce = os.urandom(8)
    data, *_ = _exchange(server, port, timeout, family, _v4_request(4, nonce, NTPV5_UPGRADE),
                         lambda d: d[24:32] == nonce)
    return data[16:24] == NTPV5_UPGRADE


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
