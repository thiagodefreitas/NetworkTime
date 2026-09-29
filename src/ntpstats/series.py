# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Time-series container used throughout ntpstats.

Sign convention
---------------
``offset`` always follows the ntpd / RFC 5905 convention::

    offset = server_time - local_time      (seconds)

i.e. a *positive* offset means the local clock is *behind* the reference.
chrony logs use the opposite sign; the chrony parsers negate on import so
every series in this package can be compared directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Optional

import numpy as np

#: Days between the MJD epoch (1858-11-17) and the POSIX epoch (1970-01-01).
MJD_UNIX_EPOCH = 40587


def mjd_to_unix(mjd, seconds):
    """Convert (Modified Julian Day, seconds past midnight UTC) to POSIX seconds."""
    return (np.asarray(mjd, dtype=float) - MJD_UNIX_EPOCH) * 86400.0 + np.asarray(seconds, dtype=float)


@dataclass
class TimeSeries:
    """An offset time series plus optional auxiliary columns.

    Attributes
    ----------
    t:
        Sample times, POSIX seconds (float64, UTC).
    offset:
        Clock offset in seconds (server - local).
    name:
        Human readable label (file name, peer address...).
    source_format:
        Parser that produced the series (``loopstats``, ``chrony-tracking``...).
    extra:
        Additional per-sample columns (``frequency_ppm``, ``jitter``,
        ``delay``...), same length as ``t``.
    meta:
        Free-form metadata (peer address, notes, warnings).
    """

    t: np.ndarray
    offset: np.ndarray
    name: str = ""
    source_format: str = ""
    extra: Dict[str, np.ndarray] = field(default_factory=dict)
    meta: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        self.t = np.asarray(self.t, dtype=float)
        self.offset = np.asarray(self.offset, dtype=float)
        if self.t.shape != self.offset.shape or self.t.ndim != 1:
            raise ValueError("t and offset must be 1-D arrays of equal length")
        for key, col in list(self.extra.items()):
            col = np.asarray(col, dtype=float)
            if col.shape != self.t.shape:
                raise ValueError(f"extra column {key!r} has wrong length")
            self.extra[key] = col

    def __len__(self) -> int:
        return int(self.t.size)

    # ------------------------------------------------------------------ views
    def select(self, mask) -> "TimeSeries":
        """Return a new series keeping only the samples where ``mask`` is true
        (``mask`` may also be an integer index array)."""
        mask = np.asarray(mask)
        return replace(
            self,
            t=self.t[mask],
            offset=self.offset[mask],
            extra={k: v[mask] for k, v in self.extra.items()},
            meta=dict(self.meta),
        )

    def sorted(self) -> "TimeSeries":
        """Return the series sorted by time with exact duplicate times removed."""
        order = np.argsort(self.t, kind="stable")
        s = self.select(order)
        if len(s) > 1:
            keep = np.concatenate(([True], np.diff(s.t) > 0))
            if not keep.all():
                s = s.select(keep)
        return s

    def between(self, start: Optional[float] = None, end: Optional[float] = None) -> "TimeSeries":
        """Restrict to ``start <= t <= end`` (POSIX seconds, either may be None)."""
        mask = np.ones(len(self), dtype=bool)
        if start is not None:
            mask &= self.t >= start
        if end is not None:
            mask &= self.t <= end
        return self.select(mask)

    # ------------------------------------------------------------ properties
    @property
    def span(self) -> float:
        return float(self.t[-1] - self.t[0]) if len(self) > 1 else 0.0

    def intervals(self) -> np.ndarray:
        return np.diff(self.t)

    def median_interval(self) -> float:
        """Median sampling interval in seconds (the natural ``tau0``)."""
        d = self.intervals()
        d = d[d > 0]
        if d.size == 0:
            raise ValueError("need at least two distinct sample times")
        return float(np.median(d))

    def regularity(self) -> float:
        """Fraction of intervals within 10 % of the median interval (1.0 = perfectly regular)."""
        d = self.intervals()
        if d.size == 0:
            return 1.0
        med = self.median_interval()
        return float(np.mean(np.abs(d - med) <= 0.1 * med))

    # --------------------------------------------------------------- resample
    def to_uniform(self, tau0: Optional[float] = None, max_gap: float = 3.0):
        """Resample onto a uniform grid for stability analysis.

        Returns ``(grid_t, x, tau0)`` where ``x`` is the offset (phase) linearly
        interpolated on the grid. Grid points that fall inside a gap longer
        than ``max_gap * tau0`` are set to NaN so that the stability
        estimators simply skip the terms that touch them instead of
        inventing data.
        """
        s = self.sorted()
        if len(s) < 2:
            raise ValueError("need at least two samples")
        if tau0 is None:
            tau0 = s.median_interval()
        tau0 = float(tau0)
        n = int(np.floor(s.span / tau0)) + 1
        grid = s.t[0] + tau0 * np.arange(n)
        x = np.interp(grid, s.t, s.offset)
        # Mark grid points lying in large gaps.
        idx = np.searchsorted(s.t, grid, side="right")
        idx = np.clip(idx, 1, len(s) - 1)
        gap = s.t[idx] - s.t[idx - 1]
        on_sample = np.isclose(grid, s.t[idx - 1], rtol=0, atol=1e-6 * tau0) | np.isclose(
            grid, s.t[idx], rtol=0, atol=1e-6 * tau0
        )
        x[(gap > max_gap * tau0) & ~on_sample] = np.nan
        return grid, x, tau0

    # ------------------------------------------------------------------- I/O
    def to_csv(self, path_or_buf) -> None:
        cols = ["unix_time", "offset"] + list(self.extra)
        data = np.column_stack([self.t, self.offset] + [self.extra[k] for k in self.extra])
        header = ",".join(cols)
        if hasattr(path_or_buf, "write"):
            np.savetxt(path_or_buf, data, delimiter=",", header=header, comments="", fmt="%.12g")
        else:
            with open(path_or_buf, "w", encoding="utf-8") as fh:
                np.savetxt(fh, data, delimiter=",", header=header, comments="", fmt="%.12g")
