#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Query public servers with every client ntpstats has; print a Markdown report.

Used by the "Live interop" GitHub workflow. Sends only a handful of packets
per server.
"""

import socket
import time

from ntpstats.analysis import format_seconds
from ntpstats.sntp import NTPError, query, supports_v5

NTP4 = ["time.cloudflare.com", "time.google.com", "ptbtime1.ptb.de", "time.nist.gov", "pool.ntp.org", "ntp.ubuntu.com"]
NTS = ["time.cloudflare.com", "nts.netnod.se", "ptbtime1.ptb.de", "ntppool1.time.nl", "ntp.3eck.net"]
V5 = ["time.cloudflare.com", "ptbtime1.ptb.de", "ntppool1.time.nl", "time.google.com"]


def row(cells):
    print("| " + " | ".join(str(c) for c in cells) + " |")


def main():
    print(f"## ntpstats live interop ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n")
    print("### NTPv4 (SNTP, random transmit timestamp)\n")
    row(["server", "address", "stratum", "refid", "offset", "delay", "root dist."])
    row(["---"] * 7)
    for s in NTP4:
        try:
            r = query(s, timeout=3, family=socket.AF_INET)
            row([s, r.address, r.stratum, r.refid, format_seconds(r.offset), format_seconds(r.delay),
                 format_seconds(r.root_delay / 2 + r.root_dispersion)])
        except (NTPError, OSError) as exc:
            row([s, "", "", "", f"error: {exc}", "", ""])
        time.sleep(1)

    print("\n### NTS (RFC 8915)\n")
    row(["server", "NTP host:port", "stratum", "offset", "delay", "cookies left"])
    row(["---"] * 6)
    try:
        from ntpstats.nts import NTSSession
    except ImportError:
        NTSSession = None
    for s in NTS:
        if NTSSession is None:
            row([s, "nts extra not installed", "", "", "", ""])
            continue
        try:
            sess = NTSSession(s, timeout=5, family=socket.AF_INET)
            r = sess.query()
            time.sleep(1)
            r2 = sess.query()  # second query exercises cookie renewal
            row([s, f"{sess.keys.server}:{sess.keys.port}", r.stratum, format_seconds(r2.offset),
                 format_seconds(r2.delay), sess.cookies_left])
        except Exception as exc:  # report, keep going
            row([s, f"error: {type(exc).__name__}: {exc}", "", "", "", ""])

    print("\n### NTPv5 (draft-ietf-ntp-ntpv5-09 upgrade probe)\n")
    row(["server", "offers v5", "v5 query"])
    row(["---"] * 3)
    for s in V5:
        try:
            ok = supports_v5(s, timeout=3, family=socket.AF_INET)
        except (NTPError, OSError) as exc:
            row([s, f"error: {exc}", ""])
            continue
        res = ""
        if ok:
            try:
                r = query(s, version=5, timeout=3, family=socket.AF_INET)
                res = f"offset {format_seconds(r.offset)}, {r.timescale}, draft {r.draft or '?'}"
            except (NTPError, OSError) as exc:
                res = f"error: {exc}"
        row([s, "yes" if ok else "no", res])
        time.sleep(1)


if __name__ == "__main__":
    main()
