# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Readers for the log formats produced by today's NTP implementations.

Supported formats (``fmt`` names):

``loopstats``
    ntpd (4.2.8) and NTPsec clock-discipline log:
    ``MJD sec offset[s] freq[ppm] jitter[s] wander[ppm] timeconst``
``peerstats``
    ntpd / NTPsec per-peer log:
    ``MJD sec addr status offset[s] delay[s] dispersion[s] jitter[s]``
``rawstats``
    ntpd / NTPsec raw packet timestamps:
    ``MJD sec src dst T1 T2 T3 T4 ...`` (NTP-era seconds). Offset and delay
    are computed here from the four on-wire timestamps.
``chrony-tracking`` / ``chrony-measurements`` / ``chrony-statistics`` / ``chrony-refclocks``
    chrony's ``tracking.log``, ``measurements.log``, ``statistics.log`` and
    ``refclocks.log`` (``log tracking measurements statistics refclocks``).
    Signs follow chrony.conf(5): measurements (theta) and refclocks (cooked
    offset) are already *reference - local*; tracking and statistics are
    *local - reference* and are negated, so every series uses the ntpd
    convention (see :mod:`ntpstats.series`).
``linuxptp``
    ``ptp4l``, ``phc2sys`` and ``ts2phc`` output (stdout or syslog/journal),
    per-sample lines (``master offset ... s2 freq ... path delay ...``) and
    summary lines (``rms ... max ... freq ... delay ...``). One series per
    program/clock. Offsets are ns *local - reference* in linuxptp and are
    converted to seconds, reference - local.
``csv``
    Generic delimited text: ``time,offset[,more columns]`` with an optional
    header. ``ntpstats monitor`` writes this format. A single column of
    offsets is accepted too (then ``tau0`` must be supplied).
``gsoc2012``
    The ``estimators.log`` files written by the 2012 prototype.
