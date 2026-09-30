# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
import pytest
from capture_util import exchanges, pcap_bytes, pcapng_bytes

from ntpstats.parsers import load


@pytest.mark.parametrize("builder", [pcap_bytes, lambda f: pcap_bytes(f, nano=True), pcapng_bytes])
@pytest.mark.parametrize("version", [4, 5])
def test_capture_offset_and_delay(builder, version, tmp_path):
    frames = exchanges(true_offset=0.003, fwd=0.010, back=0.014, version=version, vlan=version == 5)
    path = tmp_path / "cap.pcap"
    path.write_bytes(builder(frames))
    (s,) = load(str(path))
    assert s.source_format == "pcap" and len(s) == 5
    assert s.meta["peer"] == "192.0.2.10" and s.meta["client"] == "192.0.2.99"
    # asymmetric path: measured = true + (fwd - back)/2
    assert s.offset[0] == pytest.approx(0.003 + (0.010 - 0.014) / 2, abs=2e-6)
    assert s.extra["delay"][0] == pytest.approx(0.024, abs=2e-6)
    assert s.extra["version"][0] == version


def test_capture_from_bytes_and_unmatched_packets():
    frames = exchanges(n=3)
    frames.pop(1)  # drop the first response
    (s,) = load(pcap_bytes(frames))
    assert len(s) == 2


def test_capture_interleaved_mode_uses_precise_transmit_time():
    import struct

    from capture_util import ether, ntp64

    def pkt(mode, org, rx, tx):
        p = bytearray(48)
        p[0] = (4 << 3) | mode
        p[1] = 2 if mode == 4 else 0
        struct.pack_into("!QQQ", p, 24, org, rx, tx)
        return bytes(p)

    frames, prev = [], None
    for i in range(4):
        c1 = 1.8e9 + 16 * i
        t2 = c1 + 0.010 + 0.003
        t3 = t2 + 1e-5
        c4 = t3 - 0.003 + 0.010
        nonce = 0x5566778800000000 + i
        if prev is None:
            req = pkt(3, 0, 0, nonce)
            resp = pkt(4, nonce, ntp64(t2), ntp64(t3 + 0.001))  # basic: transmit stamped 1 ms late
        else:
            p_t2, p_t3, p_c4 = prev
            req = pkt(3, ntp64(p_t2), ntp64(p_c4), nonce)
            resp = pkt(4, ntp64(p_c4), ntp64(t2), ntp64(p_t3))  # interleaved: previous precise transmit
        frames.append((c1, ether("192.0.2.99", "192.0.2.10", 40000, 123, req)))
        frames.append((c4, ether("192.0.2.10", "192.0.2.99", 123, 40000, resp)))
        prev = (t2, t3, c4)
    (s,) = load(pcap_bytes(frames, nano=True))
    assert len(s) == 3 and list(s.extra["interleaved"]) == [1, 1, 1]  # the last needs a next response
    assert s.offset == pytest.approx([0.003] * 3, abs=2e-6) and s.extra["delay"] == pytest.approx([0.020] * 3, abs=2e-6)
