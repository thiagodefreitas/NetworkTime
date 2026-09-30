# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Timing assertions for test suites (pytest plugin).

For teams building NICs, switches, firmware or time daemons: turn a timing
requirement into a regression test::

    from ntpstats.testing import assert_max_te, assert_stability_within

    def test_boundary_clock_te(tmp_path):
        log = run_my_bench(tmp_path)                       # produces a capture or a log
        assert_max_te(log, 30e-9)
        assert_stability_within(log, "masks/tdev.csv")

Every helper takes a path (any format ntpstats reads) or a
:class:`~ntpstats.series.TimeSeries`, and raises ``AssertionError`` with the
failing values. With ntpstats installed, pytest also gets the
``timing_log`` fixture (a loader function).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .series import TimeSeries

Source = Union[str, TimeSeries]


def load_series(source: Source, fmt: str = "auto", peer: Optional[str] = None, **kw) -> TimeSeries:
    if isinstance(source, TimeSeries):
        return source
    from .parsers import load_one

    return load_one(source, fmt=fmt, peer=peer, **kw)


def assert_stability_within(source: Source, mask, kind: Optional[str] = None, **kw) -> None:
    """Statistic (from the mask header, or ``kind``) stays under the mask at every tau it covers."""
    from .masks import Mask, check, load_mask
    from .stability import series_stability

    m = mask if isinstance(mask, Mask) else load_mask(mask, kind=kind)
    s = load_series(source, **kw)
    (r,) = series_stability(s, kinds=(m.kind,))
    c = check(r, m)
    if c["passed"] is None:
        raise AssertionError(f"mask {m.name} does not overlap the computed taus of {s.name}")
    if not c["passed"]:
        bad = [(float(t), float(v), lim) for t, v, lim, g in zip(r.taus, r.dev, c["limit"], c["margin"])
               if g is not None and g < 1]
        raise AssertionError(f"{s.name}: {m.kind.upper()} above mask {m.name} at tau/value/limit {bad}")


def assert_max_te(source: Source, limit: float, input_is_te: bool = False, **kw) -> None:
    """max|TE| (local - reference) stays within ``limit`` seconds."""
    from .timeerror import time_error

    s = load_series(source, **kw)
    r = time_error(s, input_is_te=input_is_te)
    if not r.max_abs_te <= limit:
        raise AssertionError(f"{s.name}: max|TE| {r.max_abs_te:.3e} s > {limit:.3e} s")


def assert_time_error_within(source: Source, limits: Union[str, Dict[str, float]], masks: Sequence = (),
                             input_is_te: bool = False, **kw) -> None:
    """All time-error limits (dict or limits file) and dTE_L MTIE/TDEV masks pass."""
    from .masks import Mask, load_mask
    from .timeerror import check, load_limits, time_error

    lim = load_limits(limits) if isinstance(limits, str) else dict(limits)
    mks = [m if isinstance(m, Mask) else load_mask(m) for m in masks]
    s = load_series(source, **kw)
    c = check(time_error(s, input_is_te=input_is_te), lim, mks)
    rows: List[Dict[str, Any]] = list(c["checks"])  # type: ignore[call-overload]
    failed = [row for row in rows if row["passed"] is False]
    if failed:
        raise AssertionError(f"{s.name}: " + "; ".join(
            f"{row['label']} {row.get('value', '')} > {row.get('limit', '')}" for row in failed))


def assert_audit_passes(source: Source, limit: float, **cfg) -> None:
    """The UTC traceability audit passes (bound within ``limit`` and enough coverage)."""
    from .audit import AuditConfig, audit

    s = load_series(source)
    r = audit(s, AuditConfig(limit=limit, **cfg))
    if not r["summary"]["passed"]:
        sm = r["summary"]
        raise AssertionError(f"{s.name}: audit failed: max bound {sm['max_bound']:.3e} s, coverage "
                             f"{sm['coverage']:.1%}, {sm['failing_windows']} failing windows")


def assert_bounds_valid(bounds: Source, reference: Source, max_violation_rate: float = 0.0, **kw) -> None:
    """Clock-error windows contain the reference's true time (violation rate within the allowance)."""
    from .bounds import validate

    b = bounds if isinstance(bounds, TimeSeries) else load_series(bounds, fmt="bounds")
    r = validate(b, load_series(reference), **kw)
    if not r["compared"]:
        raise AssertionError("bounds and reference do not overlap")
    if float(r["violation_rate"]) > max_violation_rate:  # type: ignore[arg-type]
        raise AssertionError(f"{r['violations']} of {r['compared']} windows violated "
                             f"(rate {r['violation_rate']:.3%}), worst excess {r['worst_excess']:.3e} s")


def assert_no_events(source: Source, kinds: Iterable[str] = ("phase_step", "frequency_change",
                                                               "delay_floor_change"), **kw) -> None:
    """No steps, frequency changes or route changes (or the given ``kinds``) in the log."""
    from .events import detect

    s = load_series(source)
    ev = [e for e in detect(s, **kw) if e.kind in set(kinds)]
    if ev:
        raise AssertionError(f"{s.name}: {len(ev)} events: " + ", ".join(f"{e.kind} at {e.time:.0f}" for e in ev[:10]))


try:  # pytest plugin part (optional)
    import pytest

    @pytest.fixture
    def timing_log():
        """Loader for timing logs: ``timing_log(path, fmt="auto", peer=None)`` -> TimeSeries."""
        return load_series
except ImportError:  # pragma: no cover
    pass
