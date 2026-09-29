#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Generate example logs in the native formats of ntpd/NTPsec and chrony.

The underlying data are simulated (ntpstats.simulate) so the files are
reproducible and contain a known ground truth; the *layouts* follow the
documentation of ntpd 4.2.8 (``monopt.html``) and chrony 4.x
(``chrony.conf(5)``, ``log`` directive). Run from the repository root::

    python examples/make_example_logs.py
"""

import os
import time

import numpy as np

from ntpstats.simulate import PRESETS, ClockModel, PathModel, Scenario, simulate_ntp

OUT = os.path.join(os.path.dirname(__file__), "data")
NTP_UNIX = 2208988800


def mjd_sec(t):
    return int(t // 86400) + 40587, t % 86400


def chrony_ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


def main():
    os.makedirs(OUT, exist_ok=True)
    peers = {
        "192.0.2.10": Scenario(duration=12 * 3600, poll=64, seed=10),
        "198.51.100.7": Scenario(
            duration=12 * 3600, poll=64, seed=11,
            forward=PathModel(base=18e-3, queue_mean=4e-3, load=0.6),
            backward=PathModel(base=18e-3, queue_mean=1e-3, load=0.4),
        ),
    }
    clock = ClockModel(freq_offset=0.0, drift=0.0, white_fm_adev1=5e-10, rw_fm_adev1=2e-12)
    sims = {}
    for addr, sc in peers.items():
        sc.clock = clock
        sims[addr] = simulate_ntp(sc, name=addr)[0]

    # --- ntpd / NTPsec peerstats: MJD sec addr status offset delay disp jitter
    rows = []
    for i, (addr, s) in enumerate(sims.items()):
        status = "9614" if i == 0 else "9414"  # sys.peer / candidate
        for t, x, d in zip(s.t + i * 7.0, s.offset, s.extra["delay"]):
            day, sec = mjd_sec(t)
            rows.append((t, f"{day} {sec:.3f} {addr} {status} {x:.9f} {d:.9f} 0.000{np.random.randint(100, 999)}000 0.000{np.random.randint(100, 999)}000"))
    with open(os.path.join(OUT, "peerstats.example"), "w") as fh:
        fh.write("\n".join(r for _, r in sorted(rows)) + "\n")

    # --- ntpd rawstats: MJD sec src dst T1 T2 T3 T4 (NTP era seconds)
    s = sims["192.0.2.10"]
    with open(os.path.join(OUT, "rawstats.example"), "w") as fh:
        for t, x, d in list(zip(s.t, s.offset, s.extra["delay"]))[:300]:
            day, sec = mjd_sec(t)
            t1 = t - x + NTP_UNIX  # local clock reads true - offset
            t2 = t + d / 2 + NTP_UNIX
            t3 = t2 + 20e-6
            t4 = t1 + d + 20e-6
            fh.write(f"{day} {sec:.3f} 192.0.2.10 192.0.2.99 {t1:.9f} {t2:.9f} {t3:.9f} {t4:.9f} 0 4 4 1 6 -24 0.000000 0.000000 GPS\n")

    # --- chrony measurements.log (theta; positive = local clock slow, as ntpd)
    hdr = ("========================================================================================================================\n"
           "   Date (UTC) Time     IP Address   L St 123 567 ABCD  LP RP Score    Offset  Peer del. Peer disp.  Root del. Root disp. Refid     MTxRx\n"
           "========================================================================================================================\n")
    rows = []
    for addr, s in sims.items():
        for t, x, d in zip(s.t, s.offset, s.extra["delay"]):
            rows.append((t, f"{chrony_ts(t)} {addr:15s} N  2 111 111 1111   6  6 0.00 {x: .3e} {d: .3e}  1.200e-06  1.526e-05  1.068e-04 C0000201 4B K K"))
    with open(os.path.join(OUT, "chrony-measurements.log"), "w") as fh:
        fh.write(hdr + "\n".join(r for _, r in sorted(rows)) + "\n")

    # --- chrony tracking.log
    hdr = ("===============================================================================================================================\n"
           "   Date (UTC) Time     IP Address   St   Freq ppm   Skew ppm     Offset L Co  Offset sd Rem. corr. Root delay Root disp. Max. error\n"
           "===============================================================================================================================\n")
    s = sims["192.0.2.10"]
    rng = np.random.default_rng(3)
    freq = -3.54 + np.cumsum(rng.normal(0, 0.002, len(s)))
    resid = s.offset - np.convolve(s.offset, np.ones(16) / 16, mode="same")
    with open(os.path.join(OUT, "chrony-tracking.log"), "w") as fh:
        fh.write(hdr)
        for t, x, f, d in zip(s.t, resid, freq, s.extra["delay"]):
            fh.write(f"{chrony_ts(t)} 192.0.2.10       2 {f:10.3f} {0.05:10.3f} {-x: .3e} N  2  {abs(x) / 3: .3e} {0.0: .3e}  {d: .3e}  3.472e-04  {d / 2 + 3.5e-4: .3e}\n")
    # --- linuxptp: ptp4l + phc2sys stdout (offsets in ns, local - reference)
    from dataclasses import replace

    lan = replace(PRESETS["lan"], duration=1800, poll=1, seed=12,
                  clock=ClockModel(freq_offset=0, drift=0, white_fm_adev1=2e-10, rw_fm_adev1=0, white_pm=3e-9),
                  forward=PathModel(base=600e-9, queue_mean=40e-9, load=0.2),
                  backward=PathModel(base=600e-9, queue_mean=30e-9, load=0.2), server_noise=4e-9)
    ptp, _ = simulate_ntp(lan)
    mono0 = 5374018.0
    lines = []
    for i, (t, x, d) in enumerate(zip(ptp.t, ptp.offset, ptp.extra["delay"])):
        mono = mono0 + (t - ptp.t[0])
        state = 0 if i < 2 else (1 if i == 2 else 2)
        lines.append(f"ptp4l[{mono:.3f}]: master offset {int(round(-x * 1e9)):10d} s{state} freq {int(-38601 + 3 * np.sin(i / 60)):+7d} path delay {int(round(d / 2 * 1e9)):9d}")
        lines.append(f"phc2sys[{mono + 0.4:.3f}]: CLOCK_REALTIME phc offset {int(round(np.random.default_rng(i).normal(0, 12))):9d} s2 freq {-37046 + i % 5:+7d} delay {540 + i % 7:6d}")
    with open(os.path.join(OUT, "linuxptp.log"), "w") as fh:
        fh.write("ptp4l[5374017.500]: port 1 (eth0): INITIALIZING to LISTENING on INIT_COMPLETE\n")
        fh.write("\n".join(lines) + "\n")

    # --- chrony refclocks.log (PPS, cooked offset: positive = local slow)
    rng = np.random.default_rng(13)
    with open(os.path.join(OUT, "chrony-refclocks.log"), "w") as fh:
        fh.write("===============================================================================\n"
                 "   Date (UTC) Time         Refid  DP L P  Raw offset   Cooked offset      Disp.\n"
                 "===============================================================================\n")
        t0 = 1.7e9
        for i in range(3600):
            raw = rng.normal(0, 150e-9) + 2e-7 * np.sin(i / 600)
            fh.write(f"{chrony_ts(t0 + i)}.000000 PPS0    {i % 16:2d} N 1 {raw: .6e} {-raw + rng.normal(0, 5e-9): .6e}  1.000e-06\n")
    # --- packet capture of SNTP exchanges (client side), reusing the simulated peer
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "tests"))
    from capture_util import ether, ntp64, ntp_request, ntp_response, pcap_bytes

    s = sims["198.51.100.7"]
    frames = []
    for i, (t, x, d) in enumerate(list(zip(s.t, s.offset, s.extra["delay"]))[:240]):
        cookie = int.from_bytes(os.urandom(8), "big")
        fwd = d * 0.45
        t2 = t + fwd + x
        t3 = t2 + 2e-5
        c4 = t + d + 2e-5
        frames.append((t, ether("192.0.2.99", "198.51.100.7", 40000 + i % 20000, 123, ntp_request(cookie))))
        frames.append((c4, ether("198.51.100.7", "192.0.2.99", 123, 40000 + i % 20000, ntp_response(cookie, t2, t3))))
    with open(os.path.join(OUT, "ntp-capture.pcap"), "wb") as fh:
        fh.write(pcap_bytes(frames, nano=True))
    print(f"wrote example logs to {OUT}")


if __name__ == "__main__":
    main()
