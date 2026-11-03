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
    as with ``minpoll = maxpoll``, unless ``maxpoll`` is given: then the model
    adapts it as ``local_clock()`` does (``CLOCK_PGATE`` 4, ``CLOCK_LIMIT``
    30, with the time gates of ntpd bug 3615) and only uses the measurements
    it would have sent, one per current poll interval, out of a series sampled
    at ``2**minpoll``. ``popcorn=False`` turns the suppressor off.
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
``chrony``
    chrony's discipline for one NTP source (chrony 4.x: ``sourcestats.c``,
    ``regress.c``, ``reference.c``, ``sys_generic.c``, ``ntp_core.c``): the
    samples' weights from their peer distance (delay/2 + dispersion, relative
    to the median, ``SD_TO_DIST_RATIO`` 0.7); the weighted linear regression
    over the newest samples that passes the runs test (oldest samples dropped
    one by one until the residuals have more sign runs than the 5 % critical
    value; older samples extend the test, ``REGRESS_RUNS_RATIO`` 2; at most 64
    samples); the frequency updated by the skew-weighted gain
    3 skew^2 / (3 skew^2 + skew_new^2), skew from the 99.95 % t quantile and
    ``maxupdateskew`` 1000 ppm; the offset slewed out at the correction rate
    ``corrtimeratio`` (3) x offset_sd/2 x update interval, the slew lasting
    rate/|offset| (1 to 10^4 s) and bounded by ``maxslewrate`` (83333 ppm);
    ``makestep`` (default 1 s for the first 3 updates). With ``maxpoll`` the
    poll interval adapts as ``ntp_core.c`` does: back off by log2(error /
    peer distance) when the new sample is not predicted within the peer
    distance, else keep the number of regression samples near ``polltarget``
    (8). Test C of ``ntp_core.c`` drops a sample whose delay exceeds the
    register's minimum by more than ``maxdelaydevratio`` (10) times the
    regression's standard deviation plus the dispersion growth, unless its
    offset error is larger still. Not modelled: source selection and combining
    (one source), the sample filter, the other delay tests (off by default)
    and asymmetry correction, and the kernel's own slewing (the slew is the
    generic driver's).

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
    poll: int = 6  # sys_poll
    tc_counter: int = 0
    twinlo: float = -math.inf  # no step down before this time (bug 3615)
    twinhi: float = -math.inf  # no step up before this time
    minpoll: int = 6
    maxpoll: int = 6


def _poll_exponent(t: np.ndarray, poll: Optional[int]) -> int:
    if poll is not None:
        return int(poll)
    interval = float(np.median(np.diff(t))) if t.size > 1 else 64.0
    return int(min(17, max(3, round(math.log2(max(interval, 1.0))))))


