# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Write the LaTeX tables of the preprint from data/*.json (run experiments.py first)."""

import collections
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "tables")
os.makedirs(OUT, exist_ok=True)


def load(name):
    with open(os.path.join(HERE, "data", name)) as fh:
        return json.load(fh)


def write(name, text):
    with open(os.path.join(OUT, name), "w") as fh:
        fh.write(text)


def aggregate(rows):
    """Mean and sample standard deviation over seeds of each (scenario, estimator) metric."""
    g = collections.defaultdict(list)
    for r in rows:
        g[(r["scenario"], r["estimator"])].append(r)
    out = {}
    for k, rs in g.items():
        a = {"runs": len(rs)}
        for m in ("rms", "bias", "max_abs"):
            v = np.array([r[m] for r in rs], dtype=float)
            a[m], a[m + "_std"] = float(v.mean()), float(v.std(ddof=1)) if v.size > 1 else 0.0
        out[k] = a
    return out


def sig(v, n=3):
    """``n`` significant digits, never in exponent notation."""
    if v == 0 or not np.isfinite(v):
        return "0"
    d = max(n - 1 - int(np.floor(np.log10(abs(v)))), 0)
    r = round(v, d - (0 if d else 0)) if d else round(v, n - 1 - int(np.floor(np.log10(abs(v)))))
    text = f"{r:.{d}f}"
    return text if abs(r) < 10000 else f"{r:,.0f}".replace(",", "{,}")


def nist():
    rows = load("e1_nist.json")
    by = collections.defaultdict(dict)
    for r in rows:
        by[r["kind"]][r["table"]] = r["max_rel_err"]
    names = {"adev": "ADEV", "oadev": "OADEV", "mdev": "MDEV", "tdev": "TDEV", "hdev": "HDEV (overlapping)",
             "totdev": "TOTDEV", "mtot": "MTOT", "ttot": "TTOT"}
    worst = max(r["max_rel_err"] for r in rows)
    lines = []
    for k, label in names.items():
        cells = []
        for t in ("NBS-9 (Table 30)", "1000-point (Table 31)"):
            v = by[k][t]
            if v == 0:
                cells.append("$0$")
            else:
                m, e = f"{v:.1e}".split("e")
                cells.append(f"${m}\\times10^{{{int(e)}}}$")
        lines.append(f"{label} & {cells[0]} & {cells[1]} \\\\")
    write("nist.tex", "\n".join(lines) + "\n")
    return worst


SINGLE = ["raw", "mindelay", "kalman", "kalman-dw", "rts-dw", "regression", "feedforward", "hull", "ptp4l", "sptp"]
MULTI = ["median", "rfc5905", "kalman-combine"]


def bench():
    get = aggregate(load("bench-ntp.json"))
    scs = ["lan", "internet", "congested", "route-change"]
    lines = []
    for e in SINGLE:
        cells = []
        for s in scs:
            r = get[(s, e)]
            cells.append(f"{sig(r['rms'] * 1e6)} $\\pm$ {sig(r['rms_std'] * 1e6, 2)}")
        lines.append(f"\\texttt{{{e}}} & " + " & ".join(cells) + " \\\\")
    write("bench-ntp.tex", "\n".join(lines) + "\n")
    lines = []
    for e in MULTI + ["hull"]:
        r = get[("falseticker", e)]
        label = f"\\texttt{{{e}}}" + (" (server a only)" if e == "hull" else "")
        lines.append(f"{label} & {sig(r['rms'] * 1e6)} $\\pm$ {sig(r['rms_std'] * 1e6, 2)} & "
                     f"{sig(r['max_abs'] * 1e3)} \\\\")
    write("bench-falseticker.tex", "\n".join(lines) + "\n")
    getp = aggregate(load("bench-ptp.json"))
    lines = []
    for e in ["raw", "ptp4l", "sptp", "kalman-dw", "mindelay", "hull"]:
        a, b = getp[("ptp-lan", e)], getp[("ptp-tc", e)]
        lines.append(f"\\texttt{{{e}}} & {sig(a['rms'] * 1e9)} & {sig(b['rms'] * 1e9)} \\\\")
    write("bench-ptp.tex", "\n".join(lines) + "\n")


def chains():
    d = load("e5_chains.json")
    lines = []
    for label, runs in d.items():
        cells = []
        for i in (0, 4, 9, 19):
            v = [r["nodes"][i]["max_te"] * 1e9 for r in runs]
            cells.append(f"{np.mean(v):.1f}")
        mt = [r["nodes"][19]["dte_l_mtie"] * 1e9 for r in runs]
        cells.append(f"{np.mean(mt):.1f}")
        cells.append(f"{runs[0]['warmup']:.0f}")
        lines.append(f"{label} & " + " & ".join(cells) + " \\\\")
    write("chains.tex", "\n".join(lines) + "\n")


def interop():
    path = os.path.join(ROOT, "data", "interop", "2026", "2026-09-30.jsonl")
    rows = [json.loads(ln) for ln in open(path)]
    lines = []
    for r in rows:
        if r["test"] not in ("ntp4", "nts") or not r["ok"]:
            continue
        off, dl = r["offset"], r["delay"]
        lines.append(f"{r['test'].upper().replace('NTP4', 'NTPv4')} & \\texttt{{{r['server']}}} & {r.get('stratum', '')} & "
                     f"{off * 1e3:+.3f} & {dl * 1e3:.2f} & {abs(off) / (dl / 2):.2f} \\\\")
    write("interop.tex", "\n".join(lines) + "\n")
    summary = collections.Counter((r["test"], bool(r["ok"])) for r in rows)
    return rows[0]["run"], rows[0]["ntpstats"], summary


def legacy():
    d = load("e3_legacy.json")
    n = d["ntpstats"]
    write("legacy.tex", f"% samples={d['samples']} median={d['median_interval_s']} gap_h={d['max_gap_h']:.2f}\n"
          f"% legacy tau={d['legacy']['tau']} adev={d['legacy']['adev']}\n"
          f"% ntpstats tau={n['tau']} oadev={n['oadev']} lo={n['lo']} hi={n['hi']} alpha={n['alpha']}\n")


if __name__ == "__main__":
    print("NIST worst", nist())
    bench()
    chains()
    print(interop())
    legacy()
    print(open(os.path.join(OUT, "legacy.tex")).read())
