# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""PTP (IEEE 1588-2008/2019) flows from packet captures.

Messages are read over UDP (event port 319, general port 320; IPv4 and IPv6)
and over Ethernet (EtherType 0x88F7, with VLAN tags). For each master and
slave port the capture yields a time series, measured from the **capture
host's clock** as the NTP analysis is:

* ``t1`` is the master's Sync origin (the Sync itself for one-step clocks,
  the Follow_Up for two-step clocks), ``c2`` the capture time of the Sync;
* ``c3`` is the capture time of the slave's Delay_Req, ``t4`` the master's
  receive timestamp from the Delay_Resp;
* correction fields are applied as IEEE 1588 prescribes (Sync + Follow_Up
  on the master-to-slave side, Delay_Resp on the slave-to-master side)::

      ms  = c2 - t1 - cf_sync              (one-way, includes the offset)
      sm  = t4 - c3 - cf_delay_resp
      mean_path_delay = (ms + sm) / 2      (from the Sync preceding each Delay_Req)
      offset (reference - local) = mean_path_delay - ms    (for every Sync)

  With the peer-delay mechanism (Pdelay_Req/Resp/Resp_Follow_Up, one- or
  two-step) the mean link delay replaces the mean path delay. With no delay
  messages the series is the one-way ``-ms`` (offset plus delay), which
  still serves packet-delay-variation analysis (G.8260 FPP).