def ntpd_discipline(series: TimeSeries, constants: str = "ntpd", poll: Optional[int] = None,
                    initial_frequency: Optional[float] = None, stages: int = 8,
                    popcorn: bool = True, maxpoll: Optional[int] = None) -> TimeSeries:
    """ntpd's clock discipline in closed loop (see the module docstring).

    ``poll`` is the time constant exponent (log2 s; default: the measurement
    interval). With ``maxpoll``, ``poll`` is ``minpoll`` and the model adapts
    the poll exponent between them, using only the measurements it would have
    sent; the result's ``extra["poll"]`` and ``meta["polls"]`` record it.
    ``initial_frequency`` (s/s) starts in FSET state as if a drift file
    existed; otherwise the loop starts in NSET and measures the frequency
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
    adaptive = maxpoll is not None
    if adaptive and int(maxpoll) < p:  # type: ignore[arg-type]
        raise ValueError("maxpoll must not be below minpoll")
    st = _NtpdState(freq_cnt=k["startup"], poll=p, minpoll=p, maxpoll=int(maxpoll) if adaptive else p)  # type: ignore[arg-type]
    tc = 2.0 ** st.poll
    polls = np.empty(t.size)
    next_send = -math.inf
    used = 0
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
        polls[i] = st.poll
        if adaptive and t[i] < next_send - 0.5:  # not polled: ntpd sends one packet per 2**poll seconds
            continue
        next_send = float(t[i]) + 2.0 ** st.poll
        used += 1
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
        _local_clock(st, sel[1], float(t[i]), k, rfc, tc, precision, adaptive)
        if 2.0 ** st.poll != tc:  # poll_update(): new time constant and packet interval
            tc = 2.0 ** st.poll
            next_send = float(t[i]) + tc
        if st.state == "STEPPED":
            st.state = SYNC
            filt.clear()
            last_used = float(t[i])
            peer_offset = 0.0
    meta = {"estimator": "ntpd", "constants": constants, "poll": st.poll, "steps": st.steps,
            "popcorns": popcorns, "frequency": st.drift, "state": st.state, "measurements_used": used}
    extra = {}
    if adaptive:
        changes = np.flatnonzero(np.diff(polls)) + 1 if polls.size else np.array([], dtype=int)
        meta.update(minpoll=p, maxpoll=st.maxpoll,
                    polls=[(float(t[0]), int(polls[0]))] + [(float(t[j]), int(polls[j])) for j in changes])
        extra["poll"] = polls
    return TimeSeries(t, est, name=f"{s.name} (ntpd {constants})", source_format=s.source_format, meta=meta,
                      extra=extra)


def _local_clock(st: _NtpdState, off: float, now: float, k: Dict[str, float], rfc: bool, tc: float,
                 precision: float, adaptive: bool = False) -> None:
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
        if adaptive:
            _poll_adjust(st, off, now)
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
    if adaptive:
        _poll_adjust(st, off, now)


CLOCK_PGATE = 4.0  # poll-adjust gate
CLOCK_LIMIT = 30  # poll-adjust threshold


def _poll_adjust(st: _NtpdState, off: float, now: float) -> None:
    """The time-constant adjustment at the end of ntpd's ``local_clock()``."""
    old = st.poll
    if st.freq_cnt > 0:  # not during the startup clamp
        st.tc_counter, st.twinlo, st.twinhi = 0, now, now
    elif abs(off) < CLOCK_PGATE * st.jitter:
        st.tc_counter += st.poll
        if st.tc_counter > CLOCK_LIMIT:
            st.tc_counter = CLOCK_LIMIT
            if st.poll < st.maxpoll and now >= st.twinhi:
                st.poll += 1
    else:
        st.tc_counter -= st.poll << 1
        if st.tc_counter < -CLOCK_LIMIT:
            st.tc_counter = -CLOCK_LIMIT
            if st.poll > st.minpoll and now >= st.twinlo:
                st.poll -= 1
    if st.poll != old:
        deadband = float(1 << (st.poll - 1))
        st.tc_counter = 0
        st.twinlo = now + max(deadband, 60.0)
        st.twinhi = st.twinlo + deadband


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


# ------------------------------------------------------------------ chrony
#: 5 % critical number of runs (regress.c), indexed by the number of residuals
CRITICAL_RUNS = (
    0, 0, 0, 0, 0, 0, 0, 0, 2, 3, 3, 3, 4, 4, 5, 5, 5, 6, 6, 7, 7, 7, 8, 8, 9, 9, 9, 10, 10, 11,
    11, 11, 12, 12, 13, 13, 14, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18, 18, 19, 19, 20, 20, 21, 21, 21,
    22, 22, 23, 23, 24, 24, 25, 25, 26, 26, 26, 27, 27, 28, 28, 29, 29, 30, 30, 30, 31, 31, 32, 32, 33,
    33, 34, 34, 35, 35, 35, 36, 36, 37, 37, 38, 38, 39, 39, 40, 40, 40, 41, 41, 42, 42, 43, 43, 44, 44,
    45, 45, 46, 46, 46, 47, 47, 48, 48, 49, 49, 50, 50, 51, 51, 52, 52, 52, 53, 53, 54, 54, 55, 55, 56)
#: 99.95 % quantile of Student's t (regress.c RGR_GetTCoef), by degrees of freedom
T_COEF = (636.6, 31.6, 12.92, 8.61, 6.869, 5.959, 5.408, 5.041, 4.781, 4.587, 4.437, 4.318, 4.221, 4.140,
          4.073, 4.015, 3.965, 3.922, 3.883, 3.850, 3.819, 3.792, 3.768, 3.745, 3.725, 3.707, 3.690, 3.674,
          3.659, 3.646, 3.633, 3.622, 3.611, 3.601, 3.591, 3.582, 3.574, 3.566, 3.558, 3.551)
