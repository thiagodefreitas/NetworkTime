# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
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
``chrony-tracking`` / ``chrony-measurements`` / ``chrony-statistics``
    chrony's ``tracking.log``, ``measurements.log`` and ``statistics.log``
    (``log tracking measurements statistics`` in chrony.conf). chrony reports
    offsets as *local - reference*; they are negated here so every series
    uses the ntpd convention (see :mod:`ntpstats.series`).
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
from typing import Iterable, List, Optional, Sequence

import numpy as np

from .series import TimeSeries, mjd_to_unix

FORMATS = (
    "loopstats",
    "peerstats",
    "rawstats",
    "chrony-tracking",
    "chrony-measurements",
    "chrony-statistics",
    "csv",
    "gsoc2012",
)

#: Seconds between the NTP era-0 epoch (1900) and the POSIX epoch (1970).
NTP_UNIX_DELTA = 2208988800

_CHRONY_TS = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}")
_LEGACY = re.compile(r"Logged:\s*\[off,\s*([-+0-9.eE]+),\s*time,\s*([-+0-9.eE]+)\]")
_LEAP_CODES = {"N", "+", "-", "?"}


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
        return os.path.basename(os.fspath(source))
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
def detect_format(lines: Sequence[str]) -> str:
    """Guess the format of a log from its first lines."""
    header = " ".join(ln for ln in lines[:20] if ln.strip() and not ln.strip()[0].isdigit())
    for ln in lines[:200]:
        if _LEGACY.search(ln):
            return "gsoc2012"
    sample = [ln for ln in _data_lines(lines[:400]) if ln[0].isdigit() or ln[0] in "+-."][:50]
    if not sample:
        raise ParseError("no data lines found")
    fields = sample[0].split()
    if _CHRONY_TS.match(sample[0]):
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
    return "csv"


# ----------------------------------------------------------------- parsers
def _finish(t, off, name, fmt, extra=None, meta=None) -> TimeSeries:
    if not t:
        raise ParseError(f"no usable samples for format {fmt}")
    s = TimeSeries(
        t=np.array(t),
        offset=np.array(off),
        name=name,
        source_format=fmt,
        extra={k: np.array(v) for k, v in (extra or {}).items()},
        meta=meta or {},
    )
    return s.sorted()


def parse_loopstats(lines, name="loopstats") -> List[TimeSeries]:
    rows, skipped = [], 0
    for ln in _data_lines(lines):
        f = ln.split()
        try:
            rows.append([float(mjd_to_unix(int(f[0]), float(f[1])))] + [float(v) for v in f[2:7]])
        except (ValueError, IndexError):
            skipped += 1
            continue
        if len(rows[-1]) != 6:
            rows.pop()
            skipped += 1
    if not rows:
        raise ParseError("no usable loopstats lines")
    a = np.array(rows)
    return [
        _finish(
            list(a[:, 0]), list(a[:, 1]), name, "loopstats",
            extra={"frequency_ppm": a[:, 2], "jitter": a[:, 3], "wander_ppm": a[:, 4], "time_constant": a[:, 5]},
            meta={"skipped_lines": skipped},
        )
    ]


def _peer_status_select(status: str) -> int:
    try:
        return (int(status, 16) >> 8) & 0x7
    except ValueError:
        return -1


def parse_peerstats(lines, name="peerstats") -> List[TimeSeries]:
    peers: "OrderedDict[str, dict]" = OrderedDict()
    skipped = 0
    for ln in _data_lines(lines):
        f = ln.split()
        try:
            row = (
                float(mjd_to_unix(int(f[0]), float(f[1]))),
                float(f[4]), float(f[5]), float(f[6]), float(f[7]),
                _peer_status_select(f[3]),
            )
        except (ValueError, IndexError):
            skipped += 1
            continue
        peers.setdefault(f[2], []).append(row)
    out = []
    for addr, rows in peers.items():
        a = np.array(rows)
        out.append(
            _finish(
                list(a[:, 0]), list(a[:, 1]), f"{name} [{addr}]", "peerstats",
                extra={"delay": a[:, 2], "dispersion": a[:, 3], "jitter": a[:, 4]},
                # select code 6 = sys.peer, 7 = pps.peer (RFC 5905 / ntpd decode.html)
                meta={"peer": addr, "sys_peer_fraction": float(np.mean(np.isin(a[:, 5], (6, 7)))), "skipped_lines": skipped},
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


def _parse_chrony(lines, name, fmt, off_idx, extra_cols, min_fields, group=True) -> List[TimeSeries]:
    groups: "OrderedDict[str, list]" = OrderedDict()
    skipped = 0
    for ln in _data_lines(lines):
        if not _CHRONY_TS.match(ln):
            continue
        f = ln.split()
        if len(f) < min_fields:
            skipped += 1
            continue
        try:
            row = [_chrony_time(f[0], f[1]), -float(f[off_idx])]
            row += [float(f[i]) for _, i in extra_cols]
        except ValueError:
            skipped += 1
            continue
        key = f[2] if group else "all"
        groups.setdefault(key, []).append(row)
    out = []
    for key, rows in groups.items():
        a = np.array(rows)
        label = f"{name} [{key}]" if group else name
        meta = {"skipped_lines": skipped, "sign": "negated from chrony (now server - local)"}
        if group:
            meta["peer"] = key
        out.append(
            _finish(
                list(a[:, 0]), list(a[:, 1]), label, fmt,
                extra={k: a[:, 2 + j] for j, (k, _) in enumerate(extra_cols)}, meta=meta,
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
    return _parse_chrony(lines, name, "chrony-measurements", base, extra, base + 5)


def parse_chrony_statistics(lines, name="statistics.log") -> List[TimeSeries]:
    # Date Time IP Std_dev Est_offset Offset_sd Diff_freq Est_skew Stress Ns Bs Nr [Asym]
    extra = [("std_dev", 3), ("offset_sd", 5), ("diff_freq", 6), ("est_skew", 7)]
    return _parse_chrony(lines, name, "chrony-statistics", 4, extra, 8)


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
        for i, h in enumerate(header):
            if h in ("unix_time", "time", "t", "timestamp", "posix_time", "epoch"):
                ti = i
                break
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


_PARSERS = {
    "loopstats": parse_loopstats,
    "peerstats": parse_peerstats,
    "rawstats": parse_rawstats,
    "chrony-tracking": parse_chrony_tracking,
    "chrony-measurements": parse_chrony_measurements,
    "chrony-statistics": parse_chrony_statistics,
    "gsoc2012": parse_gsoc2012,
}


# --------------------------------------------------------------- public API
def load(source, fmt: str = "auto", tau0: Optional[float] = None, name: Optional[str] = None) -> List[TimeSeries]:
    """Load a log file (path, file object or text) and return one
    :class:`TimeSeries` per source/peer it contains."""
    if isinstance(source, str) and "\n" in source:
        source = io.StringIO(source)
    lines = _read_lines(source)
    label = name or _name_of(source)
    if fmt == "auto":
        fmt = detect_format(lines)
    if fmt == "csv":
        series = parse_csv(lines, label, tau0=tau0)
    elif fmt in _PARSERS:
        series = _PARSERS[fmt](lines, label)
    else:
        raise ParseError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
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
