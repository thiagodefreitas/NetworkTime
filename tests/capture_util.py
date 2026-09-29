# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Build tiny pcap/pcapng files with NTP exchanges for tests and examples."""

import struct

NTP_DELTA = 2208988800


def ntp64(t):
    sec = int(t // 1) + NTP_DELTA
    return ((sec % (1 << 32)) << 32) | int((t % 1) * (1 << 32))


def _ipv4_udp(src, dst, sport, dport, payload):
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 1, 0, 64, 17, 0,
                     bytes(map(int, src.split("."))), bytes(map(int, dst.split("."))))
    return ip + udp


def ether(src, dst, sport, dport, payload, vlan=False):
    eth = b"\x02" * 6 + b"\x04" * 6
    if vlan:
        eth += struct.pack("!HH", 0x8100, 100)
    return eth + struct.pack("!H", 0x0800) + _ipv4_udp(src, dst, sport, dport, payload)


def ntp_request(xmt_raw, version=4):
    pkt = bytearray(48)
    pkt[0] = (version << 3) | 3
    if version == 5:
        pkt[24:32] = xmt_raw.to_bytes(8, "big")  # client cookie
    else:
        pkt[40:48] = xmt_raw.to_bytes(8, "big")
    return bytes(pkt)


def ntp_response(origin_raw, t2, t3, version=4, stratum=2):
    pkt = bytearray(48)
    pkt[0] = (version << 3) | 4
    pkt[1] = stratum
    pkt[24:32] = origin_raw.to_bytes(8, "big")  # v4 origin / v5 client cookie
    struct.pack_into("!QQ", pkt, 32, ntp64(t2), ntp64(t3))
    return bytes(pkt)


def exchanges(true_offset=0.003, n=5, t0=1.8e9, fwd=0.010, back=0.014, version=4, vlan=False):
    """Frames (timestamp, bytes) for n exchanges seen on the client."""
    frames = []
    for i in range(n):
        c1 = t0 + 64 * i
        cookie = 0x1122334455660000 + i
        t2 = c1 + fwd + true_offset
        t3 = t2 + 1e-5
        c4 = t3 - true_offset + back
        frames.append((c1, ether("192.0.2.99", "192.0.2.10", 40000 + i, 123, ntp_request(cookie, version), vlan)))
        frames.append((c4, ether("192.0.2.10", "192.0.2.99", 123, 40000 + i, ntp_response(cookie, t2, t3, version), vlan)))
    return frames


def pcap_bytes(frames, nano=False):
    magic = 0xA1B23C4D if nano else 0xA1B2C3D4
    out = struct.pack("<IHHiIII", magic, 2, 4, 0, 0, 65535, 1)
    for ts, fr in frames:
        frac = round((ts % 1) * (1e9 if nano else 1e6))
        out += struct.pack("<IIII", int(ts), frac, len(fr), len(fr)) + fr
    return out


def pcapng_bytes(frames):
    def block(btype, body):
        body += b"\0" * ((4 - len(body) % 4) % 4)
        ln = 12 + len(body)
        return struct.pack("<II", btype, ln) + body + struct.pack("<I", ln)

    shb = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    opts = struct.pack("<HHB3x", 9, 1, 9) + struct.pack("<HH", 0, 0)  # if_tsresol = 10^-9
    idb = block(1, struct.pack("<HHI", 1, 0, 65535) + opts)
    out = shb + idb
    for ts, fr in frames:
        ns = round(ts * 1e9)
        out += block(6, struct.pack("<IIIII", 0, ns >> 32, ns & 0xFFFFFFFF, len(fr), len(fr)) + fr)
    return out
