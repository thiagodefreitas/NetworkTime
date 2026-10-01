# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Declarative import profiles for instrument exports and other column files.

Test equipment (time-interval counters, PTP/SyncE testers, frequency
counters) exports CSV files whose layout differs per vendor and firmware. A
**profile** describes one layout in a few TOML lines, so a new instrument
needs no Python code:

.. code-block:: toml

    name = "my-tic"
    description = "53230A time interval, DUT 1PPS minus REF 1PPS, one reading per line"
    value_column = 0          # index or header name
    units = "ns"              # s, ms, us, ns, ps
    quantity = "te"           # te: local - reference; offset: reference - local
    tau0 = 1.0                # sample interval when there is no time column

    # optional
    time_column = "Time"      # index or header name
    time_format = "unix"      # unix | iso | mjd | elapsed (seconds from start)
    time_units = "s"          # for unix/elapsed
    delimiter = ","           # default: auto (comma, semicolon, tab or spaces)
    comment = "#"
    skip_rows = 0             # lines to skip before the header or data
    header = "auto"           # true | false | auto
    extra_columns = ["MeanPathDelay"]

Use ``-f profile:NAME`` for a built-in profile or ``-f profile:path.toml``
for your own. Built-ins cover generic layouts only; vendor-specific profiles
are added from sample exports that users contribute (issue #35).
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Any, Dict, List, Optional

import numpy as np

from .series import MJD_UNIX_EPOCH, TimeSeries

UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9, "ps": 1e-12}

BUILTIN: Dict[str, Dict[str, Any]] = {
    "te-csv": {"description": "unix_time, time error (s, local - reference) with a header or not",
               "time_column": 0, "time_format": "unix", "value_column": 1, "units": "s", "quantity": "te"},
    "tic-ns": {"description": "one time-interval reading per line in ns (DUT - REF), 1 s apart",
               "value_column": 0, "units": "ns", "quantity": "te", "tau0": 1.0},
    "tic-s": {"description": "one time-interval reading per line in s (DUT - REF), 1 s apart",
              "value_column": 0, "units": "s", "quantity": "te", "tau0": 1.0},
    "iso-te-ns": {"description": "ISO 8601 timestamp, time error in ns (local - reference)",
                  "time_column": 0, "time_format": "iso", "value_column": 1, "units": "ns", "quantity": "te"},
}
_KEYS = {"name", "description", "value_column", "units", "quantity", "tau0", "time_column", "time_format",
         "time_units", "delimiter", "comment", "skip_rows", "header", "extra_columns"}


def _toml(text: str) -> Dict[str, Any]:
    import importlib

    try:
        toml: Any = importlib.import_module("tomllib")  # Python 3.11+
    except ModuleNotFoundError:
        try:
            toml = importlib.import_module("tomli")
        except ModuleNotFoundError as exc:
            raise ImportError("reading TOML profiles on Python < 3.11 needs: pip install 'ntpstats[toml]'") from exc
    return toml.loads(text)


def load_profile(ref: str) -> Dict[str, Any]:
    """A built-in profile name, or the path of a TOML profile file."""
    from .plugins import profile as plugin_profile

    if ref in BUILTIN:
        prof = dict(BUILTIN[ref], name=ref)
    elif plugin_profile(ref) is not None:
        prof = plugin_profile(ref)  # type: ignore[assignment]
    elif os.path.isfile(ref):
        with open(ref, encoding="utf-8") as fh:
            prof = _toml(fh.read())
        prof.setdefault("name", os.path.splitext(os.path.basename(ref))[0])
    else:
        raise ValueError(f"unknown profile {ref!r}: not a built-in ({', '.join(BUILTIN)}), a plugin, nor a file")
    unknown = set(prof) - _KEYS
    if unknown:
        raise ValueError(f"profile {prof['name']}: unknown keys {sorted(unknown)}")
    if "value_column" not in prof:
        raise ValueError(f"profile {prof['name']}: value_column is required")
    if prof.get("units", "s") not in UNITS or prof.get("time_units", "s") not in UNITS:
        raise ValueError(f"profile {prof['name']}: units must be one of {', '.join(UNITS)}")
    if prof.get("quantity", "offset") not in ("te", "offset"):
        raise ValueError(f"profile {prof['name']}: quantity must be 'te' or 'offset'")
    return prof


