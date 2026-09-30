# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""NTP and PTP exchanges from packet captures (pcap and pcapng), standard library only.

**NTP.** Client requests (mode 3) are matched with server responses (mode 4)
by the echoed origin timestamp (NTPv3/v4) or client cookie (NTPv5), and
RFC 9769 interleaved responses by the request's receive timestamp. Offsets
are computed from the server timestamps T2/T3 in the response and the
*capture* timestamps of the two packets as T1/T4::

    offset = ((T2 - c1) + (T3 - c4)) / 2      delay = (c4 - c1) - (T3 - T2)

so the result is the offset of the server relative to the capture host's
clock, independent of what the client software believes, and it keeps
working when the client randomises its transmit timestamp (RFC 9109 /
data-minimisation). With hardware timestamps in the capture (pcapng
``if_tsresol`` nanosecond resolution, ``tcpdump -j adapter_unsynced``) this
measures the path without software timestamping noise.

**PTP** (IEEE 1588) messages are handled by :mod:`ntpstats.ptp`.

Capture timestamps are kept as integer nanoseconds: a float of POSIX seconds
only resolves about 240 ns today, too coarse for hardware-timestamped data.

Supported link types: Ethernet (with 802.1Q/802.1ad tags), Linux cooked
v1/v2, raw IPv4/IPv6, BSD loopback. IPv4 and IPv6 (without extension headers)
over UDP. IP fragments are ignored.
"""

from __future__ import annotations

import struct
from collections import OrderedDict
from typing import Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple

import numpy as np

from .series import TimeSeries

NTP_UNIX_DELTA = 2208988800
_ERA = 1 << 32
NS = 1_000_000_000
PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1000),  # microseconds -> ns multiplier
    b"\xa1\xb2\xc3\xd4": (">", 1000),
    b"\x4d\x3c\xb2\xa1": ("<", 1),  # nanoseconds
    b"\xa1\xb2\x3c\x4d": (">", 1),
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"


def is_capture(head: bytes) -> bool:
    return head[:4] in PCAP_MAGICS or head[:4] == PCAPNG_MAGIC


# ------------------------------------------------------------ file readers
def _pcap_packets(data: bytes) -> Iterator[Tuple[int, int, bytes]]:
    endian, mult = PCAP_MAGICS[data[:4]]
    linktype = struct.unpack(endian + "I", data[20:24])[0] & 0x0FFFFFFF
    off = 24
    rec = struct.Struct(endian + "IIII")
    while off + 16 <= len(data):
        sec, frac, incl, _orig = rec.unpack_from(data, off)
        off += 16
        yield sec * NS + frac * mult, linktype, data[off: off + incl]
        off += incl


def _tsres_to_ns(v: int) -> Callable[[int], int]:
    """Converter from raw pcapng timestamp units (``if_tsresol`` byte) to ns."""
    if v & 0x80:
        shift = v & 0x7F
        return lambda raw: (raw * NS + (1 << (shift - 1) if shift else 0)) >> shift
    if v <= 9:
        k = 10 ** (9 - v)
        return lambda raw: raw * k
    d = 10 ** (v - 9)
    return lambda raw: (raw + d // 2) // d


def _pcapng_packets(data: bytes) -> Iterator[Tuple[int, int, bytes]]:
    off = 0
    endian = "<"
    ifaces: List[Tuple[int, Callable[[int], int]]] = []
    while off + 12 <= len(data):
        btype = data[off: off + 4]
        if btype == PCAPNG_MAGIC:
            bom = data[off + 8: off + 12]
            endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            ifaces = []
        btype_i, blen = struct.unpack_from(endian + "II", data, off)
        if blen < 12 or off + blen > len(data):
            break
        body = data[off + 8: off + blen - 4]
        if btype_i == 1:  # Interface Description Block
            linktype = struct.unpack_from(endian + "H", body, 0)[0]
            conv = _tsres_to_ns(6)  # default: microseconds
            opt = 8
            while opt + 4 <= len(body):
                code, olen = struct.unpack_from(endian + "HH", body, opt)
                if code == 0:
                    break
                if code == 9 and olen >= 1:  # if_tsresol
                    conv = _tsres_to_ns(body[opt + 4])
                opt += 4 + ((olen + 3) & ~3)
            ifaces.append((linktype, conv))
        elif btype_i == 6 and ifaces:  # Enhanced Packet Block
            ifid, tshi, tslo, caplen, _ = struct.unpack_from(endian + "IIIII", body, 0)
            linktype, conv = ifaces[ifid] if ifid < len(ifaces) else ifaces[0]
            yield conv((tshi << 32) | tslo), linktype, body[20: 20 + caplen]
        off += blen


def packets(data: bytes) -> Iterator[Tuple[int, int, bytes]]:
    """``(timestamp_ns, linktype, frame)`` for every packet of a pcap/pcapng file."""
    if data[:4] in PCAP_MAGICS:
        return _pcap_packets(data)
    if data[:4] == PCAPNG_MAGIC:
        return _pcapng_packets(data)
    raise ValueError("not a pcap/pcapng file")


# ---------------------------------------------------------- dissection
class Link(NamedTuple):
    ethertype: int
    offset: int  # start of the network-layer payload in the frame
    src: str  # MAC address, "" when the link type has none
    dst: str


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def link(linktype: int, frame: bytes) -> Optional[Link]:
    """Link-layer header: EtherType, payload offset and MAC addresses."""
    src = dst = ""
    if linktype == 1:  # Ethernet
        if len(frame) < 14:
            return None
        dst, src = _mac(frame[0:6]), _mac(frame[6:12])
        et = struct.unpack_from("!H", frame, 12)[0]
        p = 14
        while et in (0x8100, 0x88A8, 0x9100) and len(frame) >= p + 4:
            et = struct.unpack_from("!H", frame, p + 2)[0]
            p += 4
    elif linktype == 113:  # Linux cooked v1
        if len(frame) < 16:
            return None
        et = struct.unpack_from("!H", frame, 14)[0]
        src = _mac(frame[6:12]) if struct.unpack_from("!H", frame, 4)[0] == 6 else ""
        p = 16
    elif linktype == 276:  # Linux cooked v2
        if len(frame) < 20:
            return None
        et = struct.unpack_from("!H", frame, 0)[0]
        src = _mac(frame[12:18]) if frame[11] == 6 else ""
        p = 20
    elif linktype in (101, 12, 228, 229):  # raw IP
        if not frame:
            return None
        et = 0x0800 if frame[0] >> 4 == 4 else 0x86DD
        p = 0
    elif linktype == 0:  # BSD loopback
        if len(frame) < 4:
            return None
        fam = struct.unpack_from("<I", frame, 0)[0]
        et = 0x0800 if fam == 2 else 0x86DD
        p = 4
    else:
        return None
    return Link(et, p, src, dst)


def udp_payload(frame: bytes, lk: Link):
    """Return (src, dst, udp_sport, udp_dport, payload) or None."""
    p = lk.offset
    if lk.ethertype == 0x0800:
        if len(frame) < p + 20:
            return None
        ihl = (frame[p] & 0x0F) * 4
        proto = frame[p + 9]
        flags_frag = struct.unpack_from("!H", frame, p + 6)[0]
        if proto != 17 or flags_frag & 0x3FFF:  # not UDP, or a fragment
            return None
        src = ".".join(str(b) for b in frame[p + 12: p + 16])
        dst = ".".join(str(b) for b in frame[p + 16: p + 20])
        u = p + ihl
    elif lk.ethertype == 0x86DD:
        if len(frame) < p + 40 or frame[p + 6] != 17:
            return None
        src = _v6(frame[p + 8: p + 24])
        dst = _v6(frame[p + 24: p + 40])
        u = p + 40
    else:
        return None
    if len(frame) < u + 8:
        return None
    sport, dport, ulen = struct.unpack_from("!HHH", frame, u)
    return src, dst, sport, dport, frame[u + 8: u + max(ulen, 8)]


def _ip_payload(linktype: int, frame: bytes):
    lk = link(linktype, frame)
    return None if lk is None else udp_payload(frame, lk)


def _v6(b: bytes) -> str:
    words = struct.unpack("!8H", b)
    return ":".join(f"{w:x}" for w in words)


def _ntp_ns(raw: int, ref_ns: int, era: Optional[int] = None) -> int:
    """NTP 64-bit timestamp -> POSIX ns, era chosen closest to ``ref_ns`` (or given)."""
    sec = (raw >> 32) - NTP_UNIX_DELTA
    frac_ns = ((raw & 0xFFFFFFFF) * NS + (1 << 31)) >> 32
    if era is not None:
        sec += era * _ERA
    else:
        sec += round((ref_ns / NS - sec) / _ERA) * _ERA
    return sec * NS + frac_ns


def ntp_exchanges(data: bytes, port: int = 123) -> Dict[Tuple[str, str], list]:
    """Matched client/server exchanges per (client, server) pair.

    Rows are ``(time, offset, delay, stratum, version, interleaved)``. With
    RFC 9769 interleaved mode, a response whose origin equals the request's
    *receive* timestamp carries the precise transmit time of the previous
    response; that exchange's row is then recomputed with it and marked
    ``interleaved = 1``.
    """
    pending: Dict[Tuple[str, str, bytes], Tuple[int, int]] = {}
    pending_i: Dict[Tuple[str, str, bytes], Tuple[bytes, int, bytes]] = {}  # request rx -> (server rx, c1, tx)
    done: Dict[Tuple[str, str, bytes], Tuple[int, int, int, int]] = {}  # server rx -> (c1, t2, c4, row)
    out: "OrderedDict[Tuple[str, str], list]" = OrderedDict()
    for ts, lt, frame in packets(data):
        d = _ip_payload(lt, frame)
        if d is None:
            continue
        src, dst, sport, dport, ntp = d
        if port not in (sport, dport) or len(ntp) < 48:
            continue
        vn, mode = (ntp[0] >> 3) & 7, ntp[0] & 7
        if mode == 3:
            key = ntp[24:32] if vn == 5 else ntp[40:48]  # client cookie / transmit ts
            pending[(src, dst, key)] = (ts, vn)
            org, rx = ntp[24:32], ntp[32:40]
            if vn == 4 and any(org) and any(rx) and rx != key:
                pending_i[(src, dst, rx)] = (org, ts, key)  # interleaved request (RFC 9769 section 2)
        elif mode == 4:
            key = ntp[24:32]  # v5 client cookie, or v4 origin timestamp: same octets
            stratum = ntp[1]
            era = ntp[13] if vn == 5 else None
            req = pending.pop((dst, src, key), None)
            if req is None:
                ireq = pending_i.pop((dst, src, key), None)
                if ireq is None or stratum == 0:
                    continue
                named, c1_now, tx_now = ireq
                pending.pop((dst, src, tx_now), None)
                rows = out.setdefault((dst, src), [])
                t2_now = _ntp_ns(struct.unpack_from("!Q", ntp, 32)[0], c1_now, era)
                prev = done.pop((dst, src, named), None)
                if prev is not None:  # the transmit timestamp is the precise one of the previous response
                    c1, t2, c4, row = prev
                    t3 = _ntp_ns(struct.unpack_from("!Q", ntp, 40)[0], c1, era)
                    new = (c4 / 1e9, ((t2 - c1) + (t3 - c4)) / 2e9, ((c4 - c1) - (t3 - t2)) / 1e9,
                           float(stratum), float(vn), 1.0)
                    if row < 0:
                        rows.append(new)
                    else:
                        rows[row] = new
                done[(dst, src, ntp[32:40])] = (c1_now, t2_now, ts, -1)  # completed by the next response
                continue
            c1, _ = req
            t2 = _ntp_ns(struct.unpack_from("!Q", ntp, 32)[0], c1, era)
            t3 = _ntp_ns(struct.unpack_from("!Q", ntp, 40)[0], c1, era)
            if stratum == 0 or t3 <= 0:
                continue  # KoD / unsynchronised
            c4 = ts
            offset = ((t2 - c1) + (t3 - c4)) / 2e9
            delay = ((c4 - c1) - (t3 - t2)) / 1e9
            rows = out.setdefault((dst, src), [])
            rows.append((c4 / 1e9, offset, delay, float(stratum), float(vn), 0.0))
            if vn == 4:
                done[(dst, src, ntp[32:40])] = (c1, t2, c4, len(rows) - 1)
    for rows in out.values():
        rows.sort()
    return out


def parse_capture(data: bytes, name: str = "capture") -> List[TimeSeries]:
    """NTP and PTP time series found in a capture (one per client/server or slave/master)."""
    from .ptp import parse_ptp

    series = []
    for (client, server), rows in ntp_exchanges(data).items():
        a = np.array(rows)
        s = TimeSeries(a[:, 0], a[:, 1], name=f"{name} [{client} -> {server}]", source_format="pcap",
                       extra={"delay": a[:, 2], "stratum": a[:, 3], "version": a[:, 4], "interleaved": a[:, 5]},
                       meta={"peer": server, "client": client, "protocol": "ntp",
                             "note": "offset of server relative to the capture host clock"})
        series.append(s.sorted())
    series += parse_ptp(data, name)
    if not series:
        raise ValueError("no matched NTP exchanges or PTP flows in capture")
    return series
