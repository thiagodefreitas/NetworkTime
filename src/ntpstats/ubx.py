# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""u-blox UBX timing messages and PPS sawtooth correction.

GNSS timing receivers (u-blox ZED-F9T, LEA-M8T and others, also on the OCP
Time Card) report how good their time is in binary UBX messages. ntpstats
reads three of them from a raw receiver log (UBX frames, possibly mixed with
NMEA text), with the layouts of the u-blox interface description
(e.g. ZED-F9T, UBX-18053584):

``UBX-NAV-CLOCK`` (0x01 0x22)
    receiver clock bias ``clkB`` (ns) and drift ``clkD`` (ns/s), time
    accuracy ``tAcc`` (ns) and frequency accuracy ``fAcc`` (ps/s) of each
    navigation epoch. The series is the clock bias as reported, so its
    stability is that of the receiver's own oscillator as GNSS sees it.
``UBX-NAV-TIMEUTC`` (0x01 0x21)
    the UTC date and time of each navigation epoch, used to time-stamp the
    other messages, and its time accuracy estimate.
``UBX-TIM-TP`` (0x0D 0x01)
    the time of the *next* time pulse and its quantization error ``qErr``
    (ps): the receiver can only place the pulse on an edge of its internal
    clock, so the PPS is off by up to half a clock period, and the error
    drifts as a "sawtooth". ``qErr`` predicts it.

Times come from NAV-TIMEUTC when present (same ``iTOW``); otherwise from the
GPS week of TIM-TP, with GPS - UTC = ``leap_seconds`` (18 s since 2017).

