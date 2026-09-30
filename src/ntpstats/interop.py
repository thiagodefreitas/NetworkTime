# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Data exchange with other frequency-stability tools.

**Stable32** (W. Riley; free from IEEE UFFC) reads and writes plain ASCII
data files: one or more comma- or space-delimited numeric columns, optional
timetags (usually MJD) in the first column, and non-numeric header or
comment lines, which it skips. :func:`read_stable32` and
:func:`write_stable32` use that layout, so a dataset can be analysed in
both tools and the results compared.

Phase data are time deviations in seconds; frequency data are fractional
(dimensionless). Frequency data are integrated to phase on input
(``x[0] = 0``, ``x[i+1] = x[i] + y[i] * tau0``), as Stable32 does for its
phase-based statistics.

**TimeLab** (J. Miles, KE5FX): its native ``.tim`` format is not publicly
documented, so it is not read yet. Plain phase or frequency columns, which
:func:`write_stable32` writes with ``timetags=False``, are the usual way to
move data into it. Sample ``.tim`` files are welcome in issue #33.
"""

from __future__ import annotations

import io
import os
import re
from typing import IO, List, Optional, Union

import numpy as np

from .series import MJD_UNIX_EPOCH, TimeSeries

_SPLIT = re.compile(r"[,;\s]+")
DATA_TYPES = ("phase", "freq")


def _lines(source) -> List[str]:
    if isinstance(source, (str, os.PathLike)) and not (isinstance(source, str) and "\n" in source):
        with open(source, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    if isinstance(source, str):
        return source.splitlines()
    return source.read().splitlines()


def _numeric_rows(lines: List[str]) -> List[List[float]]:
    rows = []
    for ln in lines:
        parts = [p for p in _SPLIT.split(ln.strip()) if p]
        if not parts:
            continue
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            continue  # header, comment or non-numeric timetag line
    return rows


def _looks_like_mjd(col: np.ndarray) -> bool:
    ok = col[np.isfinite(col)]
    return ok.size > 1 and bool(np.all((ok > 15000) & (ok < 100000))) and bool(np.all(np.diff(ok) > 0))


def read_stable32(
    source,
    data_type: str = "phase",
    tau0: Optional[float] = None,
    column: int = -1,
    name: Optional[str] = None,
) -> TimeSeries:
    """Read a Stable32-style ASCII data file.

    ``column`` selects the data column (default: the last). With two or more
    columns, a first column that looks like MJD is used as the timetag;
    otherwise samples are spaced ``tau0`` apart (required then). A ``tau0``
    derived from timetags is rounded to 6 significant digits; pass it
    explicitly when more precision matters. Frequency
    data (``data_type="freq"``) are integrated to phase; zero or missing
    frequency values are gaps, as in Stable32.
    """
    if data_type not in DATA_TYPES:
        raise ValueError(f"data_type must be one of {DATA_TYPES}")
    rows = _numeric_rows(_lines(source))
    if not rows:
        raise ValueError("no numeric data")
    width = min(len(r) for r in rows)
    a = np.array([r[:width] for r in rows], dtype=float)
    values = a[:, column]
    t = None
    if width >= 2 and _looks_like_mjd(a[:, 0]) and (column % width) != 0:
        t = (a[:, 0] - MJD_UNIX_EPOCH) * 86400.0
    if tau0 is None:
        if t is None:
            raise ValueError("no timetags: pass tau0 (sample interval, seconds)")
        # MJD timetags are quantised (1e-11 day = 0.9 us): keep 6 significant digits
        tau0 = float(f"{np.median(np.diff(t)):.6g}")
    if t is None:
        t = np.arange(values.size, dtype=float) * float(tau0)
    if data_type == "freq":
        # Stable32 marks gaps in frequency data with zeros. Integrate across a
        # gap with the mean frequency (so later phase stays close) but mark the
        # phase points inside it NaN, so no statistic uses them.
        gap = ~np.isfinite(values) | (values == 0.0)
        fill = float(np.mean(values[~gap])) if (~gap).any() else 0.0
        y = np.where(gap, fill, values)
        # y[i] is the average over [t[i], t[i] + tau0): phase has one more point
        values = np.concatenate(([0.0], np.cumsum(y * float(tau0))))
        values[1:][gap] = np.nan
        t = np.concatenate((t, [t[-1] + float(tau0)]))
    label = name or (os.path.basename(source) if isinstance(source, (str, os.PathLike)) and "\n" not in str(source)
                     else "stable32")
    return TimeSeries(t=t, offset=values, name=str(label), source_format=f"stable32-{data_type}",
                      meta={"tau0": float(tau0), "data_type": data_type}).sorted()


def write_stable32(
    series: TimeSeries,
    dest: Union[str, os.PathLike, IO[str]],
    data_type: str = "phase",
    timetags: bool = True,
    tau0: Optional[float] = None,
    max_gap: float = 3.0,
) -> int:
    """Write ``series`` as a Stable32 data file; returns the number of rows.

    The series is first put on a uniform grid (:meth:`TimeSeries.to_uniform`).
    Gaps are written as ``0`` frequency values (Stable32's gap marker) or,
    for phase with timetags, as missing timetags; phase without timetags
    cannot mark a gap and is refused if it has one. Values carry 15
    significant digits.
    """
    if data_type not in DATA_TYPES:
        raise ValueError(f"data_type must be one of {DATA_TYPES}")
    grid, x, step = series.to_uniform(tau0=tau0, max_gap=max_gap)
    if data_type == "phase":
        t, v = grid, x
    else:
        t, v = grid[:-1], np.diff(x) / step
    if data_type == "phase" and not timetags and not np.all(np.isfinite(v)):
        raise ValueError("phase data with gaps need timetags (or write frequency data)")
    mjd = t / 86400.0 + MJD_UNIX_EPOCH
    buf = io.StringIO()
    rows = 0
    for tt, vv in zip(mjd, v):
        if not np.isfinite(vv):
            if data_type == "phase":
                continue  # a missing timetag marks the gap
            vv = 0.0  # Stable32's gap marker for frequency data
        buf.write(f"{tt:.11f} {vv:.15g}\n" if timetags else f"{vv:.15g}\n")
        rows += 1
    text = buf.getvalue()
    if isinstance(dest, (str, os.PathLike)):
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        dest.write(text)
    return rows
