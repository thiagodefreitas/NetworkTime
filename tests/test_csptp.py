"""CSPTP (client-server PTP, sdoId 0x300) exchanges in packet captures."""

import numpy as np
import pytest
from capture_util import csptp_exchange_frames, pcap_bytes

from ntpstats.parsers import load
from ntpstats.ptp import messages


@pytest.mark.parametrize("two_step", [True, False])
def test_csptp_offset_delay_and_corrections(two_step):
    data = pcap_bytes(csptp_exchange_frames(two_step=two_step), nano=True, epoch=1_790_000_000)
    (s,) = load(data)
    assert s.meta["protocol"] == "csptp" and s.meta["server"] == "192.0.2.10" and s.meta["client"] == "192.0.2.99"
    assert s.meta["utc_offset_s"] == 37  # PTP timescale against a UTC capture clock
    # residual path delays 20 us each way after the transparent-clock corrections: offset is the truth
    assert s.offset == pytest.approx(np.full(4, 0.4e-3), abs=2e-9)
    assert s.extra["delay"] == pytest.approx(np.full(4, 40e-6), abs=2e-9)
    assert s.extra["correction_request"][0] == pytest.approx(10e-6)
    assert s.extra["correction_response"][0] == pytest.approx(30e-6)
    assert s.meta["steps_removed"] == 1 and s.meta["grandmaster"].startswith("0a:0b")


def test_csptp_is_not_a_master_slave_flow():
    data = pcap_bytes(csptp_exchange_frames(), nano=True, epoch=1_790_000_000)
    assert all(m.sdo == 0x300 for m in messages(data))
    series = load(data)
    assert [s.meta["protocol"] for s in series] == ["csptp"]


def test_unanswered_requests_are_skipped():
    frames = csptp_exchange_frames(n=3)
    frames = [f for k, f in enumerate(frames) if k not in (1, 2)]  # first response and its Follow_Up lost
    (s,) = load(pcap_bytes(frames, nano=True, epoch=1_790_000_000))
    assert len(s) == 2