When the capture is taken at the slave, "local" is the slave's clock as the
capture timestamps it; with hardware timestamps (``tcpdump -j
adapter_unsynced``, nanosecond pcapng) this is the PHC. PTP timestamps are
on the PTP timescale (TAI): the UTC offset comes from Announce messages
(``currentUtcOffset``) or, without Announce, is inferred when the one-way
times are 30-45 s. Messages carrying an AUTHENTICATION TLV (IEEE 1588-2019
annex P, used by NTS4PTP) are flagged; they are not verified.
"""

from __future__ import annotations

import bisect
import struct
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .pcap import link, ntp_over_ptp, packets, udp_payload
from .series import TimeSeries

EVENT_PORT, GENERAL_PORT = 319, 320
ETHERTYPE_PTP = 0x88F7
SYNC, DELAY_REQ, PDELAY_REQ, PDELAY_RESP, FOLLOW_UP, DELAY_RESP, PDELAY_RESP_FU, ANNOUNCE = 0, 1, 2, 3, 8, 9, 10, 11
MESSAGE_NAMES = {0: "Sync", 1: "Delay_Req", 2: "Pdelay_Req", 3: "Pdelay_Resp", 8: "Follow_Up", 9: "Delay_Resp",
                 10: "Pdelay_Resp_Follow_Up", 11: "Announce", 12: "Signaling", 13: "Management"}
_BODY = {SYNC: 44, DELAY_REQ: 44, FOLLOW_UP: 44, DELAY_RESP: 54, PDELAY_REQ: 54, PDELAY_RESP: 54,
         PDELAY_RESP_FU: 54, ANNOUNCE: 64}
#: AUTHENTICATION TLV types: IEEE 1588-2019 (0x8009) and the 2008 experimental annex K (0x2000)
AUTH_TLVS = (0x8009, 0x2000)
NS = 1_000_000_000


@dataclass
class Message:
    ts: int  # capture timestamp, ns
    mtype: int
    version: str  # "2.0" or "2.1"
    domain: int
    flags: int
    correction: float  # ns
    port: str  # sourcePortIdentity "clockid/port"
    seq: int
    raw: bytes
    transport: str  # "l2", "udp4", "udp6"
    src: str  # MAC or IP address
    auth: bool

    @property
    def two_step(self) -> bool:
        return bool(self.flags & 0x0200)

    def timestamp(self, off: int = 34) -> int:
        """10-byte PTP timestamp at ``off`` as ns on the PTP timescale."""
        hi, lo, ns = struct.unpack_from("!HII", self.raw, off)
        return ((hi << 32) | lo) * NS + ns

    def port_at(self, off: int) -> str:
        return _port_id(self.raw[off: off + 10])


def _port_id(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b[:8]) + f"/{struct.unpack_from('!H', b, 8)[0]}"


def _auth(raw: bytes, mtype: int, length: int) -> bool:
    off = _BODY.get(mtype)
    if off is None:
        return False
    while off + 4 <= length:
        tlv_type, tlv_len = struct.unpack_from("!HH", raw, off)
        if tlv_type in AUTH_TLVS:
            return True
        off += 4 + tlv_len
    return False


def decode(payload: bytes, ts: int, transport: str, src: str) -> Optional[Message]:
    """Decode a PTPv2 common header (34 octets) plus the raw message."""
    if len(payload) < 34:
        return None
    mtype = payload[0] & 0x0F
    vmin, vmaj = payload[1] >> 4, payload[1] & 0x0F
    if vmaj != 2:
        return None
    length = min(struct.unpack_from("!H", payload, 2)[0], len(payload))
    need = _BODY.get(mtype, 34)
    if length < need:
        return None
    raw = payload[:length]
    return Message(
        ts=ts, mtype=mtype, version=f"2.{vmin}", domain=payload[4],
        flags=struct.unpack_from("!H", payload, 6)[0],
        correction=struct.unpack_from("!q", payload, 8)[0] / 65536.0,
        port=_port_id(payload[20:30]), seq=struct.unpack_from("!H", payload, 30)[0],
        raw=raw, transport=transport, src=src, auth=_auth(raw, mtype, length),
    )


def messages(data: bytes) -> List[Message]:
    """All PTP messages in a capture, in capture order."""
    out = []
    for ts, lt, frame in packets(data):
        lk = link(lt, frame)
        if lk is None:
            continue
        if lk.ethertype == ETHERTYPE_PTP:
            m = decode(frame[lk.offset:], ts, "l2", lk.src)
        else:
            u = udp_payload(frame, lk)
            if u is None or u[3] not in (EVENT_PORT, GENERAL_PORT):
                continue
            if u[3] == EVENT_PORT and ntp_over_ptp(u[4]) is not None:
                continue  # NTP over PTP (RFC 10030): an NTP exchange, analysed by ntpstats.pcap
            m = decode(u[4], ts, "udp6" if lk.ethertype == 0x86DD else "udp4", u[0])
        if m is not None:
            out.append(m)
    out.sort(key=lambda m: m.ts)
    return out


# ---------------------------------------------------------------- analysis
@dataclass
class _Sync:
    c2: int
    t1: Optional[int]
    cf: float
    seq: int
    auth: bool
    two_step: bool


def _utc_offsets(msgs: List[Message]) -> Dict[Tuple[int, str], Tuple[int, str]]:
    """(domain, master) -> (UTC offset in s, source) from Announce messages."""
    out: Dict[Tuple[int, str], Tuple[int, str]] = {}
    for m in msgs:
        if m.mtype != ANNOUNCE:
            continue
        ptp_timescale = bool(m.flags & 0x0008)
        valid = bool(m.flags & 0x0004)
        off = struct.unpack_from("!h", m.raw, 44)[0]
        if not ptp_timescale:
            out[(m.domain, m.port)] = (0, "announce (ARB timescale)")
        else:
            out[(m.domain, m.port)] = (off if valid else 37, "announce" if valid else "announce (offset not valid, 37 s assumed)")
    return out


def _syncs(msgs: List[Message]) -> Dict[Tuple[int, str], List[_Sync]]:
    """Complete Syncs per (domain, master port), in capture order."""
    pending: Dict[Tuple[int, str, int], _Sync] = {}
    out: Dict[Tuple[int, str], List[_Sync]] = defaultdict(list)
    for m in msgs:
        key = (m.domain, m.port, m.seq)
        if m.mtype == SYNC:
            s = _Sync(c2=m.ts, t1=None if m.two_step else m.timestamp(), cf=m.correction, seq=m.seq,
                      auth=m.auth, two_step=m.two_step)
            if s.t1 is None:
                pending[key] = s
            else:
                out[(m.domain, m.port)].append(s)
        elif m.mtype == FOLLOW_UP:
            fu = pending.pop(key) if key in pending else None
            if fu is not None:
                s = fu
                s.t1 = m.timestamp()
                s.cf += m.correction
                s.auth = s.auth or m.auth
                out[(m.domain, m.port)].append(s)
    for v in out.values():
        v.sort(key=lambda s: s.c2)
    return out


def _e2e(msgs: List[Message]) -> Dict[Tuple[int, str, str], List[Tuple[int, int, float]]]:
    """(domain, master, slave) -> [(c3, t4, cf_resp)] from Delay_Req/Delay_Resp pairs."""
    reqs: Dict[Tuple[int, str, int], int] = {}
    out: Dict[Tuple[int, str, str], List[Tuple[int, int, float]]] = defaultdict(list)
    for m in msgs:
        if m.mtype == DELAY_REQ:
            reqs[(m.domain, m.port, m.seq)] = m.ts
        elif m.mtype == DELAY_RESP:
            slave = m.port_at(44)
            c3 = reqs.get((m.domain, slave, m.seq))
            if c3 is not None:
                out[(m.domain, m.port, slave)].append((c3, m.timestamp(), m.correction))
    return out


def _p2p(msgs: List[Message]) -> Dict[Tuple[int, str], List[Tuple[int, float]]]:
    """(domain, requester) -> [(c1, mean link delay ns)] from peer-delay exchanges."""
    reqs: Dict[Tuple[int, str, int], int] = {}
    resps: Dict[Tuple[int, str, int], Tuple[int, int, float]] = {}
    out: Dict[Tuple[int, str], List[Tuple[int, float]]] = defaultdict(list)
    for m in msgs:
        if m.mtype == PDELAY_REQ:
            reqs[(m.domain, m.port, m.seq)] = m.ts
        elif m.mtype == PDELAY_RESP:
            req = m.port_at(44)
            key = (m.domain, req, m.seq)
            c1 = reqs.get(key)
            if c1 is None:
                continue
            if m.two_step:
                resps[key] = (m.ts, m.timestamp(), m.correction)
            else:  # one-step: the responder put its turnaround time into the correction field
                out[(m.domain, req)].append((c1, ((m.ts - c1) - m.correction) / 2))
        elif m.mtype == PDELAY_RESP_FU:
            key = (m.domain, m.port_at(44), m.seq)
            r = resps.pop(key, None)
            c1 = reqs.get(key)
            if r is None or c1 is None:
                continue
            c4, t2, cf_resp = r
            t3 = m.timestamp()
            out[(m.domain, key[1])].append((c1, ((c4 - c1) - (t3 - t2) - cf_resp - m.correction) / 2))
    return out


def _infer_utc(syncs: List[_Sync]) -> Tuple[int, str]:
    # TAI is ahead of UTC: the origin times lead the capture times by the UTC offset
    d = np.median([s.t1 - s.c2 for s in syncs if s.t1 is not None]) / NS
    if 30.0 < d < 45.0:
        return int(round(d)), "inferred from Sync timing"
    return 0, "none"


def _series(name, t, offset, extra, meta) -> TimeSeries:
    return TimeSeries(t=np.asarray(t, float), offset=np.asarray(offset, float), name=name, source_format="pcap",
                      extra={k: np.asarray(v, float) for k, v in extra.items()}, meta=meta).sorted()


def parse_ptp(data: bytes, name: str = "capture") -> List[TimeSeries]:
    """One :class:`TimeSeries` per PTP master/slave flow in a capture (possibly none)."""
    msgs = messages(data)
    if not msgs:
        return []
    utc = _utc_offsets(msgs)
    syncs = _syncs(msgs)
    e2e = _e2e(msgs)
    p2p = _p2p(msgs)
    versions = sorted({m.version for m in msgs})
    transports = sorted({m.transport for m in msgs})
    out: List[TimeSeries] = []
    for (domain, master), ss in syncs.items():
        if not ss:
            continue
        utc_off, utc_src = utc.get((domain, master)) or _infer_utc(ss)
        shift = utc_off * NS
        c2 = np.array([s.c2 for s in ss], dtype=np.int64)
        ms = np.array([(s.c2 - (s.t1 - shift)) - s.cf for s in ss if s.t1 is not None], dtype=float)
        base = {"protocol": "ptp", "domain": domain, "peer": master, "master": master,
                "ptp_version": ",".join(versions), "transport": ",".join(transports),
                "two_step": bool(ss[0].two_step), "utc_offset_s": utc_off, "utc_offset_source": utc_src,
                "authenticated": float(np.mean([s.auth for s in ss])),
                "sync_interval_s": float(np.median(np.diff(c2)) / NS) if len(ss) > 1 else float("nan")}
        flows = 0
        # end-to-end delay mechanism
        for (d2, m2, slave), ex in e2e.items():
            if d2 != domain or m2 != master:
                continue
            mpd_t, mpd_v, sm_v = [], [], []
            for c3, t4, cf in sorted(ex):
                i = bisect.bisect_right(c2, c3) - 1
                if i < 0:
                    continue
                sm = ((t4 - shift) - c3) - cf
                mpd_t.append(c3)
                mpd_v.append((ms[i] + sm) / 2)
                sm_v.append(sm)
            if not mpd_t:
                continue
            j = np.searchsorted(np.array(mpd_t, dtype=np.int64), c2, side="right") - 1
            ok = j >= 0
            mpd = np.array(mpd_v)[j[ok]]
            out.append(_series(
                f"{name} [PTP d{domain} {master} -> {slave}]", c2[ok] / 1e9, (mpd - ms[ok]) / 1e9,
                {"delay": 2 * mpd / 1e9, "mean_path_delay": mpd / 1e9, "ms_delay": ms[ok] / 1e9,
                 "sm_delay": np.array(sm_v)[j[ok]] / 1e9, "correction": np.array([s.cf for s in ss])[ok] / 1e9,
                 "sequence": np.array([s.seq for s in ss])[ok], "authenticated": np.array([s.auth for s in ss])[ok]},
                dict(base, slave=slave, client=slave, delay_mechanism="E2E",
                     note="offset of the master relative to the capture host clock")))
            flows += 1
        # peer-to-peer delay mechanism
        for (d2, requester), ld in p2p.items():
            if d2 != domain or flows:
                continue
            ld.sort()
            lt = np.array([x[0] for x in ld], dtype=np.int64)
            lv = np.array([x[1] for x in ld])
            j = np.searchsorted(lt, c2, side="right") - 1
            ok = j >= 0
            if not ok.any():
                continue
            mld = lv[j[ok]]
            out.append(_series(
                f"{name} [PTP d{domain} {master} -> {requester} P2P]", c2[ok] / 1e9, (mld - ms[ok]) / 1e9,
                {"delay": 2 * mld / 1e9, "mean_link_delay": mld / 1e9, "ms_delay": ms[ok] / 1e9,
                 "correction": np.array([s.cf for s in ss])[ok] / 1e9,
                 "sequence": np.array([s.seq for s in ss])[ok], "authenticated": np.array([s.auth for s in ss])[ok]},
                dict(base, slave=requester, client=requester, delay_mechanism="P2P",
                     note="offset of the master relative to the capture host clock; peer-delay requester "
                          + requester)))
            flows += 1
        if not flows:  # Sync only: one-way times for PDV analysis
            out.append(_series(
                f"{name} [PTP d{domain} {master} one-way]", c2 / 1e9, -ms / 1e9,
                {"ms_delay": ms / 1e9, "correction": np.array([s.cf for s in ss]) / 1e9,
                 "sequence": np.array([s.seq for s in ss]), "authenticated": np.array([s.auth for s in ss])},
                dict(base, delay_mechanism="none",
                     note="no delay measurements in the capture: offset includes the one-way path delay")))
    return out


def summary(data: bytes) -> Dict[str, object]:
    """Message counts per type, domains, versions and transports of a capture."""
    msgs = messages(data)
    counts: Dict[str, int] = defaultdict(int)
    for m in msgs:
        counts[MESSAGE_NAMES.get(m.mtype, f"type{m.mtype}")] += 1
    return {"messages": len(msgs), "by_type": dict(counts),
            "domains": sorted({m.domain for m in msgs}), "versions": sorted({m.version for m in msgs}),
            "transports": sorted({m.transport for m in msgs}),
            "authenticated": sum(m.auth for m in msgs)}
