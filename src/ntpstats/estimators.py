# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Pluggable clock-offset estimators for benchmarking synchronisation algorithms.

An estimator turns noisy measurements into an estimate of the true offset
(reference - local) at the measurement times::

    class MyEstimator(Estimator):
        name = "mine"
        def fit(self, series):            # TimeSeries -> TimeSeries
            ...

    register(MyEstimator())

Third-party packages can expose estimators through the entry-point group
``ntpstats.estimators`` (value: an :class:`Estimator` instance, class or
factory); they are picked up by :func:`available` and ``ntpstats bench``.

Multi-server estimators set ``multi = True`` and receive a list of series
(one per server); they return one combined series.

Built-in reference algorithms
-----------------------------
``raw``            the measurements themselves
``kalman``         two-state Kalman filter (no delay information)
``kalman-dw``      Kalman filter with delay-weighted measurement noise
``rts-dw``         RTS smoother, delay weighted (offline optimum for the model)
``mindelay``       NTP clock filter: minimum delay of the last 8 samples (RFC 5905 s10)
``regression``     chrony-style weighted linear regression over a window sized
                   by a runs test on the residuals
``feedforward``    RADclock-style: rate from long-baseline low-RTT packets,
                   offset from a quality-weighted recent window
``hull``           Huygens-style: the max-margin line through the offset bounds
                   (offset ± delay/2) of a sliding window
``ptp4l``          linuxptp-style slave: moving-median mean path delay and the PI
                   (or linreg) servo, in closed loop
``sptp``           SPTP-style client: complete exchanges, path-delay outlier
                   discard, PI servo
``rfc5905``        (multi) clock filter + selection (intersection), cluster and
                   combine algorithms of RFC 5905 s11
``median``         (multi) median of the servers' clock-filter outputs
``kalman-combine`` (multi) ntpd-rs-style: per-source Kalman filters, interval
                   intersection, inverse-variance combination
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional, Sequence, Tuple, Union

import numpy as np

from .series import TimeSeries


class Estimator:
    name: str = "estimator"
    multi: bool = False
    description: str = ""

    def fit(self, data):  # pragma: no cover - interface
        raise NotImplementedError

    def __repr__(self):
        return f"<Estimator {self.name}>"


_REGISTRY: Dict[str, Estimator] = {}


def register(est: Estimator) -> Estimator:
    _REGISTRY[est.name] = est
    return est


def _entry_points() -> None:
    try:
        from importlib.metadata import entry_points

        eps: Any = entry_points()
        group = eps.select(group="ntpstats.estimators") if hasattr(eps, "select") else eps.get("ntpstats.estimators", [])
    except Exception:  # pragma: no cover
        return
    for ep in group:
        if ep.name in _REGISTRY:
            continue
        try:
            obj = ep.load()
            obj = obj() if isinstance(obj, type) or (callable(obj) and not isinstance(obj, Estimator)) else obj
            obj.name = getattr(obj, "name", ep.name) or ep.name
            _REGISTRY[ep.name] = obj
        except Exception:  # a broken plugin must not break the tool
            continue


def available() -> Dict[str, Estimator]:
    _entry_points()
    return dict(_REGISTRY)


def get(name: str) -> Estimator:
    est = available().get(name)
    if est is None:
        raise KeyError(f"unknown estimator {name!r}; available: {', '.join(sorted(available()))}")
    return est


class FunctionEstimator(Estimator):
    def __init__(self, name: str, fn: Callable, multi: bool = False, description: str = ""):
        self.name, self._fn, self.multi, self.description = name, fn, multi, description

    def fit(self, data):
        return self._fn(data)


def _like(series: TimeSeries, t, offset, name) -> TimeSeries:
    return TimeSeries(np.asarray(t, float), np.asarray(offset, float), name=f"{series.name} ({name})",
                      source_format=series.source_format, meta={"estimator": name, "derived_from": series.name})


def _quality(series: TimeSeries) -> np.ndarray:
    """Per-sample error bound from queueing delay: (delay - min_delay) / 2."""
    d = series.extra.get("delay")
    if d is None or not np.isfinite(d).any():
        return np.zeros(len(series))
    return np.where(np.isfinite(d), (d - np.nanmin(d)) / 2, np.nanmax(d))


# ------------------------------------------------------- chrony-style regression
def _runs(signs: np.ndarray) -> int:
    return int(1 + np.count_nonzero(signs[1:] != signs[:-1])) if signs.size else 0