RUNS_RATIO = 2
MIN_REGRESS = 3
CHRONY_MAX_SAMPLES = 64
WORST_FREQ_BOUND = 2000e-6
MIN_SKEW, MAX_SKEW = 1e-12, 1.0
MIN_SLEW, MAX_SLEW = 1.0, 1e4


def _runs(r: np.ndarray) -> int:
    s = np.sign(r)
    return 1 + int(np.sum(~(((s[:-1] < 0) & (s[1:] < 0)) | ((s[:-1] > 0) & (s[1:] > 0))))) if r.size else 0


def _best_regression(x: np.ndarray, y: np.ndarray, w: np.ndarray, n: int, m: int, min_samples: int):
    """``RGR_FindBestRegression``: x, y hold m runs-only samples then the n samples; w the n weights.

    Returns (intercept, slope, intercept_sd, slope_sd, start, dof, variance) or None.
    """
    if n < MIN_REGRESS:
        return None
    xs, ys = x[m:], y[m:]
    start = 0
    while True:
        ww = 1.0 / w[start:]
        W = ww.sum()
        u = (xs[start:] * ww).sum() / W
        ui = xs[start:] - u
        V = (ui * ui * ww).sum()
        b = (ys[start:] * ui * ww).sum() / V
        a = (ys[start:] * ww).sum() / W - b * u
        resid_start = max(n - (n - start) * RUNS_RATIO, -m)
        resid = y[m + resid_start:] - a - b * x[m + resid_start:]
        nres = n - resid_start
        if (_runs(resid) > CRITICAL_RUNS[min(nres, len(CRITICAL_RUNS) - 1)] or n - start <= MIN_REGRESS
                or n - start <= min_samples):
            break
        start += 1
    r = resid[start - resid_start:]
    npts = n - start
    ss = float((r * r / w[start:]).sum()) / (npts - 2)
    sb1 = math.sqrt(ss / V)
    sb0 = math.sqrt(ss / W + (u * sb1) ** 2)
    return a, b, sb0, sb1, start, npts - 2, ss * npts / W


def _chrony_poll(score: float, poll: int, lo: int, hi: int) -> Tuple[float, int]:
    """``adjust_poll()`` of chrony's ntp_core.c, with ``score`` already including the adjustment."""
    if score >= 1.0:
        poll += int(score)
        score -= int(score)
    if score < 0.0:
        poll += int(score - 1.0)
        score -= int(score - 1.0)
    if poll < lo:
        return 0.0, lo
    if poll > hi:
        return 1.0, hi
    return score, poll


def _prune(hist: list, n_act: int, k: int) -> Tuple[list, int]:
    """``prune_register()``: drop the k oldest samples, which then only extend the runs test."""
    n_act -= k
    runs = min(len(hist) - n_act, n_act * (RUNS_RATIO - 1))
    return hist[len(hist) - n_act - runs:], n_act