:func:`apply_qerr` removes the sawtooth from a time-interval-counter
measurement of the receiver's PPS. u-blox does not state the sign with which
``qErr`` applies, so by default the sign that removes the sawtooth from the
data (the smaller sample-to-sample variance) is chosen and reported; it can
be fixed with ``sign=+1`` or ``-1``.
"""

from __future__ import annotations

import calendar
import struct
from typing import Dict, Iterator, List, Optional, Tuple, Union

import numpy as np

from .series import TimeSeries

SYNC = b"\xb5\x62"
NAV_CLOCK, NAV_TIMEUTC, TIM_TP = (0x01, 0x22), (0x01, 0x21), (0x0D, 0x01)
GPS_EPOCH = 315964800  # 1980-01-06T00:00:00Z as POSIX seconds
WEEK = 604800
LEAP_SECONDS = 18  # GPS - UTC since 2017-01-01


def _checksum(data: bytes) -> Tuple[int, int]:
    a = b = 0
    for x in data:
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return a, b


def frames(data: bytes, max_len: int = 4096) -> Iterator[Tuple[int, int, bytes]]:
    """Valid UBX frames ``(class, id, payload)``; anything else (NMEA, RTCM, noise) is skipped."""
    i = data.find(SYNC)
    while 0 <= i <= len(data) - 8:
        cls, mid, n = data[i + 2], data[i + 3], struct.unpack_from("<H", data, i + 4)[0]
        end = i + 6 + n
        if n <= max_len and end + 2 <= len(data) and _checksum(data[i + 2:end]) == (data[end], data[end + 1]):
            yield cls, mid, data[i + 6:end]
            i = data.find(SYNC, end + 2)
        else:
            i = data.find(SYNC, i + 1)


def is_ubx(head: bytes) -> bool:
    """True if ``head`` (the start of a file) contains a valid UBX frame."""
    return next(frames(head), None) is not None


def _utc(p: bytes) -> Optional[Tuple[int, float, float]]:
    """NAV-TIMEUTC -> (iTOW, POSIX time, tAcc s), or None when UTC is not valid."""
    itow, tacc, nano, year, month, day, hour, minute, sec, valid = struct.unpack_from("<IIiHBBBBBB", p, 0)
    if not valid & 0x04 or not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    t = calendar.timegm((year, month, day, hour, minute, min(sec, 59), 0, 0, 0)) + (sec - min(sec, 59)) + nano * 1e-9
    return itow, float(t), tacc * 1e-9


def parse_ubx(data: bytes, name: str = "ubx", leap_seconds: int = LEAP_SECONDS) -> List[TimeSeries]:
    """Series of a UBX log: the receiver clock (NAV-CLOCK) and the time-pulse quantization error (TIM-TP)."""
    clock: List[Tuple[int, int, int, int, int]] = []
    utc: Dict[int, Tuple[float, float]] = {}
    tp: List[Tuple[float, float, int, int, int]] = []
    weeks: List[int] = []
    for cls, mid, p in frames(data):
        if (cls, mid) == NAV_CLOCK and len(p) >= 20:
            clock.append(struct.unpack_from("<IiiII", p, 0))
        elif (cls, mid) == NAV_TIMEUTC and len(p) >= 20:
            u = _utc(p)
            if u is not None:
                utc[u[0]] = (u[1], u[2])
        elif (cls, mid) == TIM_TP and len(p) >= 16:
            tow_ms, sub, qerr, week, flags, ref = struct.unpack_from("<IIiHBB", p, 0)
            tow = tow_ms / 1e3 + sub * 2.0 ** -32 / 1e3
            utc_base = flags & 0x01
            t = GPS_EPOCH + week * WEEK + tow - (0 if utc_base else leap_seconds)
            tp.append((t, qerr * 1e-12, utc_base, (flags >> 1) & 0x01, ref & 0x0F))
            weeks.append(week)
    out: List[TimeSeries] = []
    if clock:
        week = weeks[0] if weeks else None
        rows = []
        for itow, clkb, clkd, tacc, facc in clock:
            if itow in utc:
                t, utc_acc = utc[itow]
            elif week is not None:
                t, utc_acc = GPS_EPOCH + week * WEEK + itow / 1e3 - leap_seconds, float("nan")
            else:
                continue
            rows.append((t, clkb * 1e-9, clkd * 1e-9, tacc * 1e-9, facc * 1e-12, utc_acc))
        if rows:
            a = np.array(rows)
            out.append(TimeSeries(a[:, 0], a[:, 1], name=f"{name} [receiver clock]", source_format="ubx",
                                  extra={"clock_drift": a[:, 2], "time_accuracy": a[:, 3],
                                         "freq_accuracy": a[:, 4], "utc_accuracy": a[:, 5]},
                                  meta={"peer": "receiver clock", "message": "UBX-NAV-CLOCK",
                                        "sign": "as reported (receiver clock bias clkB)",
                                        "timing": "NAV-TIMEUTC" if utc else f"GPS week, GPS-UTC {leap_seconds} s"}
                                  ).sorted())
    if tp:
        a = np.array(tp)
        out.append(TimeSeries(a[:, 0], a[:, 1], name=f"{name} [time pulse qErr]", source_format="ubx",
                              extra={"utc_time_base": a[:, 2], "utc_available": a[:, 3], "time_ref": a[:, 4]},
                              meta={"peer": "time pulse qErr", "message": "UBX-TIM-TP",
                                    "note": "quantization error of the time pulse at that time (s)"}).sorted())
    if not out:
        raise ValueError("no UBX-NAV-CLOCK or UBX-TIM-TP messages with usable times")
    for s in out:
        s.meta["file"] = name
    return out


def apply_qerr(pps: TimeSeries, qerr: TimeSeries, sign: Union[str, int] = "auto",
               max_dt: float = 0.5) -> TimeSeries:
    """Remove the quantization sawtooth from a PPS measurement with the receiver's ``qErr``.

    ``pps`` is a time-interval-counter series of the receiver's PPS against a
    reference (any sign convention); each sample is paired with the ``qErr``
    of the pulse nearest in time (within ``max_dt`` s). The result is
    ``pps + sign * qErr``; ``sign="auto"`` picks the sign that minimises the
    sample-to-sample variance (the sawtooth is the fastest component), and
    the choice and the improvement are reported in ``meta``.
    """
    p, q = pps.sorted(), qerr.sorted()
    if len(q) == 0 or len(p) == 0:
        raise ValueError("no PPS or qErr samples")
    j = np.clip(np.searchsorted(q.t, p.t), 1, len(q) - 1) if len(q) > 1 else np.zeros(len(p), dtype=int)
    if len(q) > 1:
        j = np.where(np.abs(q.t[j - 1] - p.t) <= np.abs(q.t[j] - p.t), j - 1, j)
    ok = np.abs(q.t[j] - p.t) <= max_dt
    if ok.sum() < 3:
        raise ValueError("fewer than 3 PPS samples have a qErr within "
                         f"{max_dt} s; check that both files cover the same period on the same timescale")
    t, x, qe = p.t[ok], p.offset[ok], q.offset[j[ok]]

    def roughness(y):
        return float(np.var(np.diff(y))) if y.size > 2 else float("nan")

    before = roughness(x)
    trials = {s: roughness(x + s * qe) for s in (1, -1)}
    if sign == "auto":
        s = min(trials, key=lambda k: trials[k])
    elif sign in (1, -1, "+1", "-1", "+", "-"):
        s = -1 if str(sign).startswith("-") else 1
    else:
        raise ValueError("sign must be 'auto', +1 or -1")
    y = x + s * qe
    meta = dict(p.meta, qerr_sign=s, matched=int(ok.sum()), unmatched=int((~ok).sum()),
                diff_rms_before=float(np.sqrt(before)), diff_rms_after=float(np.sqrt(trials[s])),
                sign_choice="data (smaller sample-to-sample variance)" if sign == "auto" else "given")
    extra = {k: v[ok] for k, v in p.extra.items() if len(v) == len(p)}
    extra.update(qerr=qe, uncorrected=x)
    return TimeSeries(t, y, name=f"{p.name} (qErr corrected)", source_format=p.source_format, extra=extra,
                      meta=meta)
