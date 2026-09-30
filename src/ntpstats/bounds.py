# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Validate clock-error bounds (uncertainty windows) against a reference.

Services such as AWS **ClockBound**, Meta's **fbclock** or a TrueTime-style
API report a window ``[earliest, latest]`` that should contain true time.
Given a better reference for the same host (a PTP/PPS comparison, or NTS
measurements when the bound is much wider than their delay), this module
checks how often the window really contains true time, and how tight it is.

Inputs are :class:`TimeSeries` with ``offset`` = window centre - local clock
(reference - local convention) and an ``extra["bound"]`` half-width:

* ClockBound example output, one line per call (``... true time was somewhere
  within A and B seconds since Jan 1 1970 ...``). ClockBound builds its window
  around the system clock reading, so the centre is the local time and the
  offset is 0.
* a CSV with ``earliest`` and ``latest`` columns (POSIX seconds) and optionally
  ``unix_time``, the local clock reading taken together with the window
  (needed for windows that are not centred on the system clock, e.g. fbclock,
  which is PHC-based) and ``status``.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import numpy as np

from .series import TimeSeries

_CB = re.compile(r"within\s+([\d.]+)\s+and\s+([\d.]+)\s+seconds.*?(?:status is\s+\"?([A-Za-z ]+?)\"?\s*\.?)?\s*$", re.I)


def _ns(v: str) -> int:
    """Decimal seconds string -> integer ns, exactly (a float cannot hold ns at 1.8e9 s)."""
    v = v.strip()
    neg = v.startswith("-")
    whole, _, frac = v.lstrip("+-").partition(".")
    ns = int(whole or 0) * 1_000_000_000 + int((frac + "000000000")[:9])
    return -ns if neg else ns


def parse_bounds(lines: List[str], name: str = "bounds") -> List[TimeSeries]:
    """ClockBound example lines, or a CSV with ``earliest``/``latest`` columns."""
    from .parsers import ParseError, _finish

    t, off, half, status = [], [], [], []
    rows = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if rows and "earliest" in rows[0].lower() and "latest" in rows[0].lower():
        hdr = [h.strip().lower() for h in re.split(r"[,;\t]", rows[0])]
        ix = {h: k for k, h in enumerate(hdr)}
        for ln in rows[1:]:
            parts = [p.strip() for p in re.split(r"[,;\t]", ln)]
            try:
                e, la = _ns(parts[ix["earliest"]]), _ns(parts[ix["latest"]])
                local = _ns(parts[ix["unix_time"]]) if "unix_time" in ix else (e + la) // 2
            except (ValueError, IndexError):
                continue
            t.append(local / 1e9)
            off.append(((e + la) / 2 - local) / 1e9)
            half.append((la - e) / 2e9)
            status.append(parts[ix["status"]] if "status" in ix and ix["status"] < len(parts) else "")
        source = "csv"
    else:
        for ln in rows:
            m = _CB.search(ln)
            if not m:
                continue
            e, la = _ns(m.group(1)), _ns(m.group(2))
            t.append((e + la) / 2e9)
            off.append(0.0)
            half.append((la - e) / 2e9)
            status.append((m.group(3) or "").strip())
        source = "clockbound"
    if not t:
        raise ParseError("no clock-error bounds found (expected earliest/latest columns or ClockBound output)")
    synced = np.array([s.lower() in ("", "synchronized", "synchronised") for s in status], dtype=float)
    return [_finish(t, off, name, "bounds", extra={"bound": half, "synchronized": synced},
                    meta={"bounds_source": source,
                          "statuses": sorted({s for s in status if s})})]


def validate(bounds: TimeSeries, reference: TimeSeries, max_gap: Optional[float] = None,
             reference_uncertainty: Optional[float] = None) -> Dict[str, object]:
    """Check how often true time (from ``reference``) lies inside the windows.

    ``reference`` offsets (reference - local) are interpolated linearly to each
    window time, only between reference samples closer than ``max_gap``
    seconds (default: 3 median reference intervals). The reference's own
    uncertainty is ``reference_uncertainty`` if given, else half its
    round-trip ``delay`` column when present, else 0. Each window is then:

    * **inside** when ``|error| + u <= bound``,
    * **violated** when ``|error| - u > bound``,
    * **indeterminate** otherwise (the reference is not good enough to tell),

    where ``error`` is true time minus the window centre.
    """
    rt, ro = reference.t, reference.offset
    order = np.argsort(rt)
    rt, ro = rt[order], ro[order]
    if rt.size < 2:
        raise ValueError("reference needs at least 2 samples")
    gap = max_gap if max_gap is not None else 3 * float(np.median(np.diff(rt)))
    ok = (bounds.t >= rt[0]) & (bounds.t <= rt[-1])
    jj = np.clip(np.searchsorted(rt, bounds.t, side="right"), 1, rt.size - 1)
    near = ok & ((rt[jj] - rt[jj - 1]) <= gap)
    ref_at = np.interp(bounds.t, rt, ro)
    if reference_uncertainty is not None:
        u = np.full(bounds.t.shape, float(reference_uncertainty))
    elif "delay" in reference.extra:
        u = np.interp(bounds.t, rt, np.abs(reference.extra["delay"][order])) / 2
    else:
        u = np.zeros(bounds.t.shape)
    b = bounds.extra["bound"]
    err = ref_at - bounds.offset
    use = near & np.isfinite(err) & np.isfinite(b)
    inside = use & (np.abs(err) + u <= b)
    violated = use & (np.abs(err) - u > b)
    n = int(use.sum())
    excess = np.abs(err[use]) - b[use]
    return {
        "compared": n,
        "inside": int(inside.sum()),
        "violations": int(violated.sum()),
        "indeterminate": int(n - inside.sum() - violated.sum()),
        "violation_rate": float(violated.sum() / n) if n else float("nan"),
        "worst_excess": float(excess.max()) if n else float("nan"),
        "median_bound": float(np.median(b[use])) if n else float("nan"),
        "median_abs_error": float(np.median(np.abs(err[use]))) if n else float("nan"),
        "tightness": float(np.median(np.abs(err[use])) / np.median(b[use])) if n else float("nan"),
        "median_reference_uncertainty": float(np.median(u[use])) if n else float("nan"),
        "violation_times": bounds.t[violated].tolist()[:100],
    }
