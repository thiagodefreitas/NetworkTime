# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Time-error metrics for packet timing (ITU-T G.8260 definitions, G.8273.2 usage).

Time error is ``TE(t) = T(t) - T_ref(t)``: the clock under test minus the
reference, i.e. **local - reference**. ntpstats series use the opposite
convention (reference - local), so they are negated here unless
``input_is_te=True`` (e.g. a time-interval counter measuring DUT - REF).

Metrics, computed on a uniform grid with gaps left out:

``max_abs_te``
    maximum absolute time error, unfiltered.
``cte``
    constant time error: the mean of TE over the record. ``cte_windows`` are
    the means over consecutive ``cte_window``-second windows (1000 s is the
    usual observation interval), and ``max_abs_cte_window`` is the worst one.
``tel`` / ``max_abs_tel``
    TE low-pass filtered by a first-order filter of bandwidth ``lpf_hz``
    (0.1 Hz by default), and its maximum absolute value (max|TEL|).
``dte_l``
    dynamic low-frequency time error, ``TEL - cTE``, evaluated with MTIE and
    TDEV (``mtie``/``tdev`` results) and as a peak-to-peak value.
``dte_h``
    dynamic high-frequency time error, ``TE - TEL``, peak-to-peak.

The filter is causal, discretised exactly for the sample interval
(``y[n] = y[n-1] + a (x[n] - y[n-1])``, ``a = 1 - exp(-2 pi f tau0)``) and
restarted after each gap; the first :data:`SETTLE` time constants after each
(re)start (8 s at 0.1 Hz) are left out of the filtered metrics. It needs samples faster than the filter
bandwidth: at ``tau0`` above ``1 / (2 lpf_hz)`` it cannot separate dTE_L and
dTE_H, which the result reports in ``warnings``.