"""

from __future__ import annotations

import calendar
import io
import os
import re
from collections import OrderedDict
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

from .pcap import is_capture, parse_capture
from .series import TimeSeries, mjd_to_unix

FORMATS = (
    "loopstats",
    "peerstats",
    "rawstats",
    "chrony-tracking",
    "chrony-measurements",
    "chrony-statistics",
    "chrony-refclocks",
    "linuxptp",
    "pcap",
    "csv",
    "stable32-phase",
    "stable32-freq",
    "w32tm",
    "prometheus",
    "bounds",
    "cggtts",
    "rinex-clock",
    "circular-t",
    "ripe-atlas",
    "ntppool",
    "interop",
    "parquet",
    "gsoc2012",
)

#: Seconds between the NTP era-0 epoch (1900) and the POSIX epoch (1970).
NTP_UNIX_DELTA = 2208988800

_CHRONY_TS = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}")
_LEGACY = re.compile(r"Logged:\s*\[off,\s*([-+0-9.eE]+),\s*time,\s*([-+0-9.eE]+)\]")
_LEAP_CODES = {"N", "+", "-", "?"}
# linuxptp: "ptp4l[1234.567]: " (stdout) or "... ptp4l[99]: [1234.567] " (syslog)
_PTP_PREFIX = re.compile(r"(ptp4l|phc2sys|ts2phc)\[(\d+)(?:\.(\d+))?\]:\s*(?:\[(\d+)\.(\d+)\]\s*)?(?:\[([^\]]*)\]\s*)?")
_PTP_SAMPLE = re.compile(
    r"(?:(?P<dev>(?!master\b)\S+)\s+(?:(?P<src>(?!offset\b)\S+)\s+)?)?(?P<kind>master offset|offset)\s+(?P<off>-?\d+)"
    r"(?:\s+s(?P<state>\d))?(?:\s+freq\s+(?P<freq>[+-]?\d+))?"
    r"(?:\s+(?:path delay|delay)\s+(?P<delay>-?\d+))?"
)
_PTP_SUMMARY = re.compile(
    r"(?:(?P<dev>\S+)\s+)?rms\s+(?P<rms>\d+)\s+max\s+(?P<max>\d+)\s+freq\s+(?P<freq>[+-]?\d+)\s+\+/-\s+(?P<fsd>\d+)"
    r"(?:\s+delay\s+(?P<delay>-?\d+)\s+\+/-\s+(?P<dsd>\d+))?"
)
_ISO_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:?\d{2})?")


class ParseError(ValueError):
    pass


# ----------------------------------------------------------------- helpers
def _read_lines(source) -> List[str]:
    if hasattr(source, "read"):
        text = source.read()
    else:
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text.splitlines()


def _name_of(source) -> str:
    if isinstance(source, (str, os.PathLike)):
        return os.path.basename(os.path.normpath(os.fspath(source)))
    return getattr(source, "name", "") or "data"


def _is_float(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _is_mjd_line(fields: Sequence[str]) -> bool:
    if len(fields) < 3:
        return False
    try:
        mjd = int(fields[0])
        sec = float(fields[1])
    except ValueError:
        return False
    return 40000 <= mjd <= 99999 and 0 <= sec < 86401


def _chrony_time(date: str, clock: str) -> float:
    y, mo, d = (int(v) for v in date.split("-"))
    hh, mm, ss = clock.split(":")
    return calendar.timegm((y, mo, d, int(hh), int(mm), 0, 0, 0, 0)) + float(ss)


def _data_lines(lines: Iterable[str]) -> List[str]:
    out = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("="):
            continue
        out.append(s)
    return out


# --------------------------------------------------------------- detection
_W32_LINE = re.compile(r"^\s*(\d{1,2}):(\d{2}):(\d{2}),\s*(?:d:([+-]?[\d.]+)s\s+o:)?([+-]?[\d.]+)s\s*$")
_W32_RDTSC = re.compile(r"rdtscstart\s*,\s*rdtscend\s*,\s*filetime", re.I)
_BOUNDS_TEXT = re.compile(r"within\s+([\d.]+)\s+and\s+([\d.]+)\s+seconds", re.I)


def detect_format(lines: Sequence[str]) -> str:
    """Guess the format of a log from its first lines."""
    head = "\n".join(lines[:50])
    if '"resultType"' in head and '"matrix"' in head:
        return "prometheus"
    from . import plugins, research  # noqa: F401  (research registers its formats as parser plugins)

    found = plugins.detect_plugin(lines, 0.9)  # installed plugins that are sure win
    if found:
        return found
    for name, p in plugins.parsers().items():
        if p.source == "built-in" and p.detect is not None and p.detect(lines) >= 0.9:
            return name
    if _W32_RDTSC.search(head) or ("Tracking " in head and any(_W32_LINE.match(ln) for ln in lines[:50])):
        return "w32tm"
    if _BOUNDS_TEXT.search(head):
        return "bounds"
    first = next((ln for ln in lines[:5] if ln.strip()), "")
    cols = [c.strip().lower() for c in re.split(r"[,;\s]+", first.lstrip("#").strip())]
    if "earliest" in cols and "latest" in cols:
        return "bounds"
    header = " ".join(ln for ln in lines[:20] if ln.strip() and not ln.strip()[0].isdigit())
    for ln in lines[:200]:
        if _LEGACY.search(ln):
            return "gsoc2012"
        if _PTP_PREFIX.search(ln) and (_PTP_SAMPLE.search(ln) or _PTP_SUMMARY.search(ln)):
            return "linuxptp"
    sample = [ln for ln in _data_lines(lines[:400]) if ln[0].isdigit() or ln[0] in "+-."][:50]
    fallback = plugins.detect_plugin(lines, 0.5)
    if not sample:
        if fallback:
            return fallback
        raise ParseError("no data lines found")
    fields = sample[0].split()
    if _CHRONY_TS.match(sample[0]):
        if "Raw offset" in header or "Cooked offset" in header:
            return "chrony-refclocks"
        if len(fields) in (8, 9) and fields[4] in _LEAP_CODES and fields[5] in ("0", "1", "-") and not _is_float(fields[2]):
            return "chrony-refclocks"
        if "Freq ppm" in header or "Skew ppm" in header:
            return "chrony-tracking"
        if "Score" in header or "Peer del" in header or "ABCD" in header:
            return "chrony-measurements"
        if "Std dev" in header or "Est offset" in header:
            return "chrony-statistics"
        # No header: use column shape.
        if len(fields) > 7 and fields[3] in _LEAP_CODES:
            return "chrony-measurements"
        if len(fields) > 7 and fields[7] in _LEAP_CODES:
            return "chrony-tracking"
        if len(fields) >= 13 and _is_float(fields[3]):
            return "chrony-statistics"
        raise ParseError("unrecognised chrony log layout")
    if _is_mjd_line(fields):
        if len(fields) >= 7 and all(_is_float(f) for f in fields[:7]):
            return "loopstats"
        if len(fields) >= 8 and all(_is_float(f) for f in fields[4:8]):
            if not _is_float(fields[3]) and re.fullmatch(r"[0-9a-fA-F]{1,4}", fields[3]):
                return "peerstats"
            if _is_float(fields[3]) and "." not in fields[3] and fields[3].isdigit():
                return "peerstats"  # status word written as all-digit hex
            return "rawstats"
        raise ParseError("MJD-stamped log of unknown type (clockstats/sysstats are not offset logs)")
    return fallback or "csv"


# ----------------------------------------------------------------- parsers
def _finish(t, off, name, fmt, extra=None, meta=None) -> TimeSeries:
    if len(t) == 0:
        raise ParseError(f"no usable samples for format {fmt}")
    s = TimeSeries(
        t=np.asarray(t, dtype=float),
        offset=np.asarray(off, dtype=float),
        name=name,
        source_format=fmt,
        extra={k: np.array(v) for k, v in (extra or {}).items()},
        meta=meta or {},
    )
    return s.sorted()


def _numeric(rows, cols):
    """Float matrix of ``cols`` from token rows; rows with a bad value are
    dropped (vectorised fast path, per-row fallback). Returns (array, keep)."""
    cols = list(cols)
    try:
        return np.array([[r[c] for c in cols] for r in rows], dtype=float).reshape(-1, len(cols)), None
    except ValueError:
        keep, out = [], []
        for r in rows:
            try:
                out.append([float(r[c]) for c in cols])
                keep.append(True)
            except ValueError:
                keep.append(False)
        return np.array(out, dtype=float).reshape(-1, len(cols)), np.array(keep, dtype=bool)


def _fast(lines, usecols, strcols=None, chrony=False):
    """numpy C tokenizer fast path; None if any data line is irregular
    (the caller then falls back to the tolerant per-line parser)."""
    import warnings

    if chrony:
        dl = [ln for ln in lines if ln[:4].isdigit() and ln[4:5] == "-"]
    else:
        dl = [ln for ln in lines if ln[:1].isdigit()]
    if not dl:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = np.loadtxt(dl, usecols=list(usecols), ndmin=2, comments="#")
            sc = np.loadtxt(dl, usecols=list(strcols), dtype=str, ndmin=2, comments="#") if strcols else None
    except (ValueError, IndexError):
        return None
    skipped = 0
    if not chrony:  # non-numeric lines that are not comments were dropped: report them
        skipped = sum(1 for ln in lines if (st := ln.strip()) and not st[0].isdigit() and st[0] not in "#=")
    return a, sc, skipped


def _tokens(lines, min_fields):
    rows = [ln.split() for ln in _data_lines(lines)]
    good = [r for r in rows if len(r) >= min_fields]
    return good, len(rows) - len(good)


def parse_loopstats(lines, name="loopstats") -> List[TimeSeries]:
    fast = _fast(lines, range(7))
    if fast is not None:
        a, _, skipped = fast
    else:
        rows, skipped = _tokens(lines, 7)
        a, keep = _numeric(rows, range(7))
        if keep is not None:
            skipped += int((~keep).sum())
    if not a.size:
        raise ParseError("no usable loopstats lines")
    t = mjd_to_unix(a[:, 0], a[:, 1])
    return [
        _finish(
            t, a[:, 2], name, "loopstats",
            extra={"frequency_ppm": a[:, 3], "jitter": a[:, 4], "wander_ppm": a[:, 5], "time_constant": a[:, 6]},
            meta={"skipped_lines": skipped},
        )
    ]


def _groups(keys):
    """Indices per distinct key, in order of first appearance."""
    uniq, first, inv = np.unique(np.asarray(keys), return_index=True, return_inverse=True)
    order = np.argsort(first)
    return [(str(uniq[i]), np.flatnonzero(inv == i)) for i in order]


def _peer_status_select(status: str) -> int:
    try:
        return (int(status, 16) >> 8) & 0x7
    except ValueError:
        return -1


def parse_peerstats(lines, name="peerstats") -> List[TimeSeries]:
    fast = _fast(lines, (0, 1, 4, 5, 6, 7), strcols=(2, 3))
    if fast is not None:
        a, sc, skipped = fast
        addrs, status = sc[:, 0], sc[:, 1]
    else:
        rows, skipped = _tokens(lines, 8)
        a, keep = _numeric(rows, (0, 1, 4, 5, 6, 7))
        if keep is not None:
            skipped += int((~keep).sum())
            rows = [r for r, k in zip(rows, keep) if k]
        addrs, status = [r[2] for r in rows], [r[3] for r in rows]
    if not a.size:
        raise ParseError("no usable peerstats lines")
    cache: Dict[str, int] = {}
    sel = np.array([cache[v] if v in cache else cache.setdefault(v, _peer_status_select(v)) for v in status])
    t = mjd_to_unix(a[:, 0], a[:, 1])
    out = []
    for addr, idx in _groups(addrs):
        out.append(
            _finish(
                t[idx], a[idx, 2], f"{name} [{addr}]", "peerstats",
                extra={"delay": a[idx, 3], "dispersion": a[idx, 4], "jitter": a[idx, 5]},
                # select code 6 = sys.peer, 7 = pps.peer (RFC 5905 / ntpd decode.html)
                meta={"peer": addr, "sys_peer_fraction": float(np.mean(np.isin(sel[idx], (6, 7)))),
                      "skipped_lines": skipped},
            )
        )
    return out


def _ntp_ts_to_unix(v: float, ref_unix: float) -> float:
    """NTP 32.32 seconds (as decimal) to POSIX, choosing the era nearest ``ref_unix``."""
    era_len = 2.0 ** 32
    base = v - NTP_UNIX_DELTA
    era = np.round((ref_unix - base) / era_len)
    return base + era * era_len


def parse_rawstats(lines, name="rawstats") -> List[TimeSeries]:
    peers: "OrderedDict[str, list]" = OrderedDict()
    skipped = 0
    for ln in _data_lines(lines):
        f = ln.split()
        try:
            tu = float(mjd_to_unix(int(f[0]), float(f[1])))
            t1, t2, t3, t4 = (_ntp_ts_to_unix(float(x), tu) for x in f[4:8])
        except (ValueError, IndexError):
            skipped += 1
            continue
        if min(t1, t2, t3, t4) <= 0:
            skipped += 1
            continue
        offset = ((t2 - t1) + (t3 - t4)) / 2.0
        delay = (t4 - t1) - (t3 - t2)
        peers.setdefault(f[2], []).append((tu, offset, delay))
    out = []
    for addr, rows in peers.items():
        a = np.array(rows)
        out.append(
            _finish(
                list(a[:, 0]), list(a[:, 1]), f"{name} [{addr}]", "rawstats",
                extra={"delay": a[:, 2]}, meta={"peer": addr, "skipped_lines": skipped},
            )
        )
    return out


def _chrony_times(rows) -> np.ndarray:
    """POSIX seconds from chrony 'YYYY-MM-DD HH:MM:SS[.ffffff]' columns (vectorised)."""
    try:
        dt = np.array([r[0] + "T" + r[1] for r in rows], dtype="datetime64[us]")
        return dt.astype(np.int64) / 1e6
    except ValueError:
        return np.array([_chrony_time(r[0], r[1]) for r in rows])


def _parse_chrony(lines, name, fmt, off_idx, extra_cols, min_fields, group=True, sign=-1.0) -> List[TimeSeries]:
    cols = [off_idx] + [i for _, i in extra_cols]
    fast = _fast(lines, cols, strcols=(0, 1, 2), chrony=True)
    if fast is not None:
        a, good, skipped = fast
    else:
        rows = [ln.split() for ln in _data_lines(lines) if _CHRONY_TS.match(ln)]
        good = [r for r in rows if len(r) >= min_fields]
        skipped = len(rows) - len(good)
        a, keep = _numeric(good, cols)
        if keep is not None:
            skipped += int((~keep).sum())
            good = [r for r, k in zip(good, keep) if k]
    if len(good) == 0:
        raise ParseError(f"no usable samples for format {fmt}")
    t = _chrony_times(good)
    out = []
    groups = _groups([r[2] for r in good]) if group else [("all", np.arange(len(good)))]
    for key, idx in groups:
        label = f"{name} [{key}]" if group else name
        meta = {"skipped_lines": skipped,
                "sign": "negated (chrony: local - reference)" if sign < 0 else "as logged (reference - local)"}
        if group:
            meta["peer"] = key
        out.append(
            _finish(
                t[idx], sign * a[idx, 0], label, fmt,
                extra={k: a[idx, 1 + j] for j, (k, _) in enumerate(extra_cols)}, meta=meta,
            )
        )
    return out


def parse_chrony_tracking(lines, name="tracking.log") -> List[TimeSeries]:
    # Date Time IP St Freq Skew Offset L Co Offset_sd Rem.corr RootDelay RootDisp MaxErr
    extra = [("frequency_ppm", 4), ("skew_ppm", 5)]
    first = next((ln.split() for ln in _data_lines(lines) if _CHRONY_TS.match(ln)), [])
    if len(first) >= 14:
        extra += [("offset_sd", 9), ("root_delay", 11), ("root_dispersion", 12), ("max_error", 13)]
    elif len(first) >= 10:
        extra += [("offset_sd", 9)]
    return _parse_chrony(lines, name, "chrony-tracking", 6, extra, 7, group=False)


def parse_chrony_measurements(lines, name="measurements.log") -> List[TimeSeries]:
    # Date Time IP L St 123 567 ABCD LP RP Score Offset PeerDel PeerDisp RootDel RootDisp Refid ...
    base = 11  # "Offset" column; stable since chrony 1.x
    extra = [("delay", base + 1), ("dispersion", base + 2), ("root_delay", base + 3), ("root_dispersion", base + 4)]
    # chrony.conf(5): "Positive indicates that the local clock is slow of the
    # remote source" - already the ntpd convention, so no sign change.
    return _parse_chrony(lines, name, "chrony-measurements", base, extra, base + 5, sign=1.0)


def parse_chrony_statistics(lines, name="statistics.log") -> List[TimeSeries]:
    # Date Time IP Std_dev Est_offset Offset_sd Diff_freq Est_skew Stress Ns Bs Nr [Asym]
    extra = [("std_dev", 3), ("offset_sd", 5), ("diff_freq", 6), ("est_skew", 7)]
    # "positive means the local clock is estimated to be fast" -> negate
    return _parse_chrony(lines, name, "chrony-statistics", 4, extra, 8)


def parse_chrony_refclocks(lines, name="refclocks.log") -> List[TimeSeries]:
    """``refclocks.log``: Date Time Refid DP L P RawOffset CookedOffset Disp.

    Filtered samples (``-`` in the raw column) are skipped; the cooked
    offset ("positive indicates that the local clock is slow") is used as is.
    """
    groups: "OrderedDict[str, list]" = OrderedDict()
    skipped = 0
    for ln in _data_lines(lines):
        if not _CHRONY_TS.match(ln):
            continue
        f = ln.split()
        if len(f) < 9 or f[6] == "-":
            skipped += 1
            continue
        try:
            groups.setdefault(f[2], []).append(
                (_chrony_time(f[0], f[1]), float(f[7]), float(f[6]), float(f[8]), 1.0 if f[5] == "1" else 0.0))
        except ValueError:
            skipped += 1
    out = []
    for key, rows in groups.items():
        a = np.array(rows)
        out.append(_finish(list(a[:, 0]), list(a[:, 1]), f"{name} [{key}]", "chrony-refclocks",
                           extra={"raw_error": a[:, 2], "dispersion": a[:, 3], "pps": a[:, 4]},
                           meta={"peer": key, "skipped_lines": skipped, "sign": "as logged (reference - local)"}))
    if not out:
        raise ParseError("no raw refclock samples found")
    return out


def _iso_to_unix(date: str, clock: str, tz) -> float:
    t = _chrony_time(date, clock)
    if tz and tz != "Z":
        tz = tz.replace(":", "")
        off = (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60) * (1 if tz[0] == "+" else -1)
        t -= off
    return t


def parse_linuxptp(lines, name="linuxptp") -> List[TimeSeries]:
    """linuxptp ``ptp4l``/``phc2sys``/``ts2phc`` messages.

    Time base: linuxptp stamps messages with CLOCK_MONOTONIC. If lines also
    carry an ISO-8601 wall-clock prefix (``journalctl -o short-iso-precise``)
    the monotonic stamps are mapped to UTC; otherwise times are monotonic
    seconds (``meta['time_base']``).
    """
    groups: "OrderedDict[str, dict]" = OrderedDict()
    mono_utc = []
    for ln in lines:
        m = _PTP_PREFIX.search(ln)
        if not m:
            continue
        prog = m.group(1)
        if m.group(4) is not None:  # syslog form: prog[pid]: [mono.ms]
            mono = float(f"{m.group(4)}.{m.group(5)}")
        elif m.group(3) is not None:
            mono = float(f"{m.group(2)}.{m.group(3)}")
        else:
            continue
        tag = (m.group(6) or "").strip()
        rest = ln[m.end():]
        iso = _ISO_TS.match(ln)
        if iso:
            try:
                mono_utc.append(_iso_to_unix(iso.group(1), iso.group(2), iso.group(3)) - mono)
            except ValueError:
                pass
        sm = _PTP_SUMMARY.match(rest)
        if sm:
            key = " ".join(x for x in (prog, tag, sm.group("dev")) if x) + " (summary)"
            g = groups.setdefault(key, {"rows": [], "summary": True})
            g["rows"].append((mono, float(sm.group("rms")) * 1e-9, float(sm.group("max")) * 1e-9,
                              float(sm.group("freq")) * 1e-3,
                              float(sm.group("delay")) * 1e-9 if sm.group("delay") else np.nan))
            continue
        pm = _PTP_SAMPLE.match(rest)
        if pm:
            dev = pm.group("dev") if pm.group("kind") == "offset" else None
            src = pm.group("src") if dev else None
            key = " ".join(x for x in (prog, tag, dev, src) if x)
            g = groups.setdefault(key, {"rows": [], "summary": False})
            g["rows"].append((mono, -float(pm.group("off")) * 1e-9,
                              float(pm.group("state")) if pm.group("state") else np.nan,
                              float(pm.group("freq")) * 1e-3 if pm.group("freq") else np.nan,
                              float(pm.group("delay")) * 1e-9 if pm.group("delay") else np.nan))
    if not groups:
        raise ParseError("no linuxptp offset lines found")
    shift = float(np.median(mono_utc)) if mono_utc else 0.0
    base = "utc" if mono_utc else "monotonic"
    out = []
    for key, g in groups.items():
        a = np.array(g["rows"], dtype=float)
        t = a[:, 0] + shift
        if g["summary"]:
            extra = {"max_abs": a[:, 2], "frequency_ppm": a[:, 3]}
            if np.isfinite(a[:, 4]).any():
                extra["delay"] = a[:, 4]
            out.append(_finish(list(t), list(a[:, 1]), f"{name} [{key}]", "linuxptp", extra=extra,
                               meta={"peer": key, "time_base": base, "note": "offset column is the RMS per summary interval"}))
        else:
            extra = {"servo_state": a[:, 2], "frequency_ppm": a[:, 3]}
            if np.isfinite(a[:, 4]).any():
                extra["delay"] = a[:, 4]
            out.append(_finish(list(t), list(a[:, 1]), f"{name} [{key}]", "linuxptp", extra=extra,
                               meta={"peer": key, "time_base": base,
                                     "sign": "negated (linuxptp: local - reference)"}))
    return out


def parse_gsoc2012(lines, name="estimators.log") -> List[TimeSeries]:
    t, off = [], []
    for ln in lines:
        m = _LEGACY.search(ln)
        if m:
            off.append(float(m.group(1)))
            t.append(float(m.group(2)))
    return [_finish(t, off, name, "gsoc2012")]


def parse_csv(lines, name="data", tau0: Optional[float] = None) -> List[TimeSeries]:
    rows = _data_lines(lines)
    if not rows:
        raise ParseError("empty file")
    delim = "," if "," in rows[0] else (";" if ";" in rows[0] else None)
    header = None
    first = [c.strip() for c in (rows[0].split(delim) if delim else rows[0].split())]
    if not all(_is_float(c) for c in first):
        header = [c.lower() for c in first]
        rows = rows[1:]
    # Also accept a commented header line ("# unix_time,offset,...").
    if header is None:
        for ln in lines[:5]:
            s = ln.strip()
            if s.startswith("#"):
                cand = [c.strip().lower() for c in (s[1:].split(delim) if delim else s[1:].split())]
                if len(cand) == len(first) and not any(_is_float(c) for c in cand):
                    header = cand
    data, skipped = [], 0
    width = len(first)
    for ln in rows:
        parts = [c.strip() for c in (ln.split(delim) if delim else ln.split())]
        if len(parts) < width:
            skipped += 1
            continue
        vals = []
        for c in parts[:width]:
            try:
                vals.append(float(c))
            except ValueError:
                vals.append(np.nan)
        data.append(vals)
    a = np.array(data, dtype=float)
    if a.size == 0:
        raise ParseError("no numeric rows")
    if a.shape[1] == 1:
        if tau0 is None:
            raise ParseError("single-column file: pass tau0 (sample interval, seconds)")
        t = np.arange(a.shape[0]) * float(tau0)
        return [_finish(list(t), list(a[:, 0]), name, "csv", meta={"skipped_lines": skipped, "synthetic_time": True})]
    ti, oi = 0, 1
    if header:
        tis = [i for i, h in enumerate(header) if h in ("unix_time", "time", "t", "timestamp", "posix_time", "epoch")]
        if not tis:
            if tau0 is None:
                raise ParseError("CSV header has no time column (unix_time/time/timestamp); pass tau0 for "
                                 "uniformly sampled offsets")
            oi = next((i for i, h in enumerate(header) if h in ("offset", "offset_s", "theta", "phase", "x")), 0)
            t = np.arange(a.shape[0]) * float(tau0)
            extra = {h: a[:, i] for i, h in enumerate(header) if i != oi}
            return [_finish(t, a[:, oi], name, "csv", extra=extra,
                            meta={"skipped_lines": skipped, "synthetic_time": True})]
        ti = tis[0]
        for i, h in enumerate(header):
            if h in ("offset", "offset_s", "theta", "phase", "x"):
                oi = i
                break
    extra = {}
    if header:
        for i, h in enumerate(header):
            if i not in (ti, oi) and np.isfinite(a[:, i]).any():
                extra[h] = a[:, i]
    ok = np.isfinite(a[:, ti]) & np.isfinite(a[:, oi])
    s = TimeSeries(
        t=a[ok, ti], offset=a[ok, oi], name=name, source_format="csv",
        extra={k: v[ok] for k, v in extra.items()}, meta={"skipped_lines": skipped},
    )
    return [s.sorted()]


_W32_DATE_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                     "%d.%m.%Y %H:%M:%S")
FILETIME_UNIX_DELTA = 11644473600  # seconds from 1601-01-01 to 1970-01-01


def parse_w32tm(lines, name="w32tm") -> List[TimeSeries]:
    """``w32tm /stripchart /dataonly`` text, or ``w32tm /stripchart /rdtsc`` CSV.

    The offset is w32tm's NtpOffset, "computed as per NTP offset
    computations" (server - local), which is the ntpstats convention. The
    text form only prints a time of day: the date comes from the "The current
    time is ..." line when it can be read, and the times are the local wall
    clock of the Windows host (the time zone is not in the output).
    """
    import datetime as _dt

    target = ""
    for ln in lines[:10]:
        m = re.match(r"\s*Tracking\s+(\S+)", ln)
        if m:
            target = m.group(1).rstrip(".")
    rd = [i for i, ln in enumerate(lines) if _W32_RDTSC.search(ln)]
    if rd:
        hdr = [h.strip().lower() for h in lines[rd[0]].split(",")]
        ix = {h: k for k, h in enumerate(hdr)}
        t, off, dly = [], [], []
        for ln in lines[rd[0] + 1:]:
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) < len(hdr):
                continue
            try:
                ft = int(parts[ix["filetime"]], 0)
                t.append(ft / 1e7 - FILETIME_UNIX_DELTA)
                off.append(float(parts[ix["ntpoffset"]].rstrip("s")))
                dly.append(float(parts[ix["roundtripdelay"]].rstrip("s")))
            except (ValueError, KeyError):
                continue
        return [_finish(t, off, name, "w32tm", extra={"delay": dly}, meta={"peer": target, "mode": "rdtsc"})]
    base = None
    for ln in lines[:10]:
        m = re.search(r"current time is\s+(.+?)\.?\s*$", ln, re.I)
        if m:
            for fmt in _W32_DATE_FORMATS:
                try:
                    base = _dt.datetime.strptime(m.group(1).strip(), fmt).replace(tzinfo=_dt.timezone.utc)
                    break
                except ValueError:
                    continue
    day0 = (base.replace(hour=0, minute=0, second=0, microsecond=0) if base
            else _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)).timestamp()
    t, off, dly = [], [], []
    day, last = 0, -1
    for ln in lines:
        m = _W32_LINE.match(ln)
        if not m:
            continue
        sod = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        if sod < last - 43200:
            day += 1  # past midnight
        last = sod
        t.append(day0 + day * 86400 + sod)
        off.append(float(m.group(5)))
        dly.append(float(m.group(4)) if m.group(4) else np.nan)
    extra = {"delay": dly} if np.isfinite(dly).any() else None
    meta = {"peer": target, "mode": "dataonly", "clock": "local wall clock of the Windows host"}
    if base is None:
        meta["note"] = "date not found in the output: times start at 1970-01-01"
    return [_finish(t, off, name, "w32tm", extra=extra, meta=meta)]


def parse_prometheus(lines, name="prometheus", negate: bool = False) -> List[TimeSeries]:
    """A saved Prometheus ``query_range`` JSON response (one series per label set).

    Offsets are taken as reference - local (e.g. ntpd-rs ``ntp_source_offset_seconds``,
    "offset between the upstream source and system time"). Use ``negate`` for
    metrics that report local - reference.
    """
    import json

    doc = json.loads("\n".join(lines))
    data = doc.get("data", doc)
    if data.get("resultType") != "matrix":
        raise ParseError("Prometheus JSON: expected a range query (resultType matrix)")
    out = []
    for r in data.get("result", []):
        labels = r.get("metric", {})
        vals = np.array([[float(a), float(b)] for a, b in r.get("values", [])], dtype=float).reshape(-1, 2)
        if not len(vals):
            continue
        label = labels.get("name") or labels.get("address") or labels.get("instance") or labels.get("__name__", "")
        extra_lab = ",".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "__name__")
        off = -vals[:, 1] if negate else vals[:, 1]
        out.append(_finish(vals[:, 0], off, f"{name} [{labels.get('__name__', 'query')} {label}]".strip(),
                           "prometheus", meta={"peer": label, "labels": extra_lab}))
    if not out:
        raise ParseError("Prometheus JSON has no samples")
    return out


_PARSERS: Dict[str, Callable[..., List[TimeSeries]]] = {
    "loopstats": parse_loopstats,
    "peerstats": parse_peerstats,
    "rawstats": parse_rawstats,
    "chrony-tracking": parse_chrony_tracking,
    "chrony-measurements": parse_chrony_measurements,
    "chrony-statistics": parse_chrony_statistics,
    "chrony-refclocks": parse_chrony_refclocks,
    "linuxptp": parse_linuxptp,
    "w32tm": parse_w32tm,
    "prometheus": parse_prometheus,
    "gsoc2012": parse_gsoc2012,
}


def _plugin_parsers():
    from . import plugins, research  # noqa: F401

    return plugins.parsers()


FORMAT_DESCRIPTIONS = {
    "loopstats": "ntpd/NTPsec loopstats", "peerstats": "ntpd/NTPsec peerstats", "rawstats": "ntpd/NTPsec rawstats",
    "chrony-tracking": "chrony tracking.log", "chrony-measurements": "chrony measurements.log",
    "chrony-statistics": "chrony statistics.log", "chrony-refclocks": "chrony refclocks.log",
    "linuxptp": "linuxptp (ptp4l/phc2sys/ts2phc)", "pcap": "pcap / pcapng capture (NTP, PTP)",
    "csv": "CSV / columns", "stable32-phase": "Stable32 phase data", "stable32-freq": "Stable32 frequency data",
    "w32tm": "Windows w32tm", "prometheus": "Prometheus query_range JSON", "bounds": "clock-error bounds",
    "gsoc2012": "2012 estimators.log", "parquet": "Parquet (ntpstats.adapters, needs pyarrow)",
}


def format_descriptions() -> Dict[str, str]:
    """Every format (built-in and plugin) with a short description."""
    plug = {n: p.description for n, p in _plugin_parsers().items()}
    return {f: FORMAT_DESCRIPTIONS.get(f) or plug.get(f) or f for f in all_formats()}


def all_formats() -> List[str]:
    """Built-in formats plus those of installed parser plugins."""
    from . import plugins

    return list(FORMATS) + [f for f in plugins.external_parsers() if f not in FORMATS]


# --------------------------------------------------------------- public API
def load(source, fmt: str = "auto", tau0: Optional[float] = None, name: Optional[str] = None) -> List[TimeSeries]:
    """Load a log file (path, file object or text) and return one
    :class:`TimeSeries` per source/peer it contains."""
    if isinstance(source, str) and "\n" in source:
        source = io.StringIO(source)
    label = name or _name_of(source)
    if isinstance(source, (str, os.PathLike)) and os.path.isdir(source):
        # A directory of log files (e.g. the weekly interop dataset): concatenate its text files in name order.
        root = os.fspath(source)
        files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs
                       if not f.startswith(".") and not f.lower().endswith((".md", ".txt.md")))
        if not files:
            raise ParseError(f"{source}: empty directory")
        parts = []
        for f in files:
            with open(f, encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read().rstrip("\n"))
        return load(io.StringIO("\n".join(parts) + "\n"), fmt=fmt, tau0=tau0, name=label)
    # Binary packet captures (pcap / pcapng)
    raw = None
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as fh:
            head = fh.read(4)
        if head[:2] == b"\x1f\x8b":  # gzip (IGS products, compressed logs)
            import gzip

            with gzip.open(source, "rb") as fh:
                raw = fh.read()
            head = raw[:4]
            if not is_capture(head):
                source, raw = io.StringIO(raw.decode("utf-8", errors="replace")), None
        elif fmt == "pcap" or is_capture(head):
            with open(source, "rb") as fh:
                raw = fh.read()
    if isinstance(source, (str, os.PathLike)) and raw is None and fmt in ("auto", "parquet"):
        with open(source, "rb") as fh:
            if fh.read(4) == b"PAR1" or fmt == "parquet":
                from .adapters import read_parquet

                try:
                    series = read_parquet(os.fspath(source), name=name or None)
                except (ValueError, OSError) as exc:
                    raise ParseError(str(exc)) from exc
                for s in series:
                    s.meta.setdefault("file", label)
                return series
    if raw is not None and (fmt in ("auto", "pcap")) and is_capture(raw[:4]):
        try:
            series = parse_capture(raw, label)
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
        for s in series:
            s.meta.setdefault("file", label)
        return series
    if raw is not None:
        source = io.StringIO(raw.decode("utf-8", errors="replace"))
    lines = _read_lines(source)
    if fmt == "auto":
        fmt = detect_format(lines)
    if fmt == "csv":
        series = parse_csv(lines, label, tau0=tau0)
    elif fmt == "bounds":
        from .bounds import parse_bounds

        series = parse_bounds(lines, label)
    elif fmt.startswith("profile:"):
        from .profiles import load_profile, parse_with_profile

        try:
            series = [parse_with_profile(lines, load_profile(fmt.split(":", 1)[1]), label, tau0=tau0)]
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
    elif fmt in ("stable32-phase", "stable32-freq"):
        from .interop import read_stable32

        try:
            series = [read_stable32("\n".join(lines) + "\n", data_type=fmt.split("-")[1], tau0=tau0, name=label)]
        except ValueError as exc:
            raise ParseError(str(exc)) from exc
    elif fmt == "pcap":
        raise ParseError("not a pcap/pcapng capture")
    elif fmt in _plugin_parsers():
        try:
            series = _plugin_parsers()[fmt].parse(lines, label)
        except (ValueError, KeyError) as exc:
            raise ParseError(str(exc)) from exc
    elif fmt in _PARSERS:
        series = _PARSERS[fmt](lines, label)
    else:
        raise ParseError(f"unknown format {fmt!r}; choose from {', '.join(all_formats())}")
    for s in series:
        s.meta.setdefault("file", label)
    return series


def load_one(source, fmt: str = "auto", peer: Optional[str] = None, **kw) -> TimeSeries:
    """Load a single series. For multi-peer logs pick ``peer`` (substring
    match on the address) or, by default, the peer ntpd selected as
    ``sys.peer`` most often, else the one with the most samples."""
    series = load(source, fmt=fmt, **kw)
    if peer is not None:
        hits = [s for s in series if peer in str(s.meta.get("peer", s.name))]
        if not hits:
            avail = ", ".join(str(s.meta.get("peer", s.name)) for s in series)
            raise ParseError(f"peer {peer!r} not found; available: {avail}")
        return hits[0]
    return max(series, key=lambda s: (s.meta.get("sys_peer_fraction", 0.0), len(s)))