def chrony_discipline(series: TimeSeries, maxpoll: Optional[int] = None, polltarget: int = 8,
                      corrtimeratio: float = 3.0, maxupdateskew: float = 1000e-6, maxslewrate: float = 83333e-6,
                      makestep: Optional[Tuple[float, int]] = (1.0, 3), max_samples: int = CHRONY_MAX_SAMPLES,
                      min_samples: int = 1, precision: float = 2.0 ** -20, maxdelaydevratio: float = 10.0,
                      maxclockerror: float = 1e-6) -> TimeSeries:
    """chrony's clock discipline for one source in closed loop (see the module docstring).

    The series is the free-running clock's offset (reference - local) with an
    optional ``delay`` and ``dispersion``. Without ``maxpoll`` every
    measurement is used; with it, the measurements are taken as sampled at
    minpoll and the model polls at its own, adapted interval (``extra["poll"]``,
    ``meta["polls"]``). ``makestep`` is (threshold s, number of updates), or
    None for chrony's default of never stepping. ``maxdelaydevratio`` is
    chrony's test C (0 disables it); rejected samples are counted in
    ``meta["delay_rejected"]``.
    """
    s = series.sorted()
    t, y = s.t, s.offset
    n_all = t.size
    delay = np.abs(np.asarray(s.extra.get("delay", np.zeros(n_all)), dtype=float))
    disp = np.abs(np.asarray(s.extra.get("dispersion", np.zeros(n_all)), dtype=float))
    minpoll = _poll_exponent(t, None)
    adaptive = maxpoll is not None
    if adaptive and int(maxpoll) < minpoll:  # type: ignore[arg-type]
        raise ValueError("maxpoll must not be below the measurement interval")
    poll, score = minpoll, 0.0
    hi = int(maxpoll) if adaptive else minpoll  # type: ignore[arg-type]
    max_samples = max(1, min(int(max_samples), CHRONY_MAX_SAMPLES))
    # clock: correction c, commanded frequency F, offset register R slewed at rate r until slew_end
    c = F = R = r = 0.0
    now = float(t[0]) if n_all else 0.0
    slew_end = now
    corr_rate = 0.0
    our_skew = 1.0
    last_update: Optional[float] = None
    updates = steps = used = 0
    hist: List[Tuple[float, float, float, float]] = []  # (t, y, delay, dispersion), runs samples first
    n_act = 0
    fit = None  # (t_ref, intercept, slope) of the last regression, in the free clock's frame
    std_dev, reg_skew = 4.0, WORST_FREQ_BOUND
    rejected = 0
    est = np.empty(n_all)
    polls = np.empty(n_all)
    next_send = -math.inf

    def advance(to: float) -> None:
        nonlocal c, R, r, now
        while r and to >= slew_end:
            c += (F + r) * (slew_end - now)
            R -= r * (slew_end - now)
            now, r = slew_end, 0.0
            reslew()
        c += (F + r) * (to - now)
        R -= r * (to - now)
        now = to

    def reslew() -> None:  # sys_generic.c update_slew()
        nonlocal r, slew_end
        if abs(R) < 1e-9:
            r, slew_end = 0.0, now
            return
        dur = min(max(corr_rate / abs(R), MIN_SLEW), MAX_SLEW)
        rate = max(-maxslewrate, min(maxslewrate, R / dur))
        r = rate
        slew_end = now + min(max(R / rate, MIN_SLEW), MAX_SLEW)

    for i in range(n_all):
        advance(float(t[i]))
        est[i] = c
        polls[i] = poll
        if adaptive and t[i] < next_send - 0.5:
            continue
        next_send = float(t[i]) + 2.0 ** poll
        used += 1
        predicted = fit[1] + fit[2] * (t[i] - fit[0]) if fit is not None else None  # SST_PredictOffset
        if maxdelaydevratio > 0 and n_act >= 6 and predicted is not None:  # test C, check_delay_dev_ratio()
            ago = float(t[i]) - fit[0]
            max_delta = std_dev * maxdelaydevratio + ago * (reg_skew + maxclockerror)
            delta = (float(delay[i]) - min(h[2] for h in hist[len(hist) - n_act:])) / 2.0
            if delta > max_delta and not abs(float(y[i]) - predicted) - delta > max_delta:
                rejected += 1
                if adaptive:
                    score, poll = _chrony_poll(score + 0.1, poll, minpoll, hi)
                    next_send = float(t[i]) + 2.0 ** poll
                continue
        # SST_AccumulateSample: make room, then add
        if n_act and n_act >= max_samples:
            hist, n_act = _prune(hist, n_act, 1)
        hist.append((float(t[i]), float(y[i]), float(delay[i]), float(disp[i])))
        n_act += 1
        m = len(hist) - n_act
        arr = np.array(hist)
        xb = arr[:, 0] - arr[-1, 0]
        dist = 0.5 * arr[m:, 2] + arr[m:, 3]
        dmin = float(dist.min())
        sd = (float(np.median(dist)) - dmin) / 0.7
        sd = min(max(sd, precision), dmin) if dmin > 0 else precision
        dmin += precision
        wts = np.where(dist > dmin, (1.0 + (dist - dmin) / max(sd, 1e-300)) ** 2, 1.0)
        reg = _best_regression(xb, arr[:, 1], wts, n_act, m, min(min_samples, max_samples))
        if reg is not None:
            a, b, sb0, sb1, start, dof, var = reg
            skew = min(max(sb1 * (T_COEF[dof - 1] if dof <= 40 else 3.5), MIN_SKEW), MAX_SKEW)
            std_dev, reg_skew = max(1e-9, math.sqrt(var)), skew
            off_sd = sb0
            if start:
                hist, n_act = _prune(hist, n_act, start)
            fit = (float(t[i]), a, b)
        else:
            a, b, skew, off_sd = float(y[i]), F, WORST_FREQ_BOUND, 4.0
            std_dev, reg_skew = 4.0, WORST_FREQ_BOUND
            fit = (float(t[i]), a, F) if n_act >= 1 else None
        # REF_SetReference: frequency by skew-weighted gain, offset into the slewed register
        interval = 0.0 if last_update is None else float(t[i]) - last_update
        last_update = float(t[i])
        mf = b - F if reg is not None else 0.0
        gain = 0.0 if abs(skew) > maxupdateskew else 3 * our_skew ** 2 / (3 * our_skew ** 2 + skew ** 2)
        gain = min(max(gain, 0.0), 1.0)
        ef = gain * mf
        extra_skew = math.sqrt(ef ** 2 * (1 - gain) + (mf - ef) ** 2 * gain)
        our_skew = max(our_skew + gain * (skew - our_skew) + extra_skew, MIN_SKEW)
        offset = a - (c + R)  # relative to the clock with its pending correction, as chrony's slewed samples
        updates += 1
        F += ef
        if makestep is not None and updates <= makestep[1] and abs(offset) > makestep[0]:
            c += offset + R  # step: the pending correction is cancelled and the total stepped
            R, r, slew_end = 0.0, 0.0, now
            steps += 1
        else:
            R += offset
            corr_rate = corrtimeratio * 0.5 * off_sd * interval
            reslew()
        if adaptive:  # ntp_core.c get_poll_adj() and adjust_poll()
            err = abs(float(y[i]) - predicted) if predicted is not None else 0.0
            pd = float(disp[i]) + 0.5 * float(delay[i])
            if predicted is not None and pd > 0 and err > pd:
                adj = -math.log2(err / pd)
            else:
                adj = (n_act / polltarget - 1.0) / polltarget
                if n_act < polltarget:
                    adj *= 2.0
            score, poll = _chrony_poll(score + adj, poll, minpoll, hi)
            next_send = float(t[i]) + 2.0 ** poll
    meta: Dict[str, object] = {"estimator": "chrony", "frequency": F, "skew": our_skew, "steps": steps,
                               "measurements_used": used, "samples": n_act, "poll": poll,
                               "delay_rejected": rejected}
    extra = {}
    if adaptive:
        changes = np.flatnonzero(np.diff(polls)) + 1 if polls.size else np.array([], dtype=int)
        meta.update(minpoll=minpoll, maxpoll=hi,
                    polls=[(float(t[0]), int(polls[0]))] + [(float(t[j]), int(polls[j])) for j in changes])
        extra["poll"] = polls
    return TimeSeries(t, est, name=f"{s.name} (chrony)", source_format=s.source_format, meta=meta, extra=extra)


