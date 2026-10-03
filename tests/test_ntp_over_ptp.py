"""NTP over PTP (RFC 10030) in packet captures: NTP TLV, Network Correction extension field, corrections."""

import numpy as np
import pytest
from capture_util import ether, network_correction_ef, ntp64, ntp_message, ntp_over_ptp_frames, pcap_bytes, ptp_with_ntp

from ntpstats.parsers import load
from ntpstats.pcap import _network_correction, ntp_over_ptp
from ntpstats.ptp import messages

LINK = 1e9


def _frames(theta=0.5e-3, d_rq=30e-6, d_rs=50e-6, cf_rq=10e-6, cf_rs=30e-6, n=4, with_ef=True, version=1):
    if with_ef and version == 1:
        return ntp_over_ptp_frames([theta] * n, [d_rq] * n, [d_rs] * n, [cf_rq] * n, [cf_rs] * n, interval=2.0)
    frames = []
    for i in range(n):
        c1 = 1.0e6 + 2 * i  # small epoch: floats keep sub-ns resolution
        nonce = 0x1122334400000000 + i
        req = ptp_with_ntp(ntp_message(3, tx=nonce, ef=network_correction_ef(0.0) if with_ef else None),
                           version=version)
        dur = (len(req) + 8 + 20 + 18) * 8 / LINK
        t2 = c1 + d_rq + theta
        t3 = t2 + 5e-6
        c4 = t3 - theta + d_rs
        resp_ntp = ntp_message(4, org=nonce, rx=ntp64(t2), tx=ntp64(t3), stratum=1,
                               ef=network_correction_ef(cf_rq + dur) if with_ef else None)
        frames.append((c1, ether("192.0.2.99", "192.0.2.10", 319, 319, req)))
        frames.append((c4, ether("192.0.2.10", "192.0.2.99", 319, 319,
                                 ptp_with_ntp(resp_ntp, correction_s=cf_rs, version=version))))
    return frames


def test_tlv_and_extension_field_decoding():
    ntp = ntp_message(4, ef=network_correction_ef(12.5e-6))
    inner = ntp_over_ptp(ptp_with_ntp(ntp, correction_s=3e-6))
    assert inner is not None
    msg, cf, domain = inner
    assert msg == ntp and domain == 123 and cf == pytest.approx(3e-6, abs=1e-15)
    assert _network_correction(msg) == pytest.approx(12.5e-6, abs=1e-9)
    assert ntp_over_ptp(b"\x01\x12" + bytes(60)) is None  # PTP without the NTP TLV


@pytest.mark.parametrize("version", [1, 0])
def test_corrections_remove_transparent_clock_delays(version):
    (s,) = load(pcap_bytes(_frames(version=version), nano=True))
    assert s.meta["transport"].startswith("ntp-over-ptp") and s.meta["corrected"] == 4
    # uncorrected: theta + (d_rq - d_rs)/2; corrected: the residual delays (20 us each way) are symmetric
    assert s.extra["offset_uncorrected"][0] == pytest.approx(0.5e-3 - 10e-6, abs=2e-9)
    assert s.offset == pytest.approx(np.full(4, 0.5e-3), abs=2e-9)
    assert s.extra["delay_uncorrected"][0] == pytest.approx(80e-6, abs=2e-9)
    assert s.extra["delay"][0] == pytest.approx(40e-6 + 40e-6 * 1e-4, abs=2e-9)
    assert s.extra["nc_response"][0] > 30e-6 and s.extra["nc_request"][0] > 10e-6


def test_without_network_correction_the_exchange_is_kept_uncorrected():
    (s,) = load(pcap_bytes(_frames(with_ef=False), nano=True))
    assert s.meta["corrected"] == 0 and np.isnan(s.extra["nc_request"]).all()
    assert s.offset[0] == pytest.approx(0.5e-3 - 10e-6, abs=2e-9)


def test_negative_corrected_delay_is_rejected():
    (s,) = load(pcap_bytes(_frames(cf_rs=200e-6), nano=True))  # correction larger than the measured delay
    assert s.offset[0] == pytest.approx(s.extra["offset_uncorrected"][0])
    assert s.extra["delay"][0] == pytest.approx(s.extra["delay_uncorrected"][0])


def test_ptp_analysis_ignores_ntp_over_ptp_messages():
    data = pcap_bytes(_frames(), nano=True)
    assert messages(data) == []
    series = load(data)
    assert len(series) == 1 and series[0].meta["protocol"] == "ntp"


def test_example_capture():
    import os

    path = os.path.join(os.path.dirname(__file__), os.pardir, "examples", "data", "ntp-over-ptp.pcap")
    (s,) = load(path)
    assert len(s) == 600 and s.meta["corrected"] == 600
    # transparent clocks corrected: the offset is far steadier than the uncorrected one
    assert np.std(np.diff(s.offset)) < 0.01 * np.std(np.diff(s.extra["offset_uncorrected"]))
