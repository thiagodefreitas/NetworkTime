# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""PTP flows from packet captures (issue #19)."""

import numpy as np
import pytest
from ptp_util import NS, pcapng_ns, scenario

from ntpstats import ptp
from ntpstats.parsers import load


def one(frames, **kw):
    series = ptp.parse_ptp(pcapng_ns(frames), "cap")
    assert len(series) == 1, [s.name for s in series]
    return series[0]


@pytest.mark.parametrize("transport", ["l2", "udp4", "udp6"])
@pytest.mark.parametrize("two_step", [True, False])
def test_e2e_offset_recovers_capture_clock_error(transport, two_step):
    s = one(scenario(x_ns=250, two_step=two_step, transport=transport))
    # reference - local = -(local error); symmetric path, corrections applied
    np.testing.assert_allclose(s.offset, -250e-9, atol=1e-12)
    np.testing.assert_allclose(s.extra["mean_path_delay"], 1500e-9, atol=1e-12)
    assert s.meta["delay_mechanism"] == "E2E" and s.meta["two_step"] is two_step
    assert s.meta["utc_offset_s"] == 37 and s.meta["utc_offset_source"] == "announce"
    assert s.meta["transport"] == transport and s.meta["ptp_version"] == "2.1"
    assert s.meta["master"].startswith("00:1b:21:ff:fe:00:00:01/1")
    assert len(s) == 63  # the first Sync precedes the first delay measurement


def test_asymmetry_and_wander():
    s = one(scenario(x_ns=0, d_ms=2000, d_sm=1000, wander=lambda k: 10 * k, vlan=True))
    # asymmetric path: measured = true error + (d_ms - d_sm) / 2, sign as reference - local
    k = np.arange(1, 64)
    expected = -(10 * k + 500) * 1e-9
    # mean path delay is refreshed every 8 Syncs, from the Sync before each Delay_Req
    assert np.max(np.abs(s.offset - expected)) < 80e-9
    np.testing.assert_allclose(s.extra["ms_delay"], (2000 + 10 * k) * 1e-9, atol=1e-12)


def test_utc_offset_inferred_without_announce():
    s = one(scenario(announce_msg=False, utc=37))
    assert s.meta["utc_offset_s"] == 37 and "inferred" in s.meta["utc_offset_source"]
    np.testing.assert_allclose(s.offset, -250e-9, atol=1e-12)


@pytest.mark.parametrize("one_step", [False, True])
def test_peer_delay(one_step):
    s = one(scenario(mech="p2p", d_ms=400, link_ns=400, p2p_one_step=one_step))
    assert s.meta["delay_mechanism"] == "P2P"
    np.testing.assert_allclose(s.extra["mean_link_delay"], 400e-9, atol=1e-12)
    np.testing.assert_allclose(s.offset, -250e-9, atol=1e-12)


def test_sync_only_gives_one_way_times():
    s = one(scenario(mech="none"))
    assert s.meta["delay_mechanism"] == "none"
    np.testing.assert_allclose(s.extra["ms_delay"], (1500 + 250) * 1e-9, atol=1e-12)


def test_authentication_tlv_flagged():
    s = one(scenario(auth=True))
    assert s.meta["authenticated"] == 1.0
    assert one(scenario()).meta["authenticated"] == 0.0


def test_loader_mixes_ntp_and_ptp_and_summary(tmp_path):
    p = tmp_path / "ptp.pcapng"
    data = pcapng_ns(scenario())
    p.write_bytes(data)
    (s,) = load(str(p))
    assert s.meta["protocol"] == "ptp" and s.source_format == "pcap"
    info = ptp.summary(data)
    assert info["by_type"]["Sync"] == 64 and info["by_type"]["Follow_Up"] == 64
    assert info["by_type"]["Delay_Req"] == 8 and info["domains"] == [0]


def test_nanosecond_capture_timestamps_are_exact():
    # A float of POSIX seconds cannot hold 1 ns steps; the reader must keep integers.
    s = one(scenario(x_ns=1, n=16))
    np.testing.assert_allclose(s.offset, -1e-9, atol=1e-13)


def test_truncated_and_foreign_packets_are_ignored():
    fr = scenario(n=16)
    fr.append((fr[0][0] + 5, fr[0][1][:40]))  # truncated PTP frame
    fr.append((fr[0][0] + 7, bytes(60)))  # junk
    s = one(fr)
    assert len(s) == 15 and np.isfinite(s.offset).all()


def test_time_axis_is_capture_time():
    s = one(scenario(n=8))
    # first sample: Sync 1 (125 ms after Sync 0), after the first Delay_Req
    assert s.t[0] == pytest.approx(1_800_000_000 + 0.125 + (1500 + 300 + 250) / NS, abs=1e-6)
