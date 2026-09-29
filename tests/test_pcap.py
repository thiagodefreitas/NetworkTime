# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
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