def _register() -> None:
    from .estimators import FunctionEstimator, register

    register(FunctionEstimator("ntpd", ntpd_discipline,
                               description="ntpd 4.2.8 clock discipline (clock filter, PLL/FLL, state machine)"))
    register(FunctionEstimator("ntpd-rfc", lambda s: ntpd_discipline(s, constants="rfc5905"),
                               description="the clock discipline with the RFC 5905 appendix constants"))
    register(FunctionEstimator("chrony", chrony_discipline,
                               description="chrony 4.x clock discipline (runs-test regression, skew-weighted "
                                           "frequency, correction-rate slewing)"))
    register(FunctionEstimator("ntpd-adaptive", lambda s: ntpd_discipline(s, maxpoll=10),
                               description="ntpd discipline adapting its poll up to 1024 s, as ntpd does"))
    register(FunctionEstimator("chrony-adaptive", lambda s: chrony_discipline(s, maxpoll=10),
                               description="chrony discipline adapting its poll up to 1024 s (polltarget 8)"))
    register(FunctionEstimator("lockclock", lockclock,
                               description="Levine's NIST frequency-lock loop (J. Res. NIST 2020)"))
    register(FunctionEstimator("levine-kalman", lambda s: lockclock(s, kalman=True),
                               description="LOCKCLOCK with Levine's scalar Kalman time estimate (PTTI 2011)"))
