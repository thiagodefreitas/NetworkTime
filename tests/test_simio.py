# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Simulator interop: OMNeT++ vector files, ns-3 text, the INET oscillator mapping."""

import math
import os

import numpy as np
import pytest

from ntpstats import load, simio
from ntpstats.series import TimeSeries
from ntpstats.stability import compute

# Layout of an OMNeT++ 6 vector file (result file format version 3) as INET writes it for clocks.
VEC = """version 3
run General-0-20261002-10:00:00-1234
attr configname General
attr network TsnNetwork

vector 0 TsnNetwork.switch1.clock timeChanged:vector ETV
attr interpolationmode linear
attr source localSignal(timeChanged)
attr title "Clock time"
attr unit s
vector 1 "TsnNetwork.device 1.clock" timeChanged:vector ETV
attr unit s
vector 2 TsnNetwork.switch1.gptp pdelay:vector ETV
attr unit s
0	10	0.125	0.12500002
1	11	0.125	0.12499995
2	12	0.125	1.0e-07
0	20	0.250	0.25000001
1	21	0.250	0.24999998
0	30	0.375	0.375
1	31	0.375	0.37500003
"""

V2 = """version 2
run General-0
vector 7  "Net.host.clock"  "timeChanged:vector"  TV
7	1.0	1.0000001
7	2.0	2.0000003
"""


def test_inet_clock_vectors_become_time_error():
    series = load(VEC)
    assert [s.meta["peer"] for s in series] == ["TsnNetwork.switch1.clock", "TsnNetwork.device 1.clock"]
    s = series[0]
    assert s.source_format == "omnetpp-vec"
    np.testing.assert_allclose(-s.offset, [2e-8, 1e-8, 0.0], atol=1e-15)  # TE = clock time - simulation time
    np.testing.assert_allclose(s.t, [0.125, 0.25, 0.375])


def test_version_2_and_tv_columns():
    s, = load(V2)
    np.testing.assert_allclose(-s.offset, [1e-7, 3e-7], atol=1e-15)


def test_other_vectors_on_request():
    p, = simio.read_omnetpp_vec(VEC.splitlines(), vectors="pdelay*")
    assert p.meta["vector"] == "pdelay:vector" and p.offset[0] == pytest.approx(1e-7)
    only, = simio.read_omnetpp_vec(VEC.splitlines(), modules="*device*")
    assert only.meta["peer"] == "TsnNetwork.device 1.clock"
    with pytest.raises(simio.SimFormatError, match="Vectors in the file"):
        simio.read_omnetpp_vec(VEC.splitlines(), vectors="nothing*")


def test_file_without_clock_vectors_gives_every_vector():
    text = "version 3\nrun r\nvector 0 Net.app rtt:vector ETV\n0\t1\t1.0\t0.002\n0\t2\t2.0\t0.003\n"
    s, = load(text)
    assert s.meta["vector"] == "rtt:vector"


def test_vec_round_trip_keeps_time_and_columns(tmp_path):
    rng = np.random.default_rng(0)
    t = 1.7e9 + np.arange(50) * 16.0
    s = TimeSeries(t, rng.normal(0, 1e-6, 50), name="x", extra={"delay": 1e-3 + rng.random(50) * 1e-4},
                   meta={"peer": "192.0.2.1"})
    text = simio.write_omnetpp_vec([s])
    assert text.startswith("version 3\n") and "vector 0 192.0.2.1 offset:vector ETV" in text
    back = simio.read_omnetpp_vec(text.splitlines(), vectors="*")
    off = next(b for b in back if b.meta["vector"] == "offset:vector")
    np.testing.assert_allclose(off.t, t, rtol=0, atol=1e-6)
    np.testing.assert_allclose(off.offset, s.offset, rtol=1e-11)
    te = simio.write_omnetpp_vec([s], te=True)
    assert "timeError:vector" in te


def test_quoted_names():
    s = TimeSeries(np.arange(3.0), np.zeros(3), name="a b", meta={"peer": 'odd "name" here'})
    text = simio.write_omnetpp_vec([s])
    back, = simio.read_omnetpp_vec(text.splitlines(), vectors="offset*")
    assert back.meta["peer"] == 'odd_"name"_here'


def test_ns3_columns_read_back_as_csv(tmp_path):
    s = TimeSeries(1.7e9 + np.arange(5.0), np.array([1, 2, 3, 4, 5]) * 1e-6)
    p = tmp_path / "ns3.txt"
    p.write_text(simio.write_columns(s))
    back, = load(str(p), fmt="csv")
    np.testing.assert_allclose(back.offset, s.offset)
    np.testing.assert_allclose(back.t, np.arange(5.0))


def test_inet_random_drift_mapping_reproduces_rw_fm():
    """INET's RandomDriftOscillator with the mapped increment has the ADEV of the h(-2) it came from."""
    h_rw = 1e-22
    osc = simio.inet_oscillator({-2: h_rw}, freq_offset=2e-6, change_interval=1.0)
    assert "uniform(" in osc["ini"] and "initialDriftRate = 2ppm" in osc["ini"]
    assert osc["a_ppm"] == pytest.approx(math.sqrt(6 * math.pi ** 2 * h_rw * 1.0) * 1e6)
    devs = []
    for seed in range(8):
        x = simio.random_drift_phase(200_000, 1.0, osc["a_ppm"], 1.0, rng=seed)
        devs.append(compute(x, 1.0, "oadev", [100, 1000, 10000], ci=None).dev)
    measured = np.sqrt(np.mean(np.square(devs), axis=0))
    model = [2 * math.pi * math.sqrt(h_rw * tau / 6) for tau in (100, 1000, 10000)]
    np.testing.assert_allclose(measured, model, rtol=0.15)


def test_inet_mapping_lists_what_is_lost():
    osc = simio.inet_oscillator({2: 1e-20, 0: 1e-22, -2: 1e-25}, drift=1e-12, tau0=64.0)
    lost = {x["noise"] for x in osc["lost"]}
    assert lost == {"white PM", "white FM", "linear frequency drift"}
    assert "not represented: white PM" in osc["ini"] and "at 64 s" in osc["ini"]


def test_cli_noise_inet_and_convert(tmp_path, capsys):
    from ntpstats.cli import main

    ex = os.path.join(os.path.dirname(__file__), "..", "examples", "data")
    ini = tmp_path / "osc.ini"
    assert main(["noise", os.path.join(ex, "chrony-tracking.log"), "--bootstrap", "0", "--inet", str(ini)]) == 0
    assert "RandomDriftOscillator" in ini.read_text()
    vec = tmp_path / "p.vec"
    main(["convert", os.path.join(ex, "peerstats.example"), "--all-peers", "--to", "omnetpp-vec", "-o", str(vec)])
    s = load(str(vec))
    assert len(s) == 2 and s[0].t[0] > 1e9
    main(["convert", os.path.join(ex, "loopstats.2012"), "--to", "ns3", "-o", str(tmp_path / "l.txt")])
    assert (tmp_path / "l.txt").read_text().startswith("0.000000000 ")