Limits are **user supplied** (no standards text is bundled): a file of
``metric,value`` lines, see :func:`load_limits`, plus optional MTIE/TDEV masks
for dTE_L (:mod:`ntpstats.masks`).
"""

from __future__ import annotations

import io
import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from .series import TimeSeries
from .stability import StabilityResult, compute

LIMIT_METRICS = {
    "max_te": "max|TE|",
    "cte": "|cTE| (whole record)",
    "cte_window": "max |cTE| over cte_window windows",
    "max_tel": "max|TEL|",
    "dte_l_pp": "dTE_L peak-to-peak",
    "dte_h_pp": "dTE_H peak-to-peak",
}
#: Filter settling excluded after the start and after each gap, in time constants.
SETTLE = 5.0
_UNITS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9, "ps": 1e-12}


@dataclass
class TimeErrorResult:
    tau0: float
    t: np.ndarray
    te: np.ndarray
    tel: np.ndarray
    max_abs_te: float
    cte: float
    cte_window: float
    cte_windows: np.ndarray  # (k, 2): window start time, mean TE
    max_abs_cte_window: float
    max_abs_tel: float
    dte_l_pp: float
    dte_h_pp: float
    mtie: Optional[StabilityResult]
    tdev: Optional[StabilityResult]
    lpf_hz: float
    n: int
    warnings: List[str] = field(default_factory=list)

    def metrics(self) -> Dict[str, float]:
        return {"max_te": self.max_abs_te, "cte": abs(self.cte), "cte_window": self.max_abs_cte_window,
                "max_tel": self.max_abs_tel, "dte_l_pp": self.dte_l_pp, "dte_h_pp": self.dte_h_pp}

    def as_dict(self) -> dict:
        def f(v):
            return None if v is None or not math.isfinite(v) else float(v)

        return {
            "tau0": self.tau0, "samples": self.n, "lpf_hz": self.lpf_hz, "cte_window_s": self.cte_window,
            "max_abs_te": f(self.max_abs_te), "cte": f(self.cte), "max_abs_cte_window": f(self.max_abs_cte_window),
            "max_abs_tel": f(self.max_abs_tel), "dte_l_pp": f(self.dte_l_pp), "dte_h_pp": f(self.dte_h_pp),
            "cte_windows": [[f(a), f(b)] for a, b in self.cte_windows],
            "dte_l_mtie": None if self.mtie is None else self.mtie.as_dict(),
            "dte_l_tdev": None if self.tdev is None else self.tdev.as_dict(),
            "warnings": self.warnings,
        }


def lowpass(x: np.ndarray, tau0: float, hz: float, settle: float = 0.0) -> np.ndarray:
    """First-order low-pass of ``x`` (NaN = gap; the filter restarts after gaps).

    The first ``settle`` time constants after every (re)start are returned as
    NaN, so start-up transients do not count as time error.
    """
    a = 1.0 - math.exp(-2.0 * math.pi * hz * tau0)
    skip = int(math.ceil(settle / (2.0 * math.pi * hz * tau0))) if settle else 0
    y = np.full_like(x, np.nan, dtype=float)
    prev = np.nan
    since = 0
    for i, v in enumerate(x):
        if not np.isfinite(v):
            prev = np.nan
            continue
        if np.isfinite(prev):
            prev = prev + a * (v - prev)
            since += 1
        else:
            prev, since = v, 0
        if since >= skip:
            y[i] = prev
    return y


def _pp(v: np.ndarray) -> float:
    v = v[np.isfinite(v)]
    return float(v.max() - v.min()) if v.size else float("nan")


def time_error(
    series: TimeSeries,
    tau0: Optional[float] = None,
    lpf_hz: float = 0.1,
    cte_window: float = 1000.0,
    input_is_te: bool = False,
    max_gap: float = 3.0,
    taus="octave",
) -> TimeErrorResult:
    """Compute the time-error metrics of ``series`` (see the module docstring)."""
    t, x, tau0 = series.to_uniform(tau0=tau0, max_gap=max_gap)
    te = np.asarray(x, dtype=float) if input_is_te else -np.asarray(x, dtype=float)
    ok = np.isfinite(te)
    if ok.sum() < 3:
        raise ValueError("need at least 3 samples")
    warnings = []
    separable = tau0 <= 1.0 / (2.0 * lpf_hz)
    if not separable:
        warnings.append(f"sample interval {tau0:g} s is too long for a {lpf_hz:g} Hz filter: "
                        "dTE_L/dTE_H cannot be separated (sample at 1 Hz or faster)")
    cte = float(np.mean(te[ok]))
    per = max(1, int(round(cte_window / tau0)))
    wins = []
    for i in range(0, te.size - per + 1, per):
        seg = te[i: i + per]
        if np.isfinite(seg).sum() >= 0.9 * per:
            wins.append((t[i], float(np.nanmean(seg))))
    if not wins:
        warnings.append(f"record shorter than one {cte_window:g} s cTE window; cTE is the whole-record mean")
    cw = np.array(wins, dtype=float).reshape(-1, 2)
    tel = lowpass(te, tau0, lpf_hz, settle=SETTLE)
    dte_l = tel - cte
    dte_h = te - tel
    mt = td = None
    if np.isfinite(dte_l).sum() >= 4:
        mt = compute(dte_l, tau0, "mtie", taus)
        td = compute(dte_l, tau0, "tdev", taus, ci=0.683)
    return TimeErrorResult(
        tau0=float(tau0), t=t, te=te, tel=tel, max_abs_te=float(np.max(np.abs(te[ok]))), cte=cte,
        cte_window=float(cte_window), cte_windows=cw,
        max_abs_cte_window=float(np.max(np.abs(cw[:, 1]))) if len(cw) else abs(cte),
        max_abs_tel=float(np.nanmax(np.abs(tel))), dte_l_pp=_pp(dte_l),
        dte_h_pp=_pp(dte_h) if separable else float("nan"),  # below Nyquist the high-pass part is numerical noise
        mtie=mt, tdev=td, lpf_hz=float(lpf_hz), n=int(ok.sum()), warnings=warnings,
    )


# ------------------------------------------------------------------ limits
def _value(tok: str) -> float:
    m = re.fullmatch(r"\s*([-+0-9.eE]+)\s*([a-zµ]*)\s*", tok)
    if not m:
        raise ValueError(f"bad limit value {tok!r}")
    unit = m.group(2) or "s"
    if unit not in _UNITS:
        raise ValueError(f"unknown unit {unit!r} (use s, ms, us, ns or ps)")
    return float(m.group(1)) * _UNITS[unit]


def load_limits(source) -> Dict[str, float]:
    """Scalar limits from ``metric,value`` lines (path, file object or text).

    Metrics: ``max_te``, ``cte``, ``cte_window``, ``max_tel``, ``dte_l_pp``,
    ``dte_h_pp``. Values are seconds unless suffixed (``30ns``, ``1.1us``).
    ``#`` starts a comment. Example (user-chosen numbers)::

        max_te, 30ns
        cte_window, 10ns
    """
    if hasattr(source, "read"):
        text = source.read()
    elif isinstance(source, (str, os.PathLike)) and os.path.isfile(source):
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = str(source)
    out: Dict[str, float] = {}
    for line in io.StringIO(text):
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        parts = [p.strip() for p in re.split(r"[,;\t ]+", s, maxsplit=1)]
        if len(parts) != 2 or parts[0].lower() in ("metric", "name"):
            continue
        key = parts[0].lower()
        if key not in LIMIT_METRICS:
            raise ValueError(f"unknown time-error metric {parts[0]!r}; choose from {', '.join(LIMIT_METRICS)}")
        out[key] = _value(parts[1])
    if not out:
        raise ValueError("no limits found")
    return out


def check(result: TimeErrorResult, limits: Optional[Dict[str, float]] = None,
          masks: Sequence = ()) -> Dict[str, object]:
    """Compare a result with scalar limits and MTIE/TDEV masks (for dTE_L).

    Returns ``{"passed": bool | None, "checks": [...]}``; ``passed`` is None
    when nothing could be checked.
    """
    from .masks import check as mask_check

    rows = []
    values = result.metrics()
    for key, lim in (limits or {}).items():
        v = values[key]
        if not np.isfinite(v):  # e.g. dTE_H when the sampling cannot separate it: not checked, not passed
            rows.append({"metric": key, "label": LIMIT_METRICS[key], "value": v, "limit": lim, "passed": None,
                         "note": "not measurable from this record (see warnings)"})
            continue
        rows.append({"metric": key, "label": LIMIT_METRICS[key], "value": v, "limit": lim,
                     "passed": bool(v <= lim), "margin": lim - v})
    for mk in masks:
        res = {"mtie": result.mtie, "tdev": result.tdev}.get(mk.kind)
        if res is None:
            rows.append({"metric": f"dte_l_{mk.kind}", "label": f"dTE_L {mk.kind.upper()} ({mk.name})",
                         "passed": None, "note": "only MTIE and TDEV masks apply to dTE_L"})
            continue
        c = mask_check(res, mk)
        rows.append({"metric": f"dte_l_{mk.kind}", "label": f"dTE_L {mk.kind.upper()} ({mk.name})",
                     "passed": c["passed"], "worst_margin": c.get("worst_margin"), "detail": c})
    judged = [r["passed"] for r in rows if r["passed"] is not None]
    return {"passed": (all(judged) if judged else None), "checks": rows}
