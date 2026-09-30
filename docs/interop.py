#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Query public servers with every client ntpstats has (NTP, NTS, NTS pool, NTPv5, Roughtime); print a Markdown report.

Used by the "Live interop" GitHub workflow. Sends only a handful of packets
per server.
"""

import socket
import time

from ntpstats.analysis import format_seconds
from ntpstats.sntp import NTPError, query, query_interleaved, supports_v5

NTP4 = ["time.cloudflare.com", "time.google.com", "ptbtime1.ptb.de", "time.nist.gov", "pool.ntp.org", "ntp.ubuntu.com"]
NTS = ["time.cloudflare.com", "nts.netnod.se", "ptbtime1.ptb.de", "ntppool1.time.nl", "ntp.3eck.net"]
NTS_POOL = "srv.experimental.ntspooltest.org"  # Trifecta Tech Foundation experimental NTS pool
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

    print("\n### Interleaved mode (RFC 9769)\n")
    row(["server", "interleaved", "offset", "delay"])
    row(["---"] * 4)
    for s in NTP4:
        try:
            r = query_interleaved(s, timeout=3, family=socket.AF_INET)
            row([s, "yes" if r.interleaved else "no (basic)", format_seconds(r.offset), format_seconds(r.delay)])
        except (NTPError, OSError) as exc:
            row([s, f"error: {exc}", "", ""])
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

    print(f"\n### NTS pool (draft-ietf-ntp-nts-keyexchange-pool-01, {NTS_POOL})\n")
    row(["session", "NTP server assigned", "denied", "offset", "delay"])
    row(["---"] * 5)
    if NTSSession is None:
        row(["", "nts extra not installed", "", "", ""])
    else:
        from ntpstats.nts import pool_sessions

        try:
            for k, sess in enumerate(pool_sessions(NTS_POOL, n=2, timeout=5, family=socket.AF_INET)):
                r = sess.query()
                row([k + 1, f"{sess.keys.server}:{sess.keys.port}", ", ".join(sess.deny) or "-",
                     format_seconds(r.offset), format_seconds(r.delay)])
        except Exception as exc:
            row(["", f"error: {type(exc).__name__}: {exc}", "", "", ""])

    print("\n### Roughtime (draft-ietf-ntp-roughtime-19, chained, two rounds)\n")
    row(["server", "version", "MIDP (UTC)", "radius", "offset", "rtt", "Merkle leaf"])
    row(["---"] * 7)
    try:
        from ntpstats import roughtime as rt

        m = rt.measure(rt.load_servers(), rounds=2, timeout=3, family=socket.AF_INET, spacing=0.5)
        for r in m.responses:
            row([r.server, hex(r.version), time.strftime("%H:%M:%S", time.gmtime(r.midp)), f"{r.radi:g} s",
                 f"{r.offset:+.3f} s", format_seconds(r.rtt), r.leaf])
        for name, err in m.errors:
            row([name, f"error: {err}", "", "", "", "", ""])
        b = m.local_bound()
        print(f"\n{len(m.responses)} signed responses, "
              + ("consistent" if m.consistent else f"**{len(m.violations)} causal violations**")
              + (f"; runner clock error within [{b[0]:+.3f}, {b[1]:+.3f}] s" if b else ""))
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
