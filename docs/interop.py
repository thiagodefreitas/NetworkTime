#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Query public servers with every client ntpstats has (NTP, NTS, NTS pool, NTPv5, Roughtime).

Prints a Markdown report and, with ``--jsonl FILE``, writes one JSON record per
probe (schema in ``data/interop/README.md``). Used by the "Live interop" GitHub
workflow, whose weekly records form the open dataset in ``data/interop/``.
Sends only a handful of packets per server.
"""

import argparse
import json
import os
import platform
import socket
import time

from ntpstats import __version__
from ntpstats.analysis import format_seconds
from ntpstats.sntp import NTPError, query, query_interleaved, supports_v5

NTP4 = ["time.cloudflare.com", "time.google.com", "ptbtime1.ptb.de", "time.nist.gov", "pool.ntp.org", "ntp.ubuntu.com"]
NTS = ["time.cloudflare.com", "nts.netnod.se", "ptbtime1.ptb.de", "ntppool1.time.nl", "ntp.3eck.net"]
NTS_POOL = "srv.experimental.ntspooltest.org"  # Trifecta Tech Foundation experimental NTS pool
V5 = ["time.cloudflare.com", "ptbtime1.ptb.de", "ntppool1.time.nl", "time.google.com"]
SCHEMA = 1

RECORDS = []
RUN = {}


def row(cells):
    print("| " + " | ".join(str(c) for c in cells) + " |")


def record(test, server, ok, error=None, **fields):
    """One dataset record; numeric fields in seconds, None when unknown."""
    rec = {"schema": SCHEMA, **RUN, "time": round(time.time(), 3), "test": test, "server": server, "ok": ok,
           "error": error}
    rec.update({k: v for k, v in fields.items() if v is not None})
    RECORDS.append(rec)
    return rec


def _ntp_fields(r):
    return {"address": r.address, "stratum": r.stratum, "refid": r.refid, "offset": r.offset, "delay": r.delay,
            "root_delay": r.root_delay, "root_dispersion": r.root_dispersion, "leap": r.leap, "version": r.version}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jsonl", help="append one JSON record per probe to this file")
    args = ap.parse_args(argv)
    RUN.update({"run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ntpstats": __version__,
                "runner": os.environ.get("RUNNER_NAME") and f"github-{os.environ.get('ImageOS', 'runner')}"
                or platform.node(), "family": "ipv4"})

    print(f"## ntpstats live interop ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n")
    print("### NTPv4 (SNTP, random transmit timestamp)\n")
    row(["server", "address", "stratum", "refid", "offset", "delay", "root dist."])
    row(["---"] * 7)
    for s in NTP4:
        try:
            r = query(s, timeout=3, family=socket.AF_INET)
            record("ntp4", s, True, **_ntp_fields(r))
            row([s, r.address, r.stratum, r.refid, format_seconds(r.offset), format_seconds(r.delay),
                 format_seconds(r.root_delay / 2 + r.root_dispersion)])
        except (NTPError, OSError) as exc:
            record("ntp4", s, False, str(exc))
            row([s, "", "", "", f"error: {exc}", "", ""])
        time.sleep(1)

    print("\n### Interleaved mode (RFC 9769)\n")
    row(["server", "interleaved", "offset", "delay"])
    row(["---"] * 4)
    for s in NTP4:
        try:
            r = query_interleaved(s, timeout=3, family=socket.AF_INET)
            record("interleaved", s, True, interleaved=r.interleaved, **_ntp_fields(r))
            row([s, "yes" if r.interleaved else "no (basic)", format_seconds(r.offset), format_seconds(r.delay)])
        except (NTPError, OSError) as exc:
            record("interleaved", s, False, str(exc))
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
            sess.query()
            time.sleep(1)
            r2 = sess.query()  # second query exercises cookie renewal
            record("nts", s, True, ntp_server=f"{sess.keys.server}:{sess.keys.port}",
                   cookies_left=sess.cookies_left, **_ntp_fields(r2))
            row([s, f"{sess.keys.server}:{sess.keys.port}", r2.stratum, format_seconds(r2.offset),
                 format_seconds(r2.delay), sess.cookies_left])
        except Exception as exc:  # report, keep going
            record("nts", s, False, f"{type(exc).__name__}: {exc}")
            row([s, f"error: {type(exc).__name__}: {exc}", "", "", "", ""])

    print("\n### NTPv5 (draft-ietf-ntp-ntpv5-09 upgrade probe)\n")
    row(["server", "offers v5", "v5 query"])
    row(["---"] * 3)
    for s in V5:
        try:
            ok = supports_v5(s, timeout=3, family=socket.AF_INET)
        except (NTPError, OSError) as exc:
            record("ntpv5", s, False, str(exc))
            row([s, f"error: {exc}", ""])
            continue
        res = ""
        fields = {"offers_v5": ok}
        if ok:
            try:
                r = query(s, version=5, timeout=3, family=socket.AF_INET)
                fields.update(_ntp_fields(r), timescale=r.timescale, draft=r.draft)
                res = f"offset {format_seconds(r.offset)}, {r.timescale}, draft {r.draft or '?'}"
            except (NTPError, OSError) as exc:
                res = f"error: {exc}"
                fields["v5_error"] = str(exc)
        record("ntpv5", s, True, **fields)
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
                record("nts-pool", NTS_POOL, True, session=k + 1, ntp_server=f"{sess.keys.server}:{sess.keys.port}",
                       denied=list(sess.deny), **_ntp_fields(r))
                row([k + 1, f"{sess.keys.server}:{sess.keys.port}", ", ".join(sess.deny) or "-",
                     format_seconds(r.offset), format_seconds(r.delay)])
        except Exception as exc:
            record("nts-pool", NTS_POOL, False, f"{type(exc).__name__}: {exc}")
            row(["", f"error: {type(exc).__name__}: {exc}", "", "", ""])

    print("\n### Roughtime (draft-ietf-ntp-roughtime-19, chained, two rounds)\n")
    row(["server", "protocol", "MIDP (UTC)", "radius", "offset", "rtt", "Merkle leaf"])
    row(["---"] * 7)
    try:
        from ntpstats import roughtime as rt

        m = rt.measure(rt.load_servers(), rounds=2, timeout=3, family=socket.AF_INET, spacing=0.5)
        for r in m.responses:
            record("roughtime", r.server, True, version=hex(r.version), midp=r.midp, radius=r.radi,
                   offset=r.offset, delay=r.rtt, merkle_leaf=r.leaf, protocol=r.protocol)
            row([r.server, r.protocol if r.protocol == "google" else hex(r.version), time.strftime("%H:%M:%S", time.gmtime(r.midp)), f"{r.radi:g} s",
                 f"{r.offset:+.3f} s", format_seconds(r.rtt), r.leaf])
        for name, err in m.errors:
            record("roughtime", name, False, err)
            row([name, f"error: {err}", "", "", "", "", ""])
        b = m.local_bound()
        record("roughtime-chain", "all", m.consistent, None if m.consistent else "causal violation",
               responses=len(m.responses), violations=len(m.violations),
               local_offset_interval=list(b) if b else None)
        print(f"\n{len(m.responses)} signed responses, "
              + ("consistent" if m.consistent else f"**{len(m.violations)} causal violations**")
              + (f"; runner clock error within [{b[0]:+.3f}, {b[1]:+.3f}] s" if b else ""))
    except Exception as exc:
        record("roughtime-chain", "all", False, f"{type(exc).__name__}: {exc}")
        print(f"error: {type(exc).__name__}: {exc}")

    if args.jsonl:
        os.makedirs(os.path.dirname(os.path.abspath(args.jsonl)), exist_ok=True)
        with open(args.jsonl, "a", encoding="utf-8") as fh:
            for rec in RECORDS:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        print(f"\n{len(RECORDS)} records appended to `{args.jsonl}`.")


if __name__ == "__main__":
    main()
