# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Synthetic files in the CGGTTS, RINEX clock, Circular T, RIPE Atlas and NTP Pool layouts (values invented)."""

import json

import numpy as np

CG_HEADER = """CGGTTS     GENERIC DATA FORMAT VERSION = 2E
REV DATE = 2026-01-01
RCVR = EXAMPLE-RX 1.0
CH = 20
IMS = EXAMPLE-RX
LAB = {lab}
X = 4000000.000 m
Y = 1000000.000 m
Z = 4800000.000 m
FRAME = ITRF
COMMENTS = synthetic example for ntpstats tests
INT DLY = 30.0 ns (GPS C1)     CAL_ID = NA
CAB DLY = 150.0 ns
REF DLY = 10.0 ns
REF = UTC({lab})
CKSUM = 00

SAT CL  MJD  STTIME TRKL ELV AZTH   REFSV      SRSV     REFSYS    SRSYS  DSG IOE MDTR SMDT MDIO SMDI MSIO SMSI ISG FR HC FRC CK
             hhmmss  s  .1dg .1dg    .1ns     .1ps/s     .1ns    .1ps/s .1ns     .1ns.1ps/s.1ns.1ps/s.1ns.1ps/s.1ns
"""


def cg_line(sat, mjd, sttime, refsv, refsys):
    body = (f"{sat} FF {mjd:5d} {sttime} 780 450 1800 {int(round(refsv)):+11d} {-10:+6d} {int(round(refsys)):+11d} "
            f"{3:+6d} {20:4d} {50:3d} {100:4d} {0:+4d} {300:4d} {0:+4d} {300:4d} {0:+4d} {15:3d} {0:2d} {0:2d} L1C ")
    return body + f"{sum(map(ord, body)) % 256:02X}"


def cggtts_pair(n_epochs=40, lab_offset_ns=12.5, seed=0):
    """Two stations seeing the same satellites; UTC(A) - UTC(B) = lab_offset_ns + a slow drift."""
    rng = np.random.default_rng(seed)
    a, b = [CG_HEADER.format(lab="LABA")], [CG_HEADER.format(lab="LABB")]
    truth = []
    for k in range(n_epochs):
        mjd = 61000 + (k * 16 * 60) // 86400
        sec = (k * 16 * 60) % 86400
        st = f"{sec // 3600:02d}{(sec % 3600) // 60:02d}00"
        ra = -48.0 + 0.01 * k  # REF(A) - GPS time, ns
        rb = ra - lab_offset_ns - 0.02 * k
        truth.append(ra - rb)
        for sat in ("G01", "G05", "G12", "G25"):
            sv = rng.normal(0, 5.0)  # satellite clock error, ns (cancels in common view)
            a.append(cg_line(sat, mjd, st, (ra + sv + rng.normal(0, 0.5)) * 10, (ra + rng.normal(0, 0.5)) * 10))
            b.append(cg_line(sat, mjd, st, (rb + sv + rng.normal(0, 0.5)) * 10, (rb + rng.normal(0, 0.5)) * 10))
    return "\n".join(a) + "\n", "\n".join(b) + "\n", np.array(truth) * 1e-9


RINEX_CLK = """     3.00           C                                       RINEX VERSION / TYPE
ntpstats            example                                 PGM / RUN BY / DATE
synthetic values for tests                                  COMMENT
    GPS                                                     TIME SYSTEM ID
     2    AR    AS                                          # / TYPES OF DATA
                                                            END OF HEADER
"""


def rinex_clock(n=48):
    lines = [RINEX_CLK.rstrip("\n")]
    for k in range(n):
        h, m = divmod(k * 5, 60)
        for kind, name, bias in (("AR", "LABA", 1.0e-9 + 1e-12 * k), ("AS", "G01", -2.5e-4 + 1e-11 * k)):
            lines.append(f"{kind} {name:<4} 2026 01 01 {h:02d} {m:02d}  0.000000  2   {bias: .12e}  1.0e-11")
    return "\n".join(lines) + "\n"


def circular_t(issue, mjd0, labs):
    mjds = [mjd0 + 5 * i for i in range(6)]
    out = [f"CIRCULAR T {issue}", "2026 JANUARY 10, 10h UTC", "",
           "1 - Difference between UTC and its local realizations UTC(k) and corresponding uncertainties.", "",
           "Date 2026    0h UTC         " + "".join(f"  D{i:02d}    " for i in range(6)) + "  Uncertainty/ns Notes",
           "       MJD                 " + "".join(f"{m:9d}" for m in mjds) + "     uA    uB    u",
           "Laboratory k                                         [UTC-UTC(k)]/ns", ""]
    for code, city, f in labs:
        vals = "".join(f"{f(m):9.1f}" if f(m) is not None else "        -" for m in mjds)
        out.append(f"{code:<4} ({city})".ljust(27) + vals + "    0.2   2.0   2.0")
    out += ["", "2 - International Atomic Time (TAI) and Coordinated Universal Time (UTC)", ""]
    return "\n".join(out) + "\n"


def ripe_atlas(n=30):
    items = []
    for k in range(n):
        t = 1_790_000_000 + 240 * k
        ntp = t + 2208988800
        items.append({"type": "ntp", "prb_id": 1001 + k % 2, "dst_addr": "192.0.2.123", "dst_name": "ntp.example",
                      "msm_id": 1, "af": 4, "stratum": 2, "root-delay": 1e-3, "root-dispersion": 2e-3,
                      "timestamp": t, "result": [{"origin-ts": ntp, "final-ts": ntp + 0.02, "rtt": 0.02,
                                                  "offset": -0.0015}, {"x": "*"}]})
    return json.dumps(items)


def ntppool(n=20):
    rows = ["ts_epoch,ts,offset,step,score,monitor_id,monitor_name,rtt,leap,error"]
    for k in range(n):
        mon = "mon-a" if k % 2 else "mon-b"
        rows.append(f"{1_790_000_000 + 60 * k},2026-09-21 00:00:00,{0.001 + 1e-5 * k:.6f},1,20,1,{mon},12.5,,")
    rows.append(f"{1_790_000_000 + 60 * n},2026-09-21 00:00:00,,-5,15,1,mon-a,,,i/o timeout")
    return "\n".join(rows) + "\n"