def _runs_ok(res: np.ndarray) -> bool:
    """Wald-Wolfowitz runs test (two-sided, ~5 %): residual signs look random."""
    s = res > 0
    n1, n2 = int(s.sum()), int((~s).sum())
    n = n1 + n2
    if n1 == 0 or n2 == 0 or n < 6:
        return n < 6
    mu = 2.0 * n1 * n2 / n + 1
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n * n * (n - 1))
    if var <= 0:
        return True
    return (_runs(s) - mu) / math.sqrt(var) > -1.96


def regression(series: TimeSeries, max_samples: int = 64, min_samples: int = 6,
               sigma: Optional[float] = None) -> TimeSeries:
    """Causal weighted linear regression per sample, chrony style.

    Weights are ``1 / (sigma^2 + q^2)`` with ``q`` the queueing error bound;
    the window shrinks (dropping the oldest half) while the residual signs
    fail a runs test, i.e. while a straight line no longer describes the
    recent phase (frequency change).
    """
    s = series.sorted()
    t, x = s.t, s.offset
    q = _quality(s)
    if sigma is None:
        sigma = max(float(np.median(np.abs(np.diff(x)))) / 4, 1e-9) if len(s) > 2 else 1e-6
    w_all = 1.0 / (sigma ** 2 + q ** 2)
    out = np.empty(len(s))
    n_used = max_samples
    for k in range(len(s)):
        n_used = min(n_used + 1, max_samples, k + 1)
        while True:
            a = k + 1 - n_used
            tt, xx, ww = t[a: k + 1] - t[k], x[a: k + 1], w_all[a: k + 1]
            if n_used < 3:
                out[k] = np.average(xx, weights=ww)
                break
            W = ww.sum()
            tm, xm = (ww * tt).sum() / W, (ww * xx).sum() / W
            den = (ww * (tt - tm) ** 2).sum()
            slope = (ww * (tt - tm) * (xx - xm)).sum() / den if den > 0 else 0.0
            icpt = xm - slope * tm
            if n_used > min_samples and not _runs_ok(xx - (icpt + slope * tt)):
                n_used = max(min_samples, n_used // 2)
                continue
            out[k] = icpt  # value of the fitted line at t[k]
            break
    return _like(s, t, out, "regression")


# ------------------------------------------------------- RADclock-style
def feedforward(series: TimeSeries, rate_window: float = 6 * 3600, offset_window: int = 16,
                e_star: Optional[float] = None) -> TimeSeries:
    """Feed-forward estimator in the spirit of RADclock (Veitch, Ridoux et al.).

    * rate: slope between low-RTT packets separated by a long baseline
      (causal, up to ``rate_window`` seconds back), robust to queueing;
    * offset: for each sample, quality-weighted average of the last
      ``offset_window`` rate-corrected offsets, weights ``exp(-(q / E*)^2)``.
    """
    s = series.sorted()
    t, x = s.t, s.offset
    q = _quality(s)
    if e_star is None:
        e_star = max(float(np.percentile(q, 25)), 1e-9) if q.any() else 1e-6
    good = q <= max(e_star, float(np.percentile(q, 20)))
    out = np.empty(len(s))
    rate = 0.0
    for k in range(len(s)):
        lo = np.searchsorted(t, t[k] - rate_window)
        idx = np.flatnonzero(good[lo: k + 1]) + lo
        if idx.size >= 2 and t[idx[-1]] - t[idx[0]] > 0:
            n4 = max(1, idx.size // 4)
            a, b = idx[:n4], idx[-n4:]
            dt = t[b].mean() - t[a].mean()
            if dt > 0:
                rate = (x[b].mean() - x[a].mean()) / dt
        a = max(0, k + 1 - offset_window)
        pred = x[a: k + 1] + rate * (t[k] - t[a: k + 1])
        w = np.exp(-((q[a: k + 1] / e_star) ** 2)) + 1e-12
        out[k] = np.average(pred, weights=w)
    return _like(s, t, out, "feedforward")


# ------------------------------------------------------- RFC 5905 multi-server
def _clock_filter(series: TimeSeries, stages: int = 8, freq_window: int = 64):
    """RFC 5905 s10 clock filter per sample: (epoch, offset, delay, jitter, freq, sample_time).

    The selected (minimum-delay) sample can be several polls old; ntpd's
    discipline loop compensates the local frequency error, so here each
    output carries a causal frequency estimate (least squares over the last
    ``freq_window`` filter outputs) used to propagate it to later epochs.
    """
    s = series.sorted()
    d = s.extra.get("delay", np.zeros(len(s)))
    rows = np.zeros((len(s), 6))
    for k in range(len(s)):
        a = max(0, k + 1 - stages)
        seg = np.arange(a, k + 1)
        order = seg[np.argsort(d[seg], kind="stable")]
        best = order[0]
        jitter = math.sqrt(np.mean((s.offset[order] - s.offset[best]) ** 2)) if order.size > 1 else 0.0
        rows[k] = (s.t[k], s.offset[best], d[best], jitter, 0.0, s.t[best])
    for k in range(len(rows)):
        a = max(0, k + 1 - freq_window)
        # The filter repeats its pick while it stays the minimum-delay sample:
        # fit over distinct samples only, and clamp to ntpd's 500 ppm limit.
        tt, first = np.unique(rows[a: k + 1, 5], return_index=True)
        xx = rows[a: k + 1, 1][first]
        if tt.size >= 4 and np.ptp(tt) > 0:
            rows[k, 4] = float(np.clip(np.polyfit(tt - tt[-1], xx, 1)[0], -500e-6, 500e-6))
    return rows


def _at(f: np.ndarray, te: float, stale: float):
    """Latest clock-filter output at epoch ``te``, propagated with its frequency."""
    i = np.searchsorted(f[:, 0], te, side="right") - 1
    if i < 0 or te - f[i, 0] > stale:
        return None
    _, off, dly, jit, freq, ts = f[i]
    return off + freq * (te - ts), dly, jit


def rfc5905_combine(series_list: Sequence[TimeSeries], nmin: int = 1, maxclock: int = 3,
                    dispersion: float = 1e-3) -> TimeSeries:
    """Selection, cluster and combine (RFC 5905 s11.2) over several servers.

    At each epoch (times of the first server) the latest clock-filter output
    of every server gives an offset and a root distance
    ``lambda = delay/2 + dispersion + jitter``. The intersection algorithm
    keeps the truechimers, the cluster algorithm prunes outliers by selection
    jitter down to ``maxclock`` survivors, and the survivors are combined
    weighted by 1/lambda.
    """
    filt = [_clock_filter(s) for s in series_list]
    epochs = np.unique(np.concatenate([f[:, 0] for f in filt]))
    stale = 4 * max(float(np.median(np.diff(f[:, 0]))) if len(f) > 1 else 0.0 for f in filt) or np.inf
    out_t, out_x = [], []
    for te in epochs:
        cands = []
        for f in filt:
            got = _at(f, te, stale)
            if got is None:
                continue
            off, dly, jit = got
            lam = dly / 2 + dispersion + jit
            cands.append((off, lam, jit))
        if not cands:
            continue
        chimers = _intersect(cands, nmin)
        if not chimers:
            continue
        surv = _cluster(chimers, maxclock)
        w = np.array([1 / c[1] for c in surv])
        out_t.append(te)
        out_x.append(float(np.sum(w * np.array([c[0] for c in surv])) / w.sum()))
    ref = series_list[0]
    res = TimeSeries(np.array(out_t), np.array(out_x), name="rfc5905 combine", source_format=ref.source_format,
                     meta={"estimator": "rfc5905", "servers": len(series_list)})
    return res


def _intersect(cands, nmin):
    """Marzullo-style intersection (RFC 5905 s11.2.1): largest set of
    correctness intervals [off - lam, off + lam] with a common point, allowing
    ``f`` falsetickers with f < n/2."""
    n = len(cands)
    edges = []
    for off, lam, _ in cands:
        edges += [(off - lam, -1), (off, 0), (off + lam, 1)]
    edges.sort()
    for f in range(0, (n + 1) // 2):
        found, low = 0, None
        for e, typ in edges:
            found -= typ
            if found >= n - f:
                low = e
                break
        found, high = 0, None
        for e, typ in reversed(edges):
            found += typ
            if found >= n - f:
                high = e
                break
        if low is not None and high is not None and low <= high:
            keep = [c for c in cands if c[0] - c[1] <= high and c[0] + c[1] >= low]
            return keep if len(keep) >= nmin else []
    return []


def _cluster(cands, maxclock):
    surv = sorted(cands, key=lambda c: c[1])
    while len(surv) > maxclock:
        offs = np.array([c[0] for c in surv])
        sel = [math.sqrt(np.mean((offs - offs[i]) ** 2)) for i in range(len(surv))]
        worst = int(np.argmax(sel))
        if sel[worst] <= min(c[2] for c in surv):
            break
        surv.pop(worst)
    return surv


def median_combine(series_list: Sequence[TimeSeries]) -> TimeSeries:
    filt = [_clock_filter(s) for s in series_list]
    epochs = np.unique(np.concatenate([f[:, 0] for f in filt]))
    out = []
    for te in epochs:
        vals = [g[0] for f in filt for g in [_at(f, te, np.inf)] if g is not None]
        out.append(np.median(vals))
    return TimeSeries(epochs, np.array(out), name="median combine", meta={"estimator": "median"})


# ------------------------------------------------------- Huygens-style convex hull
_GOLD = (math.sqrt(5) - 1) / 2


def _margin_line(t: np.ndarray, upper: np.ndarray, lower: np.ndarray, max_slope: float = 5e-4):
    """Line ``a + b t`` with the largest margin below ``upper`` and above ``lower``.

    For a slope b the best intercept sits half-way between min(upper - b t)
    and max(lower - b t); the margin is half their difference, a concave
    function of b, maximised by golden-section search.
    """
    def margin(b):
        hi, lo = np.min(upper - b * t), np.max(lower - b * t)
        return (hi - lo) / 2, (hi + lo) / 2

    lo_b, hi_b = -max_slope, max_slope
    c, d = hi_b - _GOLD * (hi_b - lo_b), lo_b + _GOLD * (hi_b - lo_b)
    mc, md = margin(c)[0], margin(d)[0]
    for _ in range(48):
        if mc >= md:
            hi_b, d, md = d, c, mc
            c = hi_b - _GOLD * (hi_b - lo_b)
            mc = margin(c)[0]
        else:
            lo_b, c, mc = c, d, md
            d = lo_b + _GOLD * (hi_b - lo_b)
            md = margin(d)[0]
    b = (lo_b + hi_b) / 2
    m, a = margin(b)
    return a, b, m


def convex_hull(series: TimeSeries, samples: int = 64, window: Optional[float] = None) -> TimeSeries:
    """Huygens-style estimator (Geng et al., NSDI 2018), for one server.

    Every exchange bounds the true offset: ``θm − δ/2 ≤ θ ≤ θm + δ/2`` (the
    error of a measurement is at most half its round trip). Over a sliding
    window of the last ``samples`` exchanges (or ``window`` seconds), the
    clock offset is taken as the straight line with the largest margin
    between those upper and lower bounds; the margin is equal on both sides
    because equal floor delays are assumed, as in the paper's SVM. The
    estimate at each exchange uses only that exchange and earlier ones.
    """
    s = series.sorted()
    d = s.extra.get("delay")
    if d is None:
        raise ValueError("the convex-hull estimator needs a round-trip delay column")
    up, lo = s.offset + d / 2, s.offset - d / 2
    ok = np.isfinite(up) & np.isfinite(lo)
    out = np.full(len(s), np.nan)
    idx = np.flatnonzero(ok)
    for j, k in enumerate(idx):
        if window is not None:
            first = np.searchsorted(s.t[idx], s.t[k] - window)
            sel = idx[first: j + 1]
        else:
            sel = idx[max(0, j + 1 - samples): j + 1]
        if sel.size < 2:
            out[k] = s.offset[k]
            continue
        tt = s.t[sel] - s.t[k]  # the estimate at the newest exchange is the intercept
        a, _, _ = _margin_line(tt, up[sel], lo[sel])
        out[k] = a
    return _like(s, s.t[ok], out[ok], "hull")


# ------------------------------------------------------- ntpd-rs-style combination
def kalman_combine(series_list: Sequence[TimeSeries], nmin: int = 1, k_sigma: float = 3.0) -> TimeSeries:
    """Multi-server combination in the spirit of ntpd-rs (not its code).

    Each source gets its own delay-weighted Kalman filter (offset and
    frequency with an uncertainty). At each epoch every source contributes
    the interval ``offset ± (k·σ + floor_delay/2)``: the filter's uncertainty
    plus the asymmetry no measurement can rule out. The largest set of
    intervals with a common point is kept (Marzullo intersection, as RFC
    5905), and the survivors are averaged with inverse-variance weights.
    """
    from .filters import kalman

    filt = []
    for s in series_list:
        s = s.sorted()
        if len(s) < 4:
            continue
        kr = kalman(s, delay_weighting=True)
        dmin = float(np.nanmin(s.extra["delay"])) if "delay" in s.extra else 0.0
        filt.append((kr.t, kr.phase, kr.freq, kr.phase_sd, dmin))
    if not filt:
        raise ValueError("no source with enough samples")
    epochs = np.unique(np.concatenate([f[0] for f in filt]))
    stale = 4 * max(float(np.median(np.diff(f[0]))) for f in filt)
    out_t, out_x = [], []
    for te in epochs:
        cands = []
        for t, ph, fr, sd, dmin in filt:
            i = np.searchsorted(t, te, side="right") - 1
            if i < 0 or te - t[i] > stale:
                continue
            off = ph[i] + fr[i] * (te - t[i])
            sig = max(float(sd[i]), 1e-12)
            cands.append((off, k_sigma * sig + dmin / 2, sig))
        if not cands:
            continue
        chimers = _intersect(cands, nmin)
        if not chimers:
            continue
        w = np.array([1 / c[2] ** 2 for c in chimers])
        out_t.append(te)
        out_x.append(float(np.sum(w * np.array([c[0] for c in chimers])) / w.sum()))
    return TimeSeries(np.array(out_t), np.array(out_x), name="kalman combine",
                      source_format=series_list[0].source_format,
                      meta={"estimator": "kalman-combine", "servers": len(series_list)})


# ------------------------------------------------------- PTP clients
def _one_way(series: TimeSeries) -> Tuple[np.ndarray, np.ndarray]:
    """Per sample: the reference-to-local one-way measurement ``u`` (t2 - t1, with the offset in it) and the
    half round trip of a complete exchange (NaN where the sample has none).

    Simulated PTP series carry ``ms``/``sm``; for NTP-style series (offset, delay) every sample is a complete
    exchange and ``u = delay/2 - offset``.
    """
    ex = series.extra
    if "ms" in ex and "sm" in ex:
        ms, sm = np.asarray(ex["ms"], float), np.asarray(ex["sm"], float)
        return ms, (ms + sm) / 2
    delay = np.asarray(ex.get("delay", np.zeros(len(series))), float)
    return delay / 2 - series.offset, delay / 2


def _servo_track(t: np.ndarray, measured: np.ndarray, servo: str, servo_options: Optional[dict]) -> np.ndarray:
    """Run a PTP servo in closed loop on a free-running clock and return its correction at every sample.

    The steered clock reads ``local + c``; the servo sees the offset ``c - measured`` (local - reference) and
    sets ``dc/dt``. Steering does not change the measurement noise, so this is the closed loop exactly.
    The correction is the servo's estimate of the offset (reference - local) of the free-running clock.
    """
    from .ptpsim import make_servo

    if t.size == 0:
        return np.empty(0)
    interval = float(np.median(np.diff(t))) if t.size > 1 else 1.0
    sv = make_servo(servo, **(servo_options or {}))
    sv.reset(interval)
    out = np.empty(t.size)
    c, freq = 0.0, 0.0
    for k in range(t.size):
        if k:
            c += freq * (t[k] - t[k - 1])
        o = c - measured[k]
        freq, step = sv.sample(o, float(t[k]))
        if step:
            c -= o
        out[k] = c
    return out


def ptp4l(series: TimeSeries, delay_filter: int = 10, servo: str = "pi",
          servo_options: Optional[dict] = None) -> TimeSeries:
    """A linuxptp-style slave: E2E delay mechanism with a moving-median delay filter and a servo.

    Every Sync gives an offset ``mean_path_delay - (t2 - t1)``, where the mean path delay is the median of
    the last ``delay_filter`` Delay_Req exchanges (ptp4l's ``delay_filter moving_median``, length 10); the
    servo (``pi`` with linuxptp's default gains, or ``linreg``) steers a clock with it, and the steered
    clock's correction is the estimate. On NTP-style series every sample is an exchange.
    """
    s = series.sorted()
    u, half = _one_way(s)
    window: Deque[float] = deque(maxlen=max(1, int(delay_filter)))
    meas = np.full(len(s), np.nan)
    for k in range(len(s)):
        if np.isfinite(half[k]):
            window.append(float(half[k]))
        if window:
            meas[k] = float(np.median(window)) - u[k]
    ok = np.isfinite(meas)
    t = s.t[ok]
    est = _servo_track(t, meas[ok], servo, servo_options)
    return TimeSeries(t, est, name=f"{s.name} (ptp4l {servo})", source_format=s.source_format,
                      meta={"estimator": "ptp4l", "servo": servo, "delay_filter": int(delay_filter)})


def sptp(series: TimeSeries, delay_filter: int = 32, discard: float = 3.0, servo: str = "pi",
         servo_options: Optional[dict] = None) -> TimeSeries:
    """An SPTP-style client (after Meta's Simple PTP): client-driven unicast exchanges, each giving all four
    timestamps at once.

    Only complete exchanges are used. The mean path delay is the median of the last ``delay_filter``
    exchanges; an exchange whose path delay exceeds that median by more than ``discard`` times the
    window's median absolute deviation is discarded (queueing outliers); the others give an offset
    ``mean_path_delay - (t2 - t1)`` that a servo (``pi`` by default) tracks. A model of the approach, not of
    a particular release.
    """
    s = series.sorted()
    u, half = _one_way(s)
    window: Deque[float] = deque(maxlen=max(1, int(delay_filter)))
    keep = np.zeros(len(s), dtype=bool)
    meas = np.full(len(s), np.nan)
    for k in range(len(s)):
        h = half[k]
        if not np.isfinite(h):
            continue
        if len(window) >= 4:
            w = np.asarray(window)
            med = float(np.median(w))
            mad = float(np.median(np.abs(w - med))) * 1.4826
            if discard and h - med > discard * max(mad, 1e-12):
                window.append(float(h))  # the filter keeps learning the delay distribution
                continue
        window.append(float(h))
        meas[k] = float(np.median(window)) - u[k]
        keep[k] = True
    t = s.t[keep]
    est = _servo_track(t, meas[keep], servo, servo_options)
    return TimeSeries(t, est, name=f"{s.name} (sptp {servo})", source_format=s.source_format,
                      meta={"estimator": "sptp", "servo": servo, "delay_filter": int(delay_filter),
                            "discarded": int(np.isfinite(half).sum() - keep.sum())})


# ------------------------------------------------------- registration
def _builtin():
    from .filters import kalman_series
    from .network import min_delay_filter

    register(FunctionEstimator("raw", lambda s: s, description="measurements as is"))
    register(FunctionEstimator("kalman", lambda s: kalman_series(s, delay_weighting=False), description="Kalman filter"))
    register(FunctionEstimator("kalman-dw", kalman_series, description="Kalman, delay-weighted"))
    register(FunctionEstimator("rts-dw", lambda s: kalman_series(s, smooth=True), description="RTS smoother, delay-weighted (offline)"))
    register(FunctionEstimator("mindelay", min_delay_filter, description="RFC 5905 clock filter (min delay of 8)"))
    register(FunctionEstimator("regression", regression, description="chrony-style weighted regression + runs test"))
    register(FunctionEstimator("feedforward", feedforward, description="RADclock-style feed-forward"))
    register(FunctionEstimator("hull", convex_hull,
                               description="Huygens-style: max-margin line through the offset bounds of a window"))
    register(FunctionEstimator("ptp4l", ptp4l,
                               description="linuxptp-style slave: moving-median path delay + PI servo"))
    register(FunctionEstimator("sptp", sptp,
                               description="SPTP-style client: complete exchanges, delay-outlier discard + PI servo"))
    register(FunctionEstimator("rfc5905", rfc5905_combine, multi=True, description="RFC 5905 select/cluster/combine"))
    register(FunctionEstimator("median", median_combine, multi=True, description="median of clock-filter outputs"))
    register(FunctionEstimator("kalman-combine", kalman_combine, multi=True,
                               description="ntpd-rs-style: per-source Kalman, intersection, inverse-variance mean"))


_builtin()


def run(est: Union[str, Estimator], data) -> TimeSeries:
    est = get(est) if isinstance(est, str) else est
    if est.multi:
        return est.fit(list(data) if isinstance(data, (list, tuple)) else [data])
    return est.fit(data[0] if isinstance(data, (list, tuple)) else data)
