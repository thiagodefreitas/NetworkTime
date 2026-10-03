# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""GNSS/PPS timing on a Linux host and in the lab: gpsd and the TAPR TICC.

**gpsd** (``gpspipe -w`` output, or a live connection; gpsd_json(5)). Two
messages carry timing:

``PPS``
    each PPS edge: ``real_sec``/``real_nsec`` is the GNSS time of the edge,
    ``clock_sec``/``clock_nsec`` the system clock's time stamp of it. The
    offset ``real - clock`` is the GNSS reference minus the local clock, the
    ntpstats convention. ``precision`` (NTP style, log2 s) and, from
    receivers that report it, ``qErr`` (ps) are kept.
``TOFF``
    the same for the time in the serial data stream (start of the reporting
    cycle), with the much larger serial and processing latency.

One series per device and message. ``qErr`` lets ``ntpstats sawtooth`` correct
a gpsd PPS series without a separate receiver log.

**TAPR TICC** (timestamping counter; output as in its firmware ``print.cpp``
and manual): lines ``1.897999794440 chA`` in Timestamp, Period and
3-Corner-Hat modes, bare numbers in Time Interval mode, comment lines starting
with ``#``. Timestamps are seconds since the counter started; with the
``WRAP`` setting only the last digits of the seconds are printed, which is
undone here. For each channel the series is the phase against an ideal grid
of the nominal period (the time interval error of the input); with two
channels the difference ``chA - chB`` of events paired within half a period
is added. Times are counter seconds, not POSIX time, unless ``epoch`` is given.
"""

from __future__ import annotations

import json
import re
import socket
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .series import TimeSeries

GPSD_PORT = 2947


# ----------------------------------------------------------------------- gpsd
def detect_gpsd(lines: Sequence[str]) -> float:
    js = [ln for ln in lines[:200] if ln.lstrip().startswith('{"class":')]
    if not js:
        return 0.0
    timing = any('"class":"PPS"' in ln.replace(" ", "") or '"class":"TOFF"' in ln.replace(" ", "") for ln in js)
    return 0.95 if timing else 0.0


def _gpsd_row(o: dict) -> Optional[Tuple[float, float, float, float]]:
    try:
        clock = int(o["clock_sec"]) + int(o["clock_nsec"]) * 1e-9
        # ntpstats convention: reference (GNSS) - local (system clock), from the exact integer parts
        off = (int(o["real_sec"]) - int(o["clock_sec"])) + (int(o["real_nsec"]) - int(o["clock_nsec"])) * 1e-9
    except (KeyError, TypeError, ValueError):
        return None
    qerr = float(o["qErr"]) * 1e-12 if o.get("qErr") is not None else float("nan")
    prec = float(o.get("precision", float("nan")))
    return clock, off, prec, qerr


def parse_gpsd(lines: Sequence[str], name: str = "gpsd") -> List[TimeSeries]:
    """PPS and TOFF series per device from gpsd JSON lines (``gpspipe -w``)."""
    groups: "OrderedDict[Tuple[str, str], list]" = OrderedDict()
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        cls = o.get("class")
        if cls not in ("PPS", "TOFF"):
            continue
        row = _gpsd_row(o)
        if row is not None:
            groups.setdefault((str(cls), str(o.get("device", "?"))), []).append(row)
    if not groups:
        raise ValueError("no gpsd PPS or TOFF messages (record with: gpspipe -w, PPS needs a PPS source)")
    out = []
    for (cls, dev), rows in groups.items():
        a = np.array(rows, dtype=float)
        extra = {"precision": a[:, 2]}
        if np.isfinite(a[:, 3]).any():
            extra["qerr"] = a[:, 3]
        out.append(TimeSeries(a[:, 0], a[:, 1], name=f"{name} [{cls} {dev}]", source_format="gpsd", extra=extra,
                              meta={"peer": f"{cls} {dev}", "device": dev, "message": cls,
                                    "note": "GNSS time minus the system clock's time stamp"
                                            + (" of the PPS edge" if cls == "PPS" else " of the serial message")}
                              ).sorted())
    return out


def sample_gpsd(cmd: Sequence[str] = ("localhost:2947",), timeout: float = 3.0) -> Dict[str, object]:
    """One PPS (or, without PPS, TOFF) offset from a running gpsd (``host:port``)."""
    from .sources import SourceError

    host, _, port = str(cmd[0] if cmd else "localhost").partition(":")
    try:
        with socket.create_connection((host or "localhost", int(port or GPSD_PORT)), timeout=timeout) as sock:
            sock.sendall(b'?WATCH={"enable":true,"json":true,"pps":true};\n')
            buf, deadline, toff = b"", time.monotonic() + timeout, None
            while time.monotonic() < deadline:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    try:
                        o = json.loads(raw)
                    except ValueError:
                        continue
                    if o.get("class") not in ("PPS", "TOFF"):
                        continue
                    row = _gpsd_row(o)
                    if row is None:
                        continue
                    d = {"time": time.time(), "offset": row[1], "precision": row[2], "qerr": row[3],
                         "source": o["class"], "device": o.get("device", "?")}
                    if o["class"] == "PPS":
                        return d
                    toff = d
            if toff is not None:
                return toff
    except OSError as exc:
        raise SourceError(f"gpsd at {host or 'localhost'}:{port or GPSD_PORT}: {exc}") from exc
    raise SourceError("gpsd sent no PPS or TOFF message (is a GNSS receiver with PPS attached?)")


# ----------------------------------------------------------------------- TAPR TICC
_TICC = re.compile(r"^\s*(-?)(\d+)\.(\d+)(?:\s+ch(\w))?\s*$")


def detect_ticc(lines: Sequence[str]) -> float:
    data = [ln for ln in lines[:200] if ln.strip() and not ln.lstrip().startswith("#")]
    if not data:
        return 0.0
    m = [_TICC.match(ln) for ln in data]
    if all(m) and any(x.group(4) for x in m if x):
        return 0.95
    return 0.0


def _unwrap(sec: np.ndarray) -> np.ndarray:
    """Undo the TICC ``WRAP`` setting: the printed seconds restart at 10**digits."""
    if sec.size < 2 or not (np.diff(sec) < 0).any():
        return sec
    span = 10 ** len(str(int(np.max(np.abs(sec)))))
    back = np.diff(sec) < -span / 2
    return sec + span * np.concatenate(([0], np.cumsum(back)))


def _phase(sec: np.ndarray, frac: np.ndarray, period: Optional[float]) -> Tuple[np.ndarray, float]:
    """Phase against an ideal grid, from integer seconds and fractions kept apart (picoseconds survive)."""
    rel = (sec - sec[0]) + (frac - frac[0])
    tau = float(np.median(np.diff(rel))) if period is None and rel.size > 1 else float(period or 1.0)
    if period is None and abs(tau - round(tau)) < 1e-3 and round(tau) > 0:
        tau = float(round(tau))  # a PPS or a whole-second rate: keep the frequency offset in the phase
    n = np.round(rel / tau)
    return ((sec - sec[0]) - n * tau) + (frac - frac[0]), tau


def parse_ticc(lines: Sequence[str], name: str = "ticc", period: Optional[float] = None,
               epoch: float = 0.0) -> List[TimeSeries]:
    """Series from TAPR TICC output: phase per channel, ``chA - chB``, or the intervals of Time Interval mode."""
    chans: "OrderedDict[str, List[Tuple[int, float]]]" = OrderedDict()
    for ln in lines:
        if ln.lstrip().startswith("#"):
            continue
        m = _TICC.match(ln)
        if m:
            sign = -1 if m.group(1) else 1
            chans.setdefault(m.group(4) or "", []).append((sign * int(m.group(2)), sign * float("0." + m.group(3))))
    if not chans:
        raise ValueError("no TICC readings (lines like '1.897999794440 chA')")
    out: List[TimeSeries] = []
    parts: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for ch, vals in chans.items():
        sec = np.array([v[0] for v in vals], dtype=float)
        frac = np.array([v[1] for v in vals], dtype=float)
        if not ch:  # Time Interval mode: one interval per line, at the nominal period
            tau = period or 1.0
            out.append(TimeSeries(epoch + tau * np.arange(sec.size), sec + frac, name=f"{name} [interval]",
                                  source_format="ticc",
                                  meta={"peer": "interval", "mode": "time interval", "period_s": tau,
                                        "note": "interval chA -> chB per event; times are event index x period"}))
            continue
        sec = _unwrap(sec)
        parts[ch] = (sec, frac)
        x, tau = _phase(sec, frac, period)
        out.append(TimeSeries(epoch + sec + frac, x, name=f"{name} [ch{ch}]", source_format="ticc",
                              meta={"peer": f"ch{ch}", "mode": "timestamp", "period_s": tau,
                                    "note": "phase of the input against an ideal grid of its period (TIE), "
                                            "measured by the TICC's reference; times are counter seconds"}))
    if len(parts) >= 2:
        (a_name, (sa, fa)), (b_name, (sb, fb)) = list(parts.items())[:2]
        ta, tb = sa + fa, sb + fb
        _, tau = _phase(sa, fa, period)
        j = np.clip(np.searchsorted(tb, ta), 1, tb.size - 1) if tb.size > 1 else np.zeros(ta.size, dtype=int)
        if tb.size > 1:
            j = np.where(np.abs(tb[j - 1] - ta) <= np.abs(tb[j] - ta), j - 1, j)
        ok = np.abs(tb[j] - ta) <= tau / 2
        if ok.sum() >= 2:
            diff = (sa[ok] - sb[j[ok]]) + (fa[ok] - fb[j[ok]])
            out.append(TimeSeries(epoch + ta[ok], diff, name=f"{name} [ch{a_name} - ch{b_name}]",
                                  source_format="ticc",
                                  meta={"peer": f"ch{a_name} - ch{b_name}", "mode": "timestamp difference",
                                        "note": f"ch{a_name} minus ch{b_name} for events within half a period"}))
    return out


def _register() -> None:
    from .plugins import ParserPlugin, register_parser

    register_parser(ParserPlugin("gpsd", parse_gpsd, detect_gpsd, "gpsd JSON (gpspipe -w): PPS and TOFF offsets"))
    register_parser(ParserPlugin("ticc", parse_ticc, detect_ticc, "TAPR TICC timestamping counter output"))


_register()