def _split(line: str, delim: Optional[str]) -> List[str]:
    if delim:
        return [c.strip() for c in line.split(delim)]
    for d in (",", ";", "\t"):
        if d in line:
            return [c.strip() for c in line.split(d)]
    return line.split()


def _num(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return float("nan")


def _col(spec, header: Optional[List[str]]) -> int:
    if isinstance(spec, int):
        return spec
    if header is None:
        raise ValueError(f"column {spec!r} given by name but the file has no header")
    low = [h.lower() for h in header]
    if str(spec).lower() not in low:
        raise ValueError(f"column {spec!r} not in header {header}")
    return low.index(str(spec).lower())


def _iso(v: str) -> float:
    v = v.strip().replace("Z", "+00:00")
    d = _dt.datetime.fromisoformat(v)
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def parse_with_profile(lines: List[str], prof: Dict[str, Any], name: str = "data",
                       tau0: Optional[float] = None) -> TimeSeries:
    """Parse ``lines`` with a profile; returns a series in ntpstats convention (reference - local)."""
    comment = prof.get("comment", "#")
    rows = [ln for ln in lines[int(prof.get("skip_rows", 0)):] if ln.strip() and not ln.lstrip().startswith(comment)]
    if not rows:
        raise ValueError("no data")
    delim = prof.get("delimiter")
    first = _split(rows[0], delim)
    hdr_opt = prof.get("header", "auto")
    has_header = (hdr_opt is True or str(hdr_opt).lower() == "true"
                  or (str(hdr_opt).lower() == "auto" and not all(np.isfinite(_num(c)) for c in first
                                                                if c and not re.match(r"^\d{4}-\d\d-\d\d", c))))
    header = first if has_header else None
    data = rows[1:] if has_header else rows
    vi = _col(prof["value_column"], header)
    ti = _col(prof["time_column"], header) if "time_column" in prof else None
    xi = [(c, _col(c, header)) for c in prof.get("extra_columns", [])]
    scale = UNITS[prof.get("units", "s")]
    tscale = UNITS[prof.get("time_units", "s")]
    fmt = prof.get("time_format", "unix")
    t, v, ex = [], [], {c: [] for c, _ in xi}  # type: ignore[var-annotated]
    skipped = 0
    for ln in data:
        p = _split(ln, delim)
        try:
            val = float(p[vi]) * scale
            if ti is None:
                tt = float("nan")
            elif fmt == "iso":
                tt = _iso(p[ti])
            elif fmt == "mjd":
                tt = (float(p[ti]) - MJD_UNIX_EPOCH) * 86400.0
            else:  # unix or elapsed
                tt = float(p[ti]) * tscale
        except (ValueError, IndexError):
            skipped += 1
            continue
        t.append(tt)
        v.append(val)
        for c, k in xi:
            ex[c].append(_num(p[k]) if k < len(p) else float("nan"))
    if not v:
        raise ValueError("no rows could be read with this profile")
    if ti is None:
        step = tau0 if tau0 is not None else prof.get("tau0")
        if step is None:
            raise ValueError(f"profile {prof['name']}: no time column, so tau0 is required")
        t = list(np.arange(len(v)) * float(step))
    off = np.asarray(v, dtype=float)
    if prof.get("quantity", "offset") == "te":
        off = -off  # TE = local - reference -> ntpstats offset = reference - local
    return TimeSeries(t=np.asarray(t, dtype=float), offset=off, name=name, source_format=f"profile:{prof['name']}",
                      extra={c: np.asarray(x, dtype=float) for c, x in ex.items()},
                      meta={"profile": prof["name"], "skipped_lines": skipped,
                            "synthetic_time": ti is None}).sorted()
