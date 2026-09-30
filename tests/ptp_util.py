# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Build PTP captures with a known truth (integer-ns timestamps) for tests."""

import struct

NS = 1_000_000_000
MASTER = bytes.fromhex("001b21fffe000001")
SLAVE = bytes.fromhex("001b21fffe000002")
SWITCH = bytes.fromhex("001b21fffe0000aa")


def header(mtype, seq, clock, port=1, domain=0, two_step=False, cf_ns=0.0, length=44, minor=1,
           flags_extra=0, logint=0):
    flags = (0x0200 if two_step else 0) | flags_extra
    return struct.pack("!BBHBBHq4s8sHHBb", mtype, (minor << 4) | 2, length, domain, 0, flags,
                       int(round(cf_ns * 65536)), b"\0" * 4, clock, port, seq, 0, logint)


def ts(ns):
    sec, rem = divmod(int(ns), NS)
    return struct.pack("!HII", sec >> 32, sec & 0xFFFFFFFF, rem)


def msg(mtype, seq, clock, body=b"", tlvs=b"", **kw):
    base = {0: 44, 1: 44, 8: 44, 9: 54, 2: 54, 3: 54, 10: 54, 11: 64}[mtype]
    body = body.ljust(base - 34, b"\0")
    return header(mtype, seq, clock, length=base + len(tlvs), **kw) + body + tlvs


def auth_tlv():
    return struct.pack("!HH", 0x8009, 8) + b"\x01" * 8


def announce(seq, utc_offset=37, domain=0, valid=True, ptp_timescale=True):
    flags = (0x0008 if ptp_timescale else 0) | (0x0004 if valid else 0)
    body = ts(0) + struct.pack("!hB", utc_offset, 0) + b"\x80" + b"\xf8\xfe\xff\xff" + b"\x80" + MASTER + b"\0\0\x20"
    return msg(11, seq, MASTER, body, domain=domain, flags_extra=flags)


# --------------------------------------------------------------- framing
def _ipv4(src, dst, sport, dport, payload):
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0,
                     bytes(map(int, src.split("."))), bytes(map(int, dst.split("."))))
    return struct.pack("!H", 0x0800) + ip + udp


def _ipv6(src_last, dst, sport, dport, payload):
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    s = bytes.fromhex("20010db8000000000000000000000000")[:15] + bytes([src_last])
    d = bytes.fromhex("ff0e0000000000000000000000000181") if dst is None else dst
    ip = struct.pack("!IHBB16s16s", 6 << 28, len(udp), 17, 64, s, d)
    return struct.pack("!H", 0x86DD) + ip + udp


def frame(payload, transport="l2", sender=1, event=True, vlan=False):
    eth = bytes.fromhex("011b19000000") + bytes([2, 0, 0, 0, 0, sender])
    if vlan:
        eth += struct.pack("!HH", 0x8100, 7)
    port = 319 if event else 320
    if transport == "l2":
        return eth + struct.pack("!H", 0x88F7) + payload
    if transport == "udp4":
        return eth + _ipv4(f"192.0.2.{sender}", "224.0.1.129", port, port, payload)
    return eth + _ipv6(sender, None, port, port, payload)


def pcapng_ns(frames):
    def block(btype, body):
        body += b"\0" * ((4 - len(body) % 4) % 4)
        ln = 12 + len(body)
        return struct.pack("<II", btype, ln) + body + struct.pack("<I", ln)

    shb = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    opts = struct.pack("<HHB3x", 9, 1, 9) + struct.pack("<HH", 0, 0)
    idb = block(1, struct.pack("<HHI", 1, 0, 65535) + opts)
    out = shb + idb
    for t, fr in sorted(frames, key=lambda x: x[0]):
        out += block(6, struct.pack("<IIIII", 0, t >> 32, t & 0xFFFFFFFF, len(fr), len(fr)) + fr)
    return out


# --------------------------------------------------------------- scenario
def scenario(n=64, x_ns=250, d_ms=1500, d_sm=1500, res_ms=300, res_sm=200, two_step=True, mech="e2e",
             utc=37, announce_msg=True, transport="l2", vlan=False, auth=False, sync_ns=NS // 8,
             delay_every=8, t0=1_800_000_000 * NS, wander=None, p2p_one_step=False, link_ns=400):
    """Frames seen at the slave. ``x_ns`` is the slave/capture clock error (local - true);
    ``wander(k)`` optionally adds a time-varying error in ns at Sync k. TAI = UTC + ``utc``."""
    fr = []
    tai = utc * NS
    tl = auth_tlv() if auth else b""
    for k in range(n):
        x = x_ns + (wander(k) if wander else 0)
        T = t0 + k * sync_ns
        c2 = T + d_ms + res_ms + x
        if two_step:
            fr.append((c2, frame(msg(0, k, MASTER, two_step=True, cf_ns=res_ms, tlvs=tl), transport, 1, True, vlan)))
            fr.append((c2 + 1000, frame(msg(8, k, MASTER, ts(T + tai), tlvs=tl), transport, 1, False, vlan)))
        else:
            fr.append((c2, frame(msg(0, k, MASTER, ts(T + tai), cf_ns=res_ms, tlvs=tl), transport, 1, True, vlan)))
        if announce_msg and k % 16 == 0:
            fr.append((c2 + 2000, frame(announce(k // 16, utc), transport, 1, False, vlan)))
        if mech == "e2e" and k % delay_every == 0:
            q = k // delay_every
            Tq = T + sync_ns // 2
            c3 = Tq + x
            t4 = Tq + d_sm + res_sm + tai
            fr.append((c3, frame(msg(1, q, SLAVE, ts(0)), transport, 2, True, vlan)))
            resp = msg(9, q, MASTER, ts(t4) + SLAVE + struct.pack("!H", 1), cf_ns=res_sm)
            fr.append((c3 + 100_000, frame(resp, transport, 1, False, vlan)))
        if mech == "p2p" and k % delay_every == 0:
            q = k // delay_every
            Tq = T + sync_ns // 2
            c1 = Tq + x
            t2 = Tq + link_ns + 5 * NS  # responder clock: arbitrary offset, cancels
            turn = 3000
            t3 = t2 + turn
            c4 = Tq + link_ns + turn + link_ns + x
            fr.append((c1, frame(msg(2, q, SLAVE), transport, 2, True, vlan)))
            req_id = SLAVE + struct.pack("!H", 1)
            if p2p_one_step:
                fr.append((c4, frame(msg(3, q, SWITCH, ts(0) + req_id, cf_ns=turn), transport, 3, True, vlan)))
            else:
                fr.append((c4, frame(msg(3, q, SWITCH, ts(t2) + req_id, two_step=True), transport, 3, True, vlan)))
                fr.append((c4 + 500, frame(msg(10, q, SWITCH, ts(t3) + req_id), transport, 3, False, vlan)))
    return fr
