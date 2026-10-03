# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Revisit the 2012 undergraduate thesis with ntpstats 3.5.0.

T. F. O. Araújo, "Modelagem e análise de relógios locais para otimização de
sincronismo horário em rede", Trabalho de Conclusão de Curso, UFCG, 2012,
https://dspace.sti.ufcg.edu.br/handle/riufcg/18226

    pip install ntpstats==3.5.0 matplotlib
    python research/thesis-2012/replicate.py          # about one minute

R1  the Savitzky-Golay stage of the 2012 code, as written and as intended
R2  the real 2012 measurements in legacy/, re-analysed
R3  the correction loop of chapters 7-8 against a simulated clock with known truth
R4  chapter 5: discretising the type II loop (forward/backward Euler, Tustin)
R5  chapter 1, first objective: poll interval versus accuracy, from the 2012 free-running clock
"""

import json
import os
import re
from dataclasses import replace
from math import factorial

import numpy as np

import ntpstats
from ntpstats import api
from ntpstats import stability as st
from ntpstats.series import TimeSeries

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
LEGACY = os.path.join(ROOT, "legacy", "gsoc2012", "core_noGUI")
DATA = os.path.join(HERE, "data")
FIG = os.path.join(HERE, "figures")
os.makedirs(DATA, exist_ok=True)
os.makedirs(FIG, exist_ok=True)


def save(name, obj):
    with open(os.path.join(DATA, name), "w") as fh:
        json.dump(obj, fh, indent=1, default=float)


# ---------------------------------------------------------------- the 2012 filters, ported to Python 3
class LegacySavitzkyGolay:
    """legacy/gsoc2012/core_noGUI/savitzky.py, same arithmetic (np.mat replaced by arrays).

    Note the default ``deriv=2``: estimators.py builds it as ``savitzky_golay(window_size=39, order=5)``.
    """

    def __init__(self, window_size, order, deriv=2, rate=1):
        self.window_size, self.order, self.deriv, self.rate = int(window_size), int(order), deriv, rate

    def filter(self, y):
        y = np.asarray(y, dtype=float)
        half = (self.window_size - 1) // 2
        b = np.array([[k ** i for i in range(self.order + 1)] for k in range(-half, half + 1)], dtype=float)
        m = np.linalg.pinv(b)[self.deriv] * self.rate ** self.deriv * factorial(self.deriv)
        first = y[0] - np.abs(y[1:half + 1][::-1] - y[0])
        last = y[-1] + np.abs(y[-half - 1:-1][::-1] - y[-1])
        return np.convolve(m[::-1], np.concatenate((first, y, last)), mode="valid")


def causal_savgol(y, window=39, order=5):
    """Realisable smoother: fit the last ``window`` samples, evaluate at the newest one."""
    y = np.asarray(y, dtype=float)
    k = np.arange(-window + 1, 1, dtype=float)
    coef = np.linalg.pinv(np.vander(k, order + 1, increasing=True))[0]
    out = np.full(y.size, np.nan)
    for i in range(window - 1, y.size):
        out[i] = coef @ y[i - window + 1:i + 1]
    out[:window - 1] = y[:window - 1]
    return out


class LegacyKalman:
    """legacy/gsoc2012/core_noGUI/kalman_class.py, same matrices and constants."""

    def __init__(self, tau=32.0):
        self.R = 1e2 * np.eye(1)
        self.P = 1e3 * np.eye(2)
        self.Q = 0.001 * np.eye(2)
        self.tau = tau
        self.xE = np.zeros((2, 1))
        self.H = np.array([[1.0, tau]])
        self.F = np.array([[1.0, tau], [0.0, 1.0]])
        self.G = np.array([[1.0, tau / 2], [0.0, 1.0]])

    def filter(self, z):
        e = z - self.H @ self.xE
        S = self.H @ self.P @ self.H.T + self.R
        W = self.P @ self.H.T @ np.linalg.inv(S)
        self.xE = self.xE + W @ e
        self.P = self.P - W @ S @ W.T
        self.xE = self.F @ self.xE
        self.P = self.F @ self.P @ self.F.T + self.G @ self.Q @ self.G.T * self.tau
        return float(self.xE[0, 0])


def legacy_kalman_series(z, tau):
    kf = LegacyKalman(tau)
    return np.array([kf.filter(v) for v in z])


# ---------------------------------------------------------------- R1: the smoothing stage
def r1_savgol():
    k = np.arange(200, dtype=float)
    a, b, c = 0.3, 2e-3, 5e-5
    quad = a + b * k + c * k ** 2
    as_built = LegacySavitzkyGolay(39, 5).filter(quad)
    intended = LegacySavitzkyGolay(39, 5, deriv=0).filter(quad)
    mid = slice(40, 160)
    x = np.loadtxt(os.path.join(LEGACY, "offsets_estimation.txt"))
    out = {
        "test_signal": "a + b k + c k^2 with c = 5e-5",
        "as_built_output_mid": [float(as_built[mid].min()), float(as_built[mid].max())],
        "expected_second_derivative": 2 * c,
        "intended_max_abs_error_mid": float(np.max(np.abs(intended[mid] - quad[mid]))),
        "real_2012_input_rms_ms": float(np.std(x) * 1e3),
        "real_2012_as_built_rms_ms": float(np.std(LegacySavitzkyGolay(39, 5).filter(x)) * 1e3),
        "real_2012_intended_rms_ms": float(np.std(LegacySavitzkyGolay(39, 5, deriv=0).filter(x)) * 1e3),
    }
    save("r1_savgol.json", out)
    return out


# ---------------------------------------------------------------- R2: the real 2012 data
def load_december():
    t = np.loadtxt(os.path.join(LEGACY, "computeTime_estimation.txt"))
    x = np.loadtxt(os.path.join(LEGACY, "offsets_estimation.txt"))
    return TimeSeries(t, x, name="utcnist2, 2 December 2012, 32 s", source_format="csv")


def load_may():
    rows = []
    with open(os.path.join(LEGACY, "estimators.log")) as fh:
        for ln in fh:
            m = re.search(r"Logged: \[off, ([-\d.e]+), time, ([\d.]+)\]", ln)
            if m:
                rows.append((float(m.group(2)), float(m.group(1))))
    a = np.array(rows)
    return TimeSeries(a[:, 0], a[:, 1], name="utcnist2, 26-31 May 2012, free-running", source_format="csv")


def stab(series, ci=0.683, detrend="linear"):
    (r,) = api.series_stability(series, kinds=("oadev",), ci=ci, detrend=detrend)
    return {"tau": r.taus.tolist(), "oadev": r.dev.tolist(), "lo": r.lo.tolist(), "hi": r.hi.tolist(),
            "alpha": r.alpha.tolist(), "n": r.n.tolist()}


def r2_real():
    dec = load_december()
    may = load_may()
    sg = LegacySavitzkyGolay(39, 5, deriv=0).filter(dec.offset)
    dec_sg = TimeSeries(dec.t, sg, name="December, smoothed (SG 5/39)", source_format="csv")
    dt = np.diff(may.t)
    segs = np.split(np.arange(len(may)), np.where(dt > 3 * np.median(dt))[0] + 1)
    seg_rows = []
    for s in segs:
        if len(s) < 10:
            continue
        rel = may.t[s] - may.t[s[0]]
        p = np.polyfit(rel, may.offset[s], 2)
        seg_rows.append({"samples": int(len(s)), "start": float(may.t[s[0]]), "hours": float(rel[-1] / 3600),
                         "frequency_ppm": float(p[1] * 1e6), "drift_per_day_ppm": float(2 * p[0] * 86400 * 1e6),
                         "residual_rms_ms": float(np.std(may.offset[s] - np.polyval(p, rel)) * 1e3)})
    events = api.detect_events(dec)
    out = {
        "december": {"samples": len(dec), "hours": float((dec.t[-1] - dec.t[0]) / 3600),
                     "median_interval": float(np.median(np.diff(dec.t))),
                     "median_ms": float(np.median(dec.offset) * 1e3),
                     "p05_ms": float(np.percentile(dec.offset, 5) * 1e3),
                     "p95_ms": float(np.percentile(dec.offset, 95) * 1e3),
                     "frequency_ppm": float(np.polyfit(dec.t - dec.t[0], dec.offset, 1)[0] * 1e6),
                     "events": len(events),
                     "oadev": stab(dec), "oadev_smoothed": stab(dec_sg)},
        "may": {"samples": len(may), "median_interval": float(np.median(dt)), "segments": seg_rows,
                "oadev": stab(may, detrend="quadratic")},
    }
    save("r2_real.json", out)
    return out, dec, may


# ---------------------------------------------------------------- R3: the correction loop with known truth
def r3_truth(seeds=(1, 2, 3, 4, 5)):
    ((_, base),) = api.load_scenarios(["internet"])
    base = replace(base, poll=32.0, duration=12 * 3600.0)
    names = ["raw", "SG 5/39 centred (offline)", "SG 5/39 causal", "2012 Kalman", "SG centred + 2012 Kalman",
             "SG as built (deriv=2) + 2012 Kalman", "kalman-dw", "regression", "hull"]
    acc = {n: {"rms": [], "oadev32": [], "oadev1024": []} for n in names}
    truth_adev = {"oadev32": [], "oadev1024": []}
    for seed in seeds:
        meas, truth = api.simulate_multi(replace(base, seed=seed))
        m = meas[0]
        z = m.offset
        tau = float(np.median(np.diff(m.t)))
        sg_c = LegacySavitzkyGolay(39, 5, deriv=0).filter(z)
        est = {
            "raw": z,
            "SG 5/39 centred (offline)": sg_c,
            "SG 5/39 causal": causal_savgol(z),
            "2012 Kalman": legacy_kalman_series(z, tau),
            "SG centred + 2012 Kalman": legacy_kalman_series(sg_c, tau),
            "SG as built (deriv=2) + 2012 Kalman": legacy_kalman_series(LegacySavitzkyGolay(39, 5).filter(z), tau),
        }
        for e in ("kalman-dw", "regression", "hull"):
            r = api.run_estimator(e, m)
            est[e] = np.interp(m.t, r.t, r.offset)
        tr = np.interp(m.t, truth.t, truth.offset)
        keep = m.t >= m.t[0] + 1800
        for n, x in est.items():
            err = (x - tr)[keep]
            acc[n]["rms"].append(float(np.sqrt(np.nanmean(err ** 2))))
            r = st.compute(np.asarray(x, dtype=float)[keep], tau, "oadev", [1, 32], ci=None)
            acc[n]["oadev32"].append(float(r.dev[0]))
            acc[n]["oadev1024"].append(float(r.dev[1]))
        r = st.compute(tr[keep], tau, "oadev", [1, 32], ci=None)
        truth_adev["oadev32"].append(float(r.dev[0]))
        truth_adev["oadev1024"].append(float(r.dev[1]))
    out = {"scenario": "internet preset, 32 s polling, 12 h, first 30 min excluded", "seeds": list(seeds),
           "estimators": {n: {k: float(np.mean(v)) for k, v in d.items()} for n, d in acc.items()},
           "truth": {k: float(np.mean(v)) for k, v in truth_adev.items()}}
    save("r3_truth.json", out)
    return out


# ---------------------------------------------------------------- R4: discretising the type II loop
def r4_discretisation(zeta=0.7071067811865476):
    """Closed-loop pole radius of a type II PI loop (zeta = 1/sqrt 2), controller discretised three ways.

    Loop: phase integrator (exact, T/(z-1)) driven by the controller
    C(s) = wn^2 (1 + 2 zeta s / wn) / s, so the continuous closed loop is
    s^2 + 2 zeta wn s + wn^2. r = T * wn is the update interval over the loop time constant.
    """

    def ctrl(method, wn, T):
        k1, k0 = 2 * zeta * wn, wn ** 2  # C(s) = k1 + k0/s
        if method == "forward":  # 1/s -> T/(z-1)
            return np.array([k1, k0 * T - k1]), np.array([1.0, -1.0])
        if method == "backward":  # 1/s -> T z/(z-1)
            return np.array([k1 + k0 * T, -k1]), np.array([1.0, -1.0])
        return np.array([k1 + k0 * T / 2, k0 * T / 2 - k1]), np.array([1.0, -1.0])  # Tustin

    rs = np.logspace(-2.5, 0.6, 400)
    out = {"zeta": zeta, "r": rs.tolist()}
    for method in ("forward", "backward", "tustin"):
        radii = []
        for r in rs:
            T, wn = r, 1.0
            num, den = ctrl(method, wn, T)
            pnum, pden = np.array([T]), np.array([1.0, -1.0])
            char = np.polyadd(np.polymul(den, pden), np.polymul(num, pnum))
            radii.append(float(np.max(np.abs(np.roots(char)))))
        radii = np.array(radii)
        unstable = rs[radii >= 1.0]
        out[method] = {"radius": radii.tolist(), "first_unstable_r": float(unstable[0]) if unstable.size else None}
    exact = np.exp(-zeta * rs)  # magnitude of exp(s T) for the continuous poles, wn = 1
    out["continuous_mapped"] = exact.tolist()
    i = int(np.argmin(np.abs(rs - 1 / 32)))
    out["at_r_1_32"] = {m: out[m]["radius"][i] for m in ("forward", "backward", "tustin")}
    out["at_r_1_32"]["continuous"] = float(exact[i])
    out["at_r_1_32"]["r"] = float(rs[i])
    save("r4_discretisation.json", out)
    return out


# ---------------------------------------------------------------- R5: poll interval versus accuracy
def r5_poll(may):
    dt = np.diff(may.t)
    segs = np.split(np.arange(len(may)), np.where(dt > 3 * np.median(dt))[0] + 1)
    s = max(segs, key=len)
    seg = TimeSeries(may.t[s], may.offset[s], name="May 2012, longest segment", source_format="csv")
    nf = api.fit_noise(seg, kinds=("oadev", "mdev"), drift=True, bootstrap=100, seed=1)
    horizons = [64, 256, 1024, 4096, 16384, 65536]
    rows = []
    for hz in horizons:
        r = api.holdover_series(seg, float(hz), model="frequency", ci=0.95)
        i = int(np.argmin(np.abs(np.asarray(r.t) - hz)))
        hi = abs(float(r.mean[i])) + 1.96 * float(r.sd[i])
        rows.append({"interval_s": hz, "tie95_s": hi})
    out = {"segment_samples": int(len(s)), "tau0": float(np.median(np.diff(seg.t))),
           "h": {str(k): float(v) for k, v in nf.h.items()},
           "h_lo": {str(k): float(v) for k, v in nf.lo.items()}, "h_hi": {str(k): float(v) for k, v in nf.hi.items()},
           "active": [int(a) for a in nf.active], "drift": float(nf.drift) if nf.drift is not None else None,
           "tie95": rows}
    save("r5_poll.json", out)
    return out


# ---------------------------------------------------------------- figures
def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "STIXGeneral", "mathtext.fontset": "stix", "font.size": 8.5,
                         "legend.fontsize": 7.5, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#dddddd", "grid.linewidth": 0.5,
                         "savefig.bbox": "tight", "savefig.pad_inches": 0.02, "pdf.fonttype": 42})
    return plt


C = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]


def figures(r2, r3, r4):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    for key, label, c in (("oadev", "measured offsets", C[0]), ("oadev_smoothed", "after SG 5/39 smoothing", C[1])):
        d = r2["december"][key]
        tau, dev = np.array(d["tau"]), np.array(d["oadev"])
        ax.errorbar(tau, dev, yerr=[dev - np.array(d["lo"]), np.array(d["hi"]) - dev], fmt="o-", ms=3, capsize=2,
                    color=c, label=label)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"averaging time $\tau$ (s)")
    ax.set_ylabel(r"$\sigma_y(\tau)$, 68 % intervals")
    ax.legend(frameon=False)
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(FIG, f"december-2012-oadev.{ext}"), dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    for m, c in (("forward", C[1]), ("backward", C[0]), ("tustin", C[2])):
        ax.plot(r4["r"], r4[m]["radius"], color=c, label={"forward": "forward Euler", "backward": "backward Euler",
                                                         "tustin": "Tustin"}[m])
    ax.plot(r4["r"], r4["continuous_mapped"], "k:", label=r"continuous poles, $|e^{sT}|$")
    ax.axhline(1.0, color="k", lw=0.6)
    ax.axvline(1 / 32, color="#888888", lw=0.6, ls="--")
    ax.set_xscale("log")
    ax.set_xlabel(r"update interval / loop time constant, $T\omega_n$")
    ax.set_ylabel("largest closed-loop pole radius")
    ax.set_ylim(0.0, 1.6)
    ax.legend(frameon=False, loc="upper left")
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(FIG, f"discretisation.{ext}"), dpi=200)
    plt.close(fig)


def main():
    meta = {"ntpstats": ntpstats.__version__, "numpy": np.__version__}
    save("versions.json", meta)
    print(meta)
    print("R1", r1_savgol())
    r2, _, may = r2_real()
    print("R2 december", {k: v for k, v in r2["december"].items() if not k.startswith("oadev")})
    print("R2 may", r2["may"]["segments"])
    r3 = r3_truth()
    for n, v in r3["estimators"].items():
        print(f"R3 {n:38s} rms {v['rms'] * 1e6:9.1f} us  oadev(32 s) {v['oadev32']:.2e}  oadev(1024 s) {v['oadev1024']:.2e}")
    print("R3 truth", r3["truth"])
    r4 = r4_discretisation()
    print("R4", {m: r4[m]["first_unstable_r"] for m in ("forward", "backward", "tustin")}, r4["at_r_1_32"])
    r5 = r5_poll(may)
    print("R5", r5)
    figures(r2, r3, r4)


if __name__ == "__main__":
    main()
