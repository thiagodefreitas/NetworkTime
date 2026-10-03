# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Regenerate every number, table and figure of the preprint.

    pip install ntpstats==3.5.0 matplotlib
    python research/preprint-2026/experiments.py          # about 10 minutes on one core

Writes data/*.json and figures/*.pdf next to this file. All simulations are
seeded, so the output is reproducible.
"""

import json
import os
import platform
import time

import numpy as np

import ntpstats
from ntpstats import api, noisefit
from ntpstats import stability as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(HERE, "data")
FIG = os.path.join(HERE, "figures")
os.makedirs(DATA, exist_ok=True)
os.makedirs(FIG, exist_ok=True)


def save(name, obj):
    with open(os.path.join(DATA, name), "w") as fh:
        json.dump(obj, fh, indent=1, default=float)


# ------------------------------------------------------------------ E1: NIST SP 1065 tables
NBS9 = [892, 809, 823, 798, 671, 644, 883, 903, 677]
TABLE30 = {"adev": [91.22945, 115.8082], "oadev": [91.22945, 85.95287], "mdev": [91.22945, 74.78849],
           "tdev": [52.67135, 86.35831], "hdev": [70.80607, 85.61487], "totdev": [91.22945, 93.90379],
           "mtot": [75.50203, 75.83606], "ttot": [43.59112, 87.56794]}
TABLE31 = {"adev": [2.922319e-01, 9.965736e-02, 3.897804e-02], "oadev": [2.922319e-01, 9.159953e-02, 3.241343e-02],
           "mdev": [2.922319e-01, 6.172376e-02, 2.170921e-02], "tdev": [1.687202e-01, 3.563623e-01, 1.253382e00],
           "hdev": [2.943883e-01, 9.581083e-02, 3.237638e-02], "totdev": [2.922319e-01, 9.134743e-02, 3.406530e-02],
           "mtot": [2.418528e-01, 6.499161e-02, 2.287774e-02], "ttot": [1.396338e-01, 3.752293e-01, 1.320847e00]}


def nist1000():
    n, out = 1234567890, []
    for _ in range(1000):
        out.append(n / 2147483647)
        n = (16807 * n) % 2147483647
    return np.array(out)


def to_phase(y):
    y = np.asarray(y, dtype=float)
    return np.concatenate(([0.0], np.cumsum(y - y.mean())))


def e1_nist():
    rows = []
    for table, data, ms in (("NBS-9 (Table 30)", NBS9, [1, 2]), ("1000-point (Table 31)", nist1000(), [1, 10, 100])):
        ref = TABLE30 if len(ms) == 2 else TABLE31
        for kind, want in ref.items():
            got = st.compute(to_phase(data), 1.0, kind, ms, ci=None, min_terms=1).dev
            rel = np.abs(got / np.array(want) - 1)
            rows.append({"table": table, "kind": kind, "m": ms, "published": want, "computed": got.tolist(),
                         "max_rel_err": float(rel.max())})
    save("e1_nist.json", rows)
    return rows


# ------------------------------------------------------------------ E2: confidence-interval coverage
def e2_coverage(runs=400, n_phase=1025, ms=(1, 4, 16, 64), ci=0.95):
    out = []
    z = 1.959963984540054
    for alpha in (2, 1, 0, -1, -2):
        h = {alpha: 1.0}
        for kind in ("oadev", "mdev"):
            truth = noisefit.predict(h, kind, [float(m) for m in ms], 1.0)
            hit_edf = np.zeros(len(ms))
            hit_simple = np.zeros(len(ms))
            for r in range(runs):
                x = noisefit.simulate(h, n_phase, 1.0, seed=10_000 * (alpha + 3) + r)
                res = st.compute(x, 1.0, kind, list(ms), ci=ci)
                hit_edf += (res.lo <= truth) & (truth <= res.hi)
                hit_simple += np.abs(res.dev - truth) <= z * res.err
            out.append({"alpha": alpha, "kind": kind, "m": list(ms), "runs": runs, "n_phase": n_phase, "ci": ci,
                        "coverage_exact_edf": (hit_edf / runs).tolist(),
                        "coverage_dev_over_sqrt_n": (hit_simple / runs).tolist()})
    save("e2_coverage.json", out)
    return out


# ------------------------------------------------------------------ E3: the 2012 prototype on its own sample
def legacy_allan_dev_mills(values):
    """allanDevMills() of the 2012 prototype (legacy/gsoc2012/core_noGUI/allandev.py), verbatim logic."""
    y1, d, taus, adev = np.asarray(values, dtype=float), 32, [], []
    while len(y1) >= 10:
        u = np.diff(y1) / d
        v = np.diff(u)
        adev.append(float(np.sqrt(np.mean(v * v) / 2)))
        taus.append(d)
        y1 = y1[::2]
        d *= 2
    return taus, adev


def e3_legacy():
    (s,) = api.load(os.path.join(ROOT, "examples", "data", "loopstats.2012"))
    dt = np.diff(s.t)
    lt, la = legacy_allan_dev_mills(s.offset)
    (res,) = api.series_stability(s, kinds=("oadev",), ci=0.683)
    out = {"samples": len(s), "median_interval_s": float(np.median(dt)), "max_gap_h": float(dt.max() / 3600),
           "legacy": {"tau": lt, "adev": la},
           "ntpstats": {"tau": res.taus.tolist(), "oadev": res.dev.tolist(), "lo": res.lo.tolist(),
                        "hi": res.hi.tolist(), "n": res.n.tolist(), "alpha": res.alpha.tolist()}}
    save("e3_legacy.json", out)
    return out


# ------------------------------------------------------------------ E4: estimator benchmarks
def e4_bench(seeds=(1, 2, 3, 4, 5)):
    ntp = api.run_bench(api.load_scenarios(["lan", "internet", "congested", "route-change", "falseticker"]),
                        seeds=seeds)
    ptp = api.run_bench(api.load_scenarios(["ptp-lan", "ptp-tc"]), seeds=range(1, 4))
    save("bench-ntp.json", ntp)
    save("bench-ptp.json", ptp)
    return ntp, ptp


# ------------------------------------------------------------------ E5: boundary-clock chains
CHAIN_CONFIGS = {"PI, linuxptp gains": ("pi", {}), "PI, narrow loop": ("pi", {"kp": 0.3, "ki": 3.5e-4}),
                 "linreg": ("linreg", {})}


def e5_chains(hops=20, seeds=(1, 2, 3)):
    out = {}
    for label, (servo, opts) in CHAIN_CONFIGS.items():
        runs = []
        for seed in seeds:
            r = api.simulate_chain(api.ChainScenario(hops=hops, servo=servo, servo_options=dict(opts), seed=seed))
            runs.append({"seed": seed, "warmup": r.warmup, "nodes": r.nodes, "hops": r.hops})
        out[label] = runs
    save("e5_chains.json", out)
    return out


# ------------------------------------------------------------------ E6: throughput
def e6_perf():
    rng = np.random.default_rng(1)
    x = np.cumsum(rng.normal(0, 1e-9, 1_000_000))
    out = {"python": platform.python_version(), "machine": platform.machine(), "processor": platform.processor(),
           "numpy": np.__version__}
    for kind in ("oadev", "mdev", "hdev", "totdev"):
        t0 = time.perf_counter()
        st.compute(x, 1.0, kind, "octave", ci=0.683)
        out[kind] = time.perf_counter() - t0
    save("e6_perf.json", out)
    return out


# ------------------------------------------------------------------ E7: bias after a one-way route change
def e7_route_change(seeds=(1, 2, 3, 4, 5)):
    from dataclasses import replace

    ((_, sc),) = api.load_scenarios(["route-change"])
    out = {}
    for name in ("raw", "mindelay", "regression", "kalman-dw", "rts-dw", "feedforward", "hull"):
        before, after = [], []
        for seed in seeds:
            meas, truth = api.simulate_multi(replace(sc, seed=seed))
            est = api.run_estimator(name, meas[0])
            err = est.offset - np.interp(est.t, truth.t, truth.offset)
            rel = est.t - truth.t[0]
            before.append(float(np.nanmedian(err[(rel > 3600) & (rel < 8 * 3600)])))
            after.append(float(np.nanmedian(err[(rel > 10 * 3600) & (rel < 18 * 3600)])))
        out[name] = {"median_error_1h_8h": before, "median_error_10h_18h": after}
    save("e7_route_change.json", out)
    return out


# ------------------------------------------------------------------ figures
OKABE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]


def _style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "STIXGeneral", "mathtext.fontset": "stix", "font.size": 8.5, "axes.titlesize": 8.5, "axes.labelsize": 8.5,
                         "legend.fontsize": 7.5, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": "#dddddd", "grid.linewidth": 0.5, "lines.linewidth": 1.2,
                         "savefig.bbox": "tight", "savefig.pad_inches": 0.02, "pdf.fonttype": 42})
    return plt


def fig_legacy(e3):
    plt = _style()
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    n = e3["ntpstats"]
    tau, dev = np.array(n["tau"]), np.array(n["oadev"])
    ax.errorbar(tau, dev, yerr=[dev - np.array(n["lo"]), np.array(n["hi"]) - dev], fmt="o-", ms=3, capsize=2,
                color=OKABE[0], label=r"ntpstats OADEV, $\tau_0$ = median interval, 68 % interval")
    ax.plot(e3["legacy"]["tau"], e3["legacy"]["adev"], "s--", ms=3, color=OKABE[1],
            label=r"2012 prototype, $\tau_0$ fixed at 32 s")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"averaging time $\tau$ (s)")
    ax.set_ylabel(r"$\sigma_y(\tau)$")
    ax.legend(loc="upper right", frameon=False)
    ax.set_ylim(1e-7, 1e-2)
    fig.savefig(os.path.join(FIG, "legacy-adev.pdf"))
    plt.close(fig)


def fig_chains(e5):
    plt = _style()
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    for (label, runs), c in zip(e5.items(), OKABE):
        m = np.array([[nd["max_te"] for nd in r["nodes"]] for r in runs]) * 1e9
        k = np.arange(1, m.shape[1] + 1)
        ax.plot(k, m.mean(0), "o-", ms=2.5, color=c, label=label)
        ax.fill_between(k, m.min(0), m.max(0), color=c, alpha=0.18, lw=0)
    ax.set_yscale("log")
    ax.set_xlabel("boundary clock (hops from the grandmaster)")
    ax.set_ylabel(r"max|TE| (ns)")
    ax.set_xticks([1, 5, 10, 15, 20])
    ax.legend(loc="upper left", frameon=False)
    fig.savefig(os.path.join(FIG, "chain-maxte.pdf"))
    plt.close(fig)


def fig_ptp(ptp):
    plt = _style()
    order = ["raw", "ptp4l", "sptp", "kalman", "regression", "kalman-dw", "rts-dw", "mindelay", "hull"]
    fig, ax = plt.subplots(figsize=(3.4, 2.5))
    y = np.arange(len(order))
    for j, (sc, c) in enumerate((("ptp-lan", OKABE[1]), ("ptp-tc", OKABE[0]))):
        v = [next(r for r in ptp if r["scenario"] == sc and r["estimator"] == e)["rms"] * 1e9 for e in order]
        ax.barh(y + (0.2 if j == 0 else -0.2), v, height=0.38, color=c,
                label="no on-path support" if sc == "ptp-lan" else "transparent clocks (95 %)")
    ax.set_yticks(y)
    ax.set_yticklabels(order)
    ax.set_xscale("log")
    ax.set_xlabel("rms error of the offset estimate (ns)")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    ax.grid(axis="y", visible=False)
    fig.savefig(os.path.join(FIG, "ptp-bench.pdf"))
    plt.close(fig)


def fig_coverage(e2):
    plt = _style()
    fig, axs = plt.subplots(1, 2, figsize=(6.9, 2.2), sharey=True)
    names = {2: "white PM", 1: "flicker PM", 0: "white FM", -1: "flicker FM", -2: "RW FM"}
    for ax, kind in zip(axs, ("oadev", "mdev")):
        for row, c in zip([r for r in e2 if r["kind"] == kind], OKABE):
            ax.plot(row["m"], row["coverage_exact_edf"], "o-", ms=3, color=c, label=names[row["alpha"]])
            ax.plot(row["m"], row["coverage_dev_over_sqrt_n"], "x:", ms=3, color=c)
        ax.axhline(0.95, color="k", lw=0.6)
        ax.set_xscale("log", base=2)
        ax.set_xlabel("averaging factor m")
        ax.set_title(kind.upper())
        ax.set_ylim(0.0, 1.02)
    axs[0].set_ylabel("coverage of 95 % intervals")
    axs[1].legend(loc="lower left", frameon=False, ncol=2)
    fig.savefig(os.path.join(FIG, "ci-coverage.pdf"))
    plt.close(fig)


def figures_from_data():
    """Redraw the figures from data/*.json without rerunning the experiments."""

    def load(name):
        with open(os.path.join(DATA, name)) as fh:
            return json.load(fh)

    fig_legacy(load("e3_legacy.json"))
    fig_chains(load("e5_chains.json"))
    fig_ptp(_aggregate(load("bench-ptp.json")))
    fig_coverage(load("e2_coverage.json"))


def _aggregate(rows):
    """Mean RMS over seeds per (scenario, estimator), in the shape fig_ptp expects."""
    groups = {}
    for r in rows:
        groups.setdefault((r["scenario"], r["estimator"]), []).append(r["rms"])
    return [{"scenario": s, "estimator": e, "rms": float(np.mean(v))} for (s, e), v in groups.items()]


def main():
    meta = {"ntpstats": ntpstats.__version__, "numpy": np.__version__, "python": platform.python_version()}
    save("versions.json", meta)
    print("ntpstats", meta)
    e1 = e1_nist()
    print("E1 worst relative error:", max(r["max_rel_err"] for r in e1))
    e2 = e2_coverage()
    e3 = e3_legacy()
    _, ptp = e4_bench()
    e5 = e5_chains()
    e6 = e6_perf()
    e7_route_change()
    print("E6", e6)
    fig_legacy(e3)
    fig_chains(e5)
    fig_ptp(_aggregate(ptp))
    fig_coverage(e2)


if __name__ == "__main__":
    import sys

    figures_from_data() if "--figures" in sys.argv[1:] else main()
