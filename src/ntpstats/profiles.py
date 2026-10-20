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

Without a profile file, ``--columns`` (or ``-f columns:SPEC``) maps the
columns inline, for example ``--columns time=Time:iso,value=TIE,units=ns``
(see :func:`columns_profile`), and :func:`guess_columns` proposes a mapping
from the file itself (``ntpstats columns FILE``), which
:func:`profile_toml` saves as a profile.
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
    return check_profile(prof)


def check_profile(prof: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a profile dictionary (raises ValueError) and return it."""
    prof.setdefault("name", "profile")
    unknown = set(prof) - _KEYS
    if unknown:
        raise ValueError(f"profile {prof['name']}: unknown keys {sorted(unknown)}")
    if "value_column" not in prof:
        raise ValueError(f"profile {prof['name']}: value_column is required")
    if prof.get("units", "s") not in UNITS or prof.get("time_units", "s") not in UNITS:
        raise ValueError(f"profile {prof['name']}: units must be one of {', '.join(UNITS)}")
    if prof.get("quantity", "offset") not in ("te", "offset"):
        raise ValueError(f"profile {prof['name']}: quantity must be 'te' or 'offset'")
    if prof.get("time_format", "unix") not in TIME_FORMATS:
        raise ValueError(f"profile {prof['name']}: time_format must be one of {', '.join(TIME_FORMATS)}")
    return prof


TIME_FORMATS = ("unix", "iso", "mjd", "elapsed")
#: short names accepted by --columns, and the profile keys they set
COLUMN_ALIASES = {"time": "time_column", "value": "value_column", "offset": "value_column",
                  "te": "value_column", "format": "time_format", "time_format": "time_format",
                  "units": "units", "time_units": "time_units", "quantity": "quantity", "tau0": "tau0",
                  "delimiter": "delimiter", "comment": "comment", "skip": "skip_rows",
                  "skip_rows": "skip_rows", "header": "header", "extra": "extra_columns",
                  "name": "name", "description": "description"}
_DELIMS = {"comma": ",", "semicolon": ";", "tab": "\t", "space": " ", "spaces": None}


def _cell(v: str):
    v = v.strip()
    return int(v) if re.fullmatch(r"\d+", v) else v


def columns_profile(spec: str) -> Dict[str, Any]:
    """A profile from an inline column mapping.

    ``spec`` is a comma-separated list of ``key=value`` pairs. Columns are
    0-based indices or header names. Keys: ``time`` (optionally
    ``time=NAME:FORMAT`` with FORMAT unix, iso, mjd or elapsed), ``value``
    (also ``offset=`` for reference - local or ``te=`` for local - reference,
    which sets ``quantity``), ``units``, ``time_units``, ``quantity``,
    ``tau0``, ``delimiter`` (``comma``, ``semicolon``, ``tab``, ``space``),
    ``skip``, ``header``, ``comment`` and ``extra`` (several columns joined
    with ``+``). Example: ``time=Time:iso,te=TIE,units=ns,extra=Delay``.
    """
    prof: Dict[str, Any] = {"name": "columns"}
    for item in (x for x in spec.split(",") if x.strip()):
        if "=" not in item:
            raise ValueError(f"--columns: {item!r} is not key=value")
        k, v = (x.strip() for x in item.split("=", 1))
        key = COLUMN_ALIASES.get(k.lower())
        if key is None:
            raise ValueError(f"--columns: unknown key {k!r}; use {', '.join(sorted(COLUMN_ALIASES))}")
        if key == "time_column" and ":" in v and v.rsplit(":", 1)[1].lower() in TIME_FORMATS:
            v, prof["time_format"] = v.rsplit(":", 1)[0], v.rsplit(":", 1)[1].lower()
        if key == "value_column" and k.lower() in ("te", "offset"):
            prof["quantity"] = k.lower()
        if key == "extra_columns":
            prof[key] = [_cell(c) for c in v.split("+") if c.strip()]
        elif key == "delimiter":
            d = _DELIMS.get(v.lower(), v)
            if d is not None:
                prof[key] = "\t" if d == "\\t" else d
        elif key in ("tau0",):
            prof[key] = float(v)
        elif key == "skip_rows":
            prof[key] = int(v)
        elif key == "header":
            prof[key] = {"true": True, "yes": True, "false": False, "no": False}.get(v.lower(), "auto")
        elif key in ("time_column", "value_column"):
            prof[key] = _cell(v)
        else:
            prof[key] = v
    return check_profile(prof)


def columns_spec(prof: Dict[str, Any]) -> str:
    """The ``--columns`` spec of a profile (the inverse of :func:`columns_profile`)."""
    out = []
    if "time_column" in prof:
        out.append(f"time={prof['time_column']}:{prof.get('time_format', 'unix')}")
    out.append(f"{prof.get('quantity', 'offset')}={prof['value_column']}")
    for k in ("units", "time_units"):
        if prof.get(k, "s") != "s":
            out.append(f"{k}={prof[k]}")
    if "tau0" in prof and "time_column" not in prof:
        out.append(f"tau0={prof['tau0']:g}")
    if prof.get("delimiter"):
        out.append("delimiter=" + {",": "comma", ";": "semicolon", "\t": "tab", " ": "space"}.get(
            prof["delimiter"], prof["delimiter"]))
    if prof.get("skip_rows"):
        out.append(f"skip={prof['skip_rows']}")
    if prof.get("extra_columns"):
        out.append("extra=" + "+".join(str(c) for c in prof["extra_columns"]))
    return ",".join(out)


def profile_toml(prof: Dict[str, Any]) -> str:
    """A profile as the TOML text that :func:`load_profile` reads back."""
    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(val(x) for x in v) + "]"
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t") + '"'
    order = ["name", "description", "time_column", "time_format", "time_units", "value_column", "units",
             "quantity", "tau0", "delimiter", "comment", "skip_rows", "header", "extra_columns"]
    keys = [k for k in order if k in prof] + sorted(set(prof) - set(order))
    return "".join(f"{k} = {val(prof[k])}\n" for k in keys)


_UNIT_HINT = re.compile(r"(?:^|[\s_(\[/-])(ps|ns|us|µs|ms|s|sec|seconds|nanoseconds?|microseconds?|milliseconds?)"
                        r"(?:$|[\s_)\]])", re.I)
_UNIT_WORDS = {"sec": "s", "seconds": "s", "nanosecond": "ns", "nanoseconds": "ns", "microsecond": "us",
               "microseconds": "us", "millisecond": "ms", "milliseconds": "ms", "µs": "us"}
_VALUE_HINT = re.compile(r"tie|time.?error|\bte\b|offset|phase|interval|\btic\b|error|diff|value", re.I)
_TE_HINT = re.compile(r"tie|time.?error|\bte\b|interval|\btic\b|dut", re.I)
_OFFSET_HINT = re.compile(r"offset", re.I)
_TIME_HINT = re.compile(r"time|date|epoch|stamp|mjd|utc|elapsed|^t$|^sec", re.I)


def _units_from_name(name: str) -> Optional[str]:
    m = _UNIT_HINT.search(name)
    if not m:
        return None
    u = m.group(1).lower()
    return _UNIT_WORDS.get(u, u) if _UNIT_WORDS.get(u, u) in UNITS else None


def guess_columns(lines: List[str], max_rows: int = 200) -> Dict[str, Any]:
    """Propose a column mapping for a column file.

    Returns ``{"profile": ..., "spec": ..., "columns": [...], "header": ...,
    "rows": [...], "notes": [...]}``: the proposed profile (validated), its
    ``--columns`` spec, one entry per column (``index``, ``name``, ``kind``
    among iso, unix, mjd, elapsed, number, text, and an ``example``), the
    header and the first rows as split, and notes on what was guessed and
    should be checked (units and sign in particular).
    """
    comment = "#"
    rows = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith(comment)]
    if not rows:
        raise ValueError("no data lines")
    delim = next((d for d in (",", ";", "\t") if d in rows[min(1, len(rows) - 1)]), None)
    first = _split(rows[0], delim)
    has_header = not all(np.isfinite(_num(c)) for c in first if c and not re.match(r"^\d{4}-\d\d-\d\d", c))
    header = first if has_header else None
    data = [_split(r, delim) for r in (rows[1:] if has_header else rows)[:max_rows]]
    if not data:
        raise ValueError("only a header line, no data")
    ncol = max(len(r) for r in data)
    notes: List[str] = []
    cols: List[Dict[str, Any]] = []
    for i in range(ncol):
        vals = [r[i] for r in data if i < len(r) and r[i] != ""]
        name = header[i] if header and i < len(header) else str(i)
        kind = "text"
        nums = np.array([_num(v) for v in vals])
        if vals and all(re.match(r"^\d{4}-\d\d-\d\d[T ]\d", v) for v in vals[:20]):
            kind = "iso"
        elif vals and np.isfinite(nums).mean() > 0.9:
            fin = nums[np.isfinite(nums)]
            mono = fin.size > 2 and bool(np.all(np.diff(fin) >= 0)) and fin[-1] > fin[0]
            if mono and 3e8 < fin[0] < 5e9:
                kind = "unix"
            elif mono and 3e4 < fin[0] < 1e5 and np.median(np.diff(fin)) < 1:
                kind = "mjd"
            elif mono and fin[0] >= 0 and _TIME_HINT.search(name or ""):
                kind = "elapsed"
            else:
                kind = "number"
        cols.append({"index": i, "name": name, "kind": kind, "example": vals[0] if vals else ""})
    times = [c for c in cols if c["kind"] in ("iso", "unix", "mjd", "elapsed")]
    numbers = [c for c in cols if c["kind"] == "number"]
    if not numbers:
        raise ValueError("no numeric column that could hold the offset or time error")
    hinted = [c for c in numbers if header and _VALUE_HINT.search(c["name"])]
    value = (hinted or numbers)[0]

    def ref(c):
        return c["name"] if header else c["index"]

    prof: Dict[str, Any] = {"name": "columns", "value_column": ref(value)}
    if delim:
        prof["delimiter"] = delim
    if times:
        prof["time_column"] = ref(times[0])
        prof["time_format"] = times[0]["kind"]
    else:
        prof["tau0"] = 1.0
        notes.append("no time column found: samples are taken 1 s apart (set tau0=...)")
    vname = str(value["name"]) if header else ""
    units = _units_from_name(vname)
    if units:
        prof["units"] = units
        notes.append(f"units {units} from the column name {vname!r}")
    else:
        fin = np.abs([_num(r[value["index"]]) for r in data if value["index"] < len(r)])
        fin = fin[np.isfinite(fin) & (fin > 0)]
        med = float(np.median(fin)) if fin.size else 0.0
        prof["units"] = "s" if med < 0.5 else "ns"
        notes.append(f"units guessed as {prof['units']} from the magnitude of the values (median |value| "
                     f"{med:.3g}); check them")
    if header and _OFFSET_HINT.search(vname) and not _TE_HINT.search(vname):
        prof["quantity"] = "offset"
        notes.append("sign: the column is an offset, taken as reference - local")
    else:
        prof["quantity"] = "te"
        notes.append("sign: taken as time error, local (DUT) - reference, as instruments report it; "
                     "use offset= instead of te= if the file logs reference - local")
    extras = [ref(c) for c in numbers if c is not value][:8]
    if extras:
        prof["extra_columns"] = extras
    check_profile(prof)
    return {"profile": prof, "spec": columns_spec(prof), "columns": cols, "header": header,
            "rows": data[:5], "notes": notes}


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
