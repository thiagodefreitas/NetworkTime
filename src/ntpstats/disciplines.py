# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Clock-discipline models for the research bench: ntpd's loop and Levine's NIST algorithms.

Like the ``ptp4l`` and ``sptp`` estimators, each model steers a clock in
closed loop on the free-running clock of a scenario: the steered clock reads
``local + c(t)``, every measurement is seen as the residual
``offset - c(t)``, and the correction ``c(t)`` at each measurement time is the
estimate of the offset (reference - local). Steering does not change the
measurement noise, so this is the closed loop exactly.

``ntpd``
    The daemon clock discipline of the NTP reference implementation (ntpd
    4.2.8, ``ntpd/ntp_loopfilter.c``, without the kernel PLL): the clock
    filter (minimum delay of the last eight samples, used only when newer than
    the last update; among equal delays the newest, as the RFC's sort keeps
    it first; during the startup clamp, when ntpd does not sort, the newest
    sample; samples older than the Allan intercept ranked by delay plus their
    grown dispersion), the popcorn spike suppressor of ``ntp_proto.c`` (a new
    best sample whose offset differs from the previous one by more than three
    times the filter jitter, less than two poll intervals after the last sample
    used, is ignored), the state machine (NSET, FREQ, SYNC, SPIK; step
    threshold 128 ms, stepout 300 s), the hybrid PLL/FLL frequency update and
    the phase adjustment once per second, with the total slew (frequency plus
    phase) bounded at 500 ppm as in ``adj_host_clock()``. ``constants="rfc5905"`` uses the constants and
    gain formulas of the RFC 5905 appendix (A.5.5.6, A.5.6.1) instead: PLL gain
    65536, FLL gain 1/(18 - poll), Allan intercept 1500 s, stepout 900 s, the
    phase adjusted by offset/(PLL min(2^poll, 1500 s)) per second, without
    the 500 ppm bound on the slew (the appendix's ``clock_adjust()`` has none).
    The clock filter, popcorn suppressor and state machine are ntpd's in both
    cases. (The appendix's own suppressor, A.5.2, compares the interval in
    seconds with twice the poll *exponent* and sums the squared offset
    differences without averaging; ntpd's version is used instead.)
    The time constant (poll exponent) is fixed at the measurement interval,
    as with ``minpoll = maxpoll``; ``popcorn=False`` turns the suppressor off.
``lockclock``
    J. Levine's frequency-lock loop for the NIST time servers, as described in
    J. Res. NIST 125:125008 (2020), section 6: a five-point majority vote on the
    measurements of each cycle; time-adjustment mode while the residual
    exceeds 3 sigma; otherwise a frequency estimate y = dx/T (Eq. 3) averaged
    as ybar = (y + k ybar) / (k + 1) (Eq. 5) plus a phase correction that
    removes dx over the next cycle; and the outlier rule of section 7 (the
    frequency is not updated when its innovation exceeds three times the mean
    innovation of the preceding cycles). Defaults are the paper's network
    configuration: a cycle of about 1000 s and k = 1.
``levine-kalman``
    LOCKCLOCK with the scalar Kalman time estimate of J. Levine, PTTI 2011
    ("Synchronizing computer clocks by the use of Kalman filters", Eq. 5): the
    phase correction applies only the fraction sigma_o^2 / (sigma_o^2 +
    sigma_t^2) of the residual, where sigma_t^2 is the variance of the
    measurement (link) noise (the 1-sample deviation used by the vote) and
    sigma_o^2 that of the clock's time dispersion over one cycle. As in the
    paper, the Kalman filter estimates only the time state; the frequency
    comes from the LOCKCLOCK loop (Eq. 3 then uses the time difference left
    after the previous partial correction). Levine measured
    sigma_o^2 = <(x_k - x_k^-)^2> (his Eq. 4) with a reference of negligible
    noise; without one, the model estimates it online as the mean square of
    the last eight cycle residuals (whose variance is sigma_o^2 + sigma_t^2)
    minus sigma_t^2, unless ``sigma_o`` is given.

These are models written from the published code and papers, not the
programs themselves.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from .series import TimeSeries

MAXFREQ = 500e-6
PHI = 15e-6  # dispersion growth, s/s
SGATE = 3.0  # popcorn spike gate
MAXDIST = 1.5  # sys_maxdist, s

#: the two constant sets of the ntpd model
NTPD_CONSTANTS: Dict[str, Dict[str, float]] = {
    # ntpd 4.2.8, ntpd/ntp_loopfilter.c
    "ntpd": {"step": 0.128, "stepout": 300.0, "pll": 16.0, "fll": 0.25, "allan": 2.0 ** 11, "avg": 8.0,
             "floor": 0.0005, "startup": 300.0},
    # RFC 5905, appendix A.5.5.6 and A.5.6.1
    "rfc5905": {"step": 0.128, "stepout": 900.0, "pll": 65536.0, "fll": 18.0, "allan": 1500.0, "avg": 4.0,
                "floor": 0.0, "startup": 0.0},
}

NSET, FSET, FREQ, SYNC, SPIK = "NSET", "FSET", "FREQ", "SYNC", "SPIK"


@dataclass
class _NtpdState:
    state: str = NSET
    drift: float = 0.0  # drift_comp, s/s
    offset: float = 0.0  # clock_offset, the residual being amortised
    last: float = 0.0  # last_offset
    epoch: float = 0.0  # clock_epoch
    freq_cnt: float = 0.0  # startup clamp, seconds
    jitter: float = 0.0
    c: float = 0.0  # correction applied so far
    steps: int = 0


def _poll_exponent(t: np.ndarray, poll: Optional[int]) -> int:
    if poll is not None:
        return int(poll)
    interval = float(np.median(np.diff(t))) if t.size > 1 else 64.0
    return int(min(17, max(3, round(math.log2(max(interval, 1.0))))))


def ntpd_discipline(series: TimeSeries, constants: str = "ntpd", poll: Optional[int] = None,
                    initial_frequency: Optional[float] = None, stages: int = 8,
                    popcorn: bool = True) -> TimeSeries:
    """ntpd's clock discipline in closed loop (see the module docstring).

    ``poll`` is the time constant exponent (log2 s; default: the measurement
    interval). ``initial_frequency`` (s/s) starts in FSET state as if a drift
    file existed; otherwise the loop starts in NSET and measures the frequency
    directly after the stepout interval. ``popcorn`` enables ntpd's popcorn
    spike suppressor.
    """
    if constants not in NTPD_CONSTANTS:
        raise ValueError(f"constants must be one of {', '.join(NTPD_CONSTANTS)}")
    k = NTPD_CONSTANTS[constants]
    rfc = constants == "rfc5905"
    s = series.sorted()
    t, meas = s.t, s.offset
    delay = np.asarray(s.extra.get("delay", np.zeros(len(s))), dtype=float)
    p = _poll_exponent(t, poll)
    tc = 2.0 ** p
    st = _NtpdState(freq_cnt=k["startup"])
    if initial_frequency is not None:
        st.state, st.drift = FSET, float(initial_frequency)
    st.epoch = float(t[0]) if t.size else 0.0
    est = np.empty(t.size)
    filt: Deque[Tuple[float, float, float]] = deque(maxlen=max(1, int(stages)))
    last_used = -math.inf
    peer_offset = 0.0
    popcorns = 0
    tick = float(t[0]) if t.size else 0.0  # next one-second adjustment
    precision = 2.0 ** -20

    def adjust_second():
        # adj_host_clock() / clock_adjust(): one second of phase and frequency adjustment
        if st.state != SYNC:
            adj = 0.0
        elif rfc:
            adj = st.offset / (k["pll"] * min(tc, k["allan"]))
        elif st.freq_cnt > 0:
            adj = st.offset / (k["pll"] * 2.0)
            st.freq_cnt -= 1
        else:
            adj = st.offset / (k["pll"] * tc)
        if not rfc:  # the total slew is bounded at NTP_MAXFREQ
            adj = min(max(adj, -MAXFREQ - st.drift), MAXFREQ - st.drift)
        st.offset -= adj
        st.c += st.drift + adj

    for i in range(t.size):
        while tick <= t[i]:
            adjust_second()
            tick += 1.0
        est[i] = st.c
        r = meas[i] - st.c
        now = float(t[i])
        filt.append((now, float(r), float(delay[i])))
        if st.freq_cnt > 0:
            order = sorted(filt, key=lambda x: -x[0])  # not sorted during the startup clamp: newest first
        else:
            def dist(x, now=now):
                age = now - x[0]
                return x[2] + PHI * age if age > k["allan"] else x[2]
            order = sorted(filt, key=lambda x: (dist(x), -x[0]))  # increasing distance; newest first among equals
        sel = order[0]
        m = sum(1 for j, x in enumerate(order) if not (j >= 2 and x[2] >= MAXDIST))
        jitter = math.sqrt(sum((x[1] - sel[1]) ** 2 for x in order[:m]) / max(m - 1, 1))
        jitter = max(jitter, precision)
        etemp = abs(peer_offset - sel[1])
        peer_offset = sel[1]
        if popcorn and etemp > SGATE * jitter and sel[0] - last_used < 2.0 * tc:
            popcorns += 1
            continue  # popcorn spike
        if sel[0] <= last_used:
            continue  # the clock filter passes only samples newer than the last one used
        last_used = sel[0]
        _local_clock(st, sel[1], float(t[i]), k, rfc, tc, precision)
        if st.state == "STEPPED":
            st.state = SYNC
            filt.clear()
            last_used = float(t[i])
            peer_offset = 0.0
    meta = {"estimator": "ntpd", "constants": constants, "poll": p, "steps": st.steps,
            "popcorns": popcorns, "frequency": st.drift, "state": st.state}
    return TimeSeries(t, est, name=f"{s.name} (ntpd {constants})", source_format=s.source_format, meta=meta)


def _local_clock(st: _NtpdState, off: float, now: float, k: Dict[str, float], rfc: bool, tc: float,
                 precision: float) -> None:
    mu = now - st.epoch
    freq = st.drift

    def rstclock(state: str, offset: float) -> None:
        st.state, st.offset, st.last, st.epoch = state, offset, offset, now

    def step() -> None:
        st.c += off
        st.steps += 1
        st.jitter = precision

    if abs(off) > k["step"]:
        if st.state == SYNC:
            st.state = SPIK
            return
        if st.state == FREQ:
            if mu < k["stepout"]:
                return
            freq = off / mu
            st.drift = max(-MAXFREQ, min(MAXFREQ, freq))
        elif st.state == SPIK:
            if mu < k["stepout"]:
                return
        was_nset = st.state == NSET
        step()
        if was_nset:
            rstclock(FREQ, 0.0)
            return
        rstclock(SYNC, 0.0)
        st.state = "STEPPED"
        st.drift = max(-MAXFREQ, min(MAXFREQ, freq))
        return
    st.jitter = math.sqrt(st.jitter ** 2 + (max(abs(off - st.last), precision) ** 2 - st.jitter ** 2) / k["avg"])
    if st.state == NSET:
        st.c += off  # adj_systime(): the first offset is slewed out at once
        rstclock(FREQ, off)
        return
    if st.state == FREQ:
        if mu < k["stepout"]:
            return
        freq = off / mu  # direct_freq()
    if rfc:
        if tc > k["allan"] / 2:
            g = max(k["fll"] - math.log2(tc), 4.0)
            freq += (off - st.offset) / (max(mu, k["allan"]) * g)
        freq += off * min(mu, tc) / (4 * k["pll"] * tc) ** 2
        rstclock(SYNC, off)
    else:
        if st.freq_cnt <= 0:
            if tc >= k["allan"]:
                freq += (off - st.offset) / max(tc, mu) * k["fll"]
            freq += off * min(k["allan"], mu) / (4 * k["pll"] * tc) ** 2
        rstclock(SYNC, off)
        if abs(off) < k["floor"]:
            st.freq_cnt = 0
    st.drift = max(-MAXFREQ, min(MAXFREQ, freq))


# ------------------------------------------------------------------ Levine (NIST)
def _vote(x: List[float], sigma: float) -> Optional[float]:
    """The five-point majority vote of Levine (2020), section 6: drop the extreme farther from its neighbour
    until the spread is below 3 sigma; None if three points still disagree."""
    v = sorted(x)
    while len(v) >= 3:
        if v[-1] - v[0] < 3 * sigma:
            return float(np.mean(v))
        if len(v) == 3 and len(x) > 3:
            return None
        a, b = v[-1] - v[-2], v[1] - v[0]
        if a > b:
            v = v[:-1]
        elif b > a:
            v = v[1:]
        else:
            v = v[1:-1]
    if len(v) and len(x) < 3:
        return float(np.mean(v))
    return None


def lockclock(series: TimeSeries, cycle: float = 1024.0, k: float = 1.0, sigma: Optional[float] = None,
              points: int = 5, max_rate: float = MAXFREQ, kalman: bool = False,
              sigma_o: Optional[float] = None) -> TimeSeries:
    """Levine's LOCKCLOCK frequency-lock loop (J. Res. NIST 2020, section 6), or with ``kalman=True`` its
    scalar Kalman time estimate (PTTI 2011). See the module docstring.

    ``cycle`` is the interval between frequency updates (s), ``k`` the averaging constant of Eq. 5, ``sigma``
    the 1-sample time deviation used by the vote and the 3-sigma tests (default: estimated robustly from the
    first differences of the measurements), ``points`` the measurements voted on per cycle.

    In time-adjustment mode the paper adjusts every second, so the clock's frequency error is negligible
    between adjustments. With the bench's longer measurement intervals it is not, so in that mode the model
    adjusts at every measurement and also estimates the frequency from successive residuals (Eq. 3 and 5);
    without that, a clock with a large frequency offset would never leave the time-adjustment mode.
    """
    s = series.sorted()
    t, meas = s.t, s.offset
    if sigma is None:
        d = np.diff(meas[: min(len(meas), 64)])
        sigma = float(np.median(np.abs(d - np.median(d))) * 1.4826 / math.sqrt(2)) if d.size else 1e-3
        sigma = max(sigma, 1e-9)
    gain = 1.0
    st2 = sigma ** 2
    sq: Deque[float] = deque(maxlen=8)  # recent squared cycle residuals (Kalman variant)
    left = 0.0  # time difference deliberately left after the previous correction (Kalman variant)
    est = np.empty(t.size)
    c, rate = 0.0, 0.0
    ybar: Optional[float] = None
    innovations: Deque[float] = deque(maxlen=max(1, int(round(k))) + 2)
    last_t = float(t[0]) if t.size else 0.0
    prev_t: Optional[float] = None  # time of the previous adjustment
    buf: List[float] = []
    mode = "time"

    def update_frequency(dx: float, T: float) -> None:
        nonlocal ybar
        # Eq. 3: the change of the time difference over the cycle; the previous adjustment drove it to
        # zero (LOCKCLOCK) or to ``left`` (Kalman variant). The frequency already applied is added back.
        y = (dx - left) / T + (ybar or 0.0)
        if ybar is None:
            ybar = y
            return
        inn = abs(y - ybar)
        ok = len(innovations) < 3 or inn <= 3 * float(np.mean(innovations))
        innovations.append(inn)
        if ok:
            ybar = (y + k * ybar) / (k + 1)  # Eq. 5

    for i in range(t.size):
        c += rate * (t[i] - last_t)
        last_t = float(t[i])
        est[i] = c
        buf.append(float(meas[i] - c))
        buf = buf[-points:]
        if mode == "frequency" and prev_t is not None and t[i] - prev_t < cycle:
            continue
        dx = _vote(buf, sigma)
        buf = []
        if dx is None:
            continue
        T = float(t[i] - prev_t) if prev_t is not None else 0.0
        if abs(dx) > 1.0:  # cold start: step the clock
            c += dx
            prev_t, left = float(t[i]), 0.0
            continue
        if mode == "time" and abs(dx) > 3 * sigma:
            if T > 0:
                update_frequency(dx, T)
            nxt = float(np.median(np.diff(t[i: i + 3]))) if i + 2 < t.size else max(T, 1.0)
            rate = (ybar or 0.0) + max(-max_rate, min(max_rate, dx / max(nxt, 1.0)))
            prev_t, left = float(t[i]), 0.0
            continue
        mode = "frequency"
        if T > 0:
            update_frequency(dx, T)
        if kalman:
            sq.append(dx * dx)
            so2 = sigma_o ** 2 if sigma_o is not None else max(float(np.mean(sq)) - st2, 0.0)
            gain = so2 / (so2 + st2) if so2 + st2 > 0 else 1.0
        corr = gain * dx  # Eq. 5 of the 2011 paper: the weighted time estimate (all of dx for LOCKCLOCK)
        rate = (ybar or 0.0) + max(-max_rate, min(max_rate, corr / cycle))
        prev_t, left = float(t[i]), dx - corr
    name = "levine-kalman" if kalman else "lockclock"
    return TimeSeries(t, est, name=f"{s.name} ({name})", source_format=s.source_format,
                      meta={"estimator": name, "cycle": cycle, "k": k, "sigma": sigma, "gain": gain,
                            "frequency": ybar, "mode": mode})


def _register() -> None:
    from .estimators import FunctionEstimator, register

    register(FunctionEstimator("ntpd", ntpd_discipline,
                               description="ntpd 4.2.8 clock discipline (clock filter, PLL/FLL, state machine)"))
    register(FunctionEstimator("ntpd-rfc", lambda s: ntpd_discipline(s, constants="rfc5905"),
                               description="the clock discipline with the RFC 5905 appendix constants"))
    register(FunctionEstimator("lockclock", lockclock,
                               description="Levine's NIST frequency-lock loop (J. Res. NIST 2020)"))
    register(FunctionEstimator("levine-kalman", lambda s: lockclock(s, kalman=True),
                               description="LOCKCLOCK with Levine's scalar Kalman time estimate (PTTI 2011)"))
