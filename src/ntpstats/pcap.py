# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""NTP exchanges from packet captures (pcap and pcapng), standard library only.

Client requests (mode 3) are matched with server responses (mode 4) by the
echoed origin timestamp (NTPv3/v4) or client cookie (NTPv5). Offsets are
computed from the server timestamps T2/T3 in the response and the *capture*
timestamps of the two packets as T1/T4::

    offset = ((T2 - c1) + (T3 - c4)) / 2      delay = (c4 - c1) - (T3 - T2)

so the result is the offset of the server relative to the capture host's
clock, independent of what the client software believes, and it keeps
working when the client randomises its transmit timestamp (RFC 9109 /
data-minimisation). With hardware timestamps in the capture (pcapng
``if_tsresol`` nanosecond resolution, ``tcpdump -j adapter_unsynced``) this
measures the path without software timestamping noise.

Supported link types: Ethernet (with 802.1Q/802.1ad tags), Linux cooked
v1/v2, raw IPv4/IPv6, BSD loopback. IPv4 and IPv6 (without extension headers)
over UDP port 123. IP fragments are ignored.
"""

from __future__ import annotations

import struct
from collections import OrderedDict
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from .series import TimeSeries

NTP_UNIX_DELTA = 2208988800
_ERA = 1 << 32
PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1e-6),
    b"\xa1\xb2\xc3\xd4": (">", 1e-6),
    b"\x4d\x3c\xb2\xa1": ("<", 1e-9),
    b"\xa1\xb2\x3c\x4d": (">", 1e-9),
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"


def is_capture(head: bytes) -> bool:
    return head[:4] in PCAP_MAGICS or head[:4] == PCAPNG_MAGIC


# ------------------------------------------------------------ file readers
def _pcap_packets(data: bytes) -> Iterator[Tuple[float, int, bytes]]:
    endian, res = PCAP_MAGICS[data[:4]]
    linktype = struct.unpack(endian + "I", data[20:24])[0] & 0x0FFFFFFF
    off = 24
    rec = struct.Struct(endian + "IIII")
    while off + 16 <= len(data):
        sec, frac, incl, _orig = rec.unpack_from(data, off)
        off += 16
        yield sec + frac * res, linktype, data[off: off + incl]
        off += incl


def _pcapng_packets(data: bytes) -> Iterator[Tuple[float, int, bytes]]:
    off = 0
    endian = "<"
    ifaces: List[Tuple[int, float]] = []
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
            tsres = 1e-6
            opt = 8
            while opt + 4 <= len(body):
                code, olen = struct.unpack_from(endian + "HH", body, opt)
                if code == 0:
                    break
                if code == 9 and olen >= 1:  # if_tsresol
                    v = body[opt + 4]
                    tsres = 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
                opt += 4 + ((olen + 3) & ~3)
            ifaces.append((linktype, tsres))
        elif btype_i == 6 and ifaces:  # Enhanced Packet Block
            ifid, tshi, tslo, caplen, _ = struct.unpack_from(endian + "IIIII", body, 0)
            linktype, tsres = ifaces[ifid] if ifid < len(ifaces) else ifaces[0]
            ts = ((tshi << 32) | tslo) * tsres
            yield ts, linktype, body[20: 20 + caplen]
        elif btype_i == 3 and ifaces:  # Simple Packet Block: no timestamp
            pass
        off += blen


def packets(data: bytes) -> Iterator[Tuple[float, int, bytes]]:
    if data[:4] in PCAP_MAGICS:
        return _pcap_packets(data)
    if data[:4] == PCAPNG_MAGIC:
        return _pcapng_packets(data)
    raise ValueError("not a pcap/pcapng file")


# ---------------------------------------------------------- dissection
def _ip_payload(linktype: int, frame: bytes):
    """Return (src, dst, udp_sport, udp_dport, payload) or None."""
    p = 0
    if linktype == 1:  # Ethernet
        if len(frame) < 14:
            return None
        et = struct.unpack_from("!H", frame, 12)[0]
        p = 14
        while et in (0x8100, 0x88A8, 0x9100) and len(frame) >= p + 4:
            et = struct.unpack_from("!H", frame, p + 2)[0]
            p += 4
    elif linktype == 113:  # Linux cooked v1
        et = struct.unpack_from("!H", frame, 14)[0]
        p = 16
    elif linktype == 276:  # Linux cooked v2
        et = struct.unpack_from("!H", frame, 0)[0]
        p = 20
    elif linktype in (101, 12, 228, 229):  # raw IP
        et = 0x0800 if frame[0] >> 4 == 4 else 0x86DD
    elif linktype == 0:  # BSD loopback
        fam = struct.unpack_from("<I", frame, 0)[0]
        et = 0x0800 if fam == 2 else 0x86DD
        p = 4
    else:
        return None
    if et == 0x0800:
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
    elif et == 0x86DD:
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


def _v6(b: bytes) -> str:
    words = struct.unpack("!8H", b)
    return ":".join(f"{w:x}" for w in words)


def _ntp_ts(raw: int, ref: float, era: Optional[int] = None) -> float:
    base = (raw >> 32) + (raw & 0xFFFFFFFF) / _ERA - NTP_UNIX_DELTA
    if era is not None:
        return base + era * _ERA
    return base + round((ref - base) / _ERA) * _ERA


def ntp_exchanges(data: bytes, port: int = 123) -> Dict[Tuple[str, str], list]:
    """Matched client/server exchanges per (client, server) pair."""
    pending: Dict[Tuple[str, str, bytes], Tuple[float, int]] = {}
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
        elif mode == 4:
            key = ntp[24:32]  # v5 client cookie, or v4 origin timestamp: same octets
            req = pending.pop((dst, src, key), None)
            if req is None:
                continue
            c1, _ = req
            stratum = ntp[1]
            if vn == 5:
                era = ntp[13]
                t2 = _ntp_ts(struct.unpack_from("!Q", ntp, 32)[0], c1, era)
                t3 = _ntp_ts(struct.unpack_from("!Q", ntp, 40)[0], c1, era)
            else:
                t2 = _ntp_ts(struct.unpack_from("!Q", ntp, 32)[0], c1)
                t3 = _ntp_ts(struct.unpack_from("!Q", ntp, 40)[0], c1)
            if stratum == 0 or t3 <= 0:
                continue  # KoD / unsynchronised
            c4 = ts
            offset = ((t2 - c1) + (t3 - c4)) / 2
            delay = (c4 - c1) - (t3 - t2)
            out.setdefault((dst, src), []).append((c4, offset, delay, float(stratum), float(vn)))
    return out


def parse_capture(data: bytes, name: str = "capture") -> List[TimeSeries]:
    series = []
    for (client, server), rows in ntp_exchanges(data).items():
        a = np.array(rows)
        s = TimeSeries(a[:, 0], a[:, 1], name=f"{name} [{client} -> {server}]", source_format="pcap",
                       extra={"delay": a[:, 2], "stratum": a[:, 3], "version": a[:, 4]},
                       meta={"peer": server, "client": client,
                             "note": "offset of server relative to the capture host clock"})
        series.append(s.sorted())
    if not series:
        raise ValueError("no matched NTP client/server exchanges in capture")
    return series
