# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Poll-interval advice: the longest interval between measurements that meets an accuracy target.

A client that polls every T seconds runs, between polls, on the phase and
frequency it estimated from the polls so far. Its error just before the next
poll is the time-interval error of a holdover of length T that starts from an
estimate made with measurements T apart. For each candidate interval (the
log's own interval times 1, 2, 4, ...) the log is decimated to that interval
and the holdover model of :mod:`ntpstats.holdover` predicts that error,
including the uncertainty of the fitted frequency and of the noise model.
Decimating makes the fewer measurements of a long interval count against it.

The answer is as good as the log: it should cover the conditions the client
will see (time of day, temperature, network load), and an interval is only
offered when the decimated log still has ``min_samples`` measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .series import TimeSeries


@dataclass
class PollAdvice:
    intervals: np.ndarray  # candidate poll intervals (s)
    error: np.ndarray  # predicted |TIE| bound just before the next poll (s), made non-decreasing in the interval
    mean: np.ndarray  # predicted mean TIE (s)
    sd: np.ndarray  # predicted standard deviation (s)
    samples: np.ndarray  # measurements left after decimation
    ci: float
    model: str
    target: Optional[float] = None
    recommended: Optional[float] = None  # longest interval whose bound meets the target
    h: Dict[int, float] = field(default_factory=dict)  # noise model of the full-rate log
    meta: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"intervals": self.intervals.tolist(), "error": self.error.tolist(), "mean": self.mean.tolist(),
                "sd": self.sd.tolist(), "samples": self.samples.astype(int).tolist(), "ci": self.ci,
                "model": self.model, "target": self.target, "recommended": self.recommended,
                "h": {str(k): v for k, v in self.h.items()}, "meta": self.meta}


def poll_advice(series: TimeSeries, target: Optional[float] = None, ci: float = 0.95, model: str = "frequency",
                min_samples: int = 32, max_interval: Optional[float] = None, uncertainty: int = 20) -> PollAdvice:
    """Predicted error versus poll interval for the clock and path of ``series`` (offsets, reference - local).

    ``target`` (s) selects the longest candidate interval whose ``ci`` bound is within it. ``model`` is what
    the clock applies between polls (``"frequency"`` or ``"drift"``), ``uncertainty`` the bootstrap noise
    models mixed into each prediction.
    """
    from .holdover import phase_from, predict

    _, x, tau0 = phase_from(series, "offset")
    rows: List[tuple] = []
    h0: Dict[int, float] = {}
    m = 1
    while True:
        xd = x[::m]
        n = int(np.isfinite(xd).sum())
        T = tau0 * m
        if n < min_samples or (max_interval is not None and T > max_interval * (1 + 1e-9)):
            break
        r = predict(xd, T, T, model=model, ci=ci, points=8, uncertainty=uncertainty)
        if m == 1:
            h0 = dict(r.h)
        i = int(np.argmin(np.abs(np.asarray(r.t) - T)))
        bound = float(max(abs(r.lo[i]), abs(r.hi[i])))
        rows.append((T, bound, float(r.mean[i]), float(r.sd[i]), n))
        m *= 2
    if not rows:
        raise ValueError(f"the log has fewer than {min_samples} usable measurements")
    a = np.array(rows, dtype=float)
    raw = a[:, 1].copy()
    # Polling less often cannot make the error smaller; where the predictions from the sparser logs say so,
    # it is sampling noise, so the reported bound is the running maximum (conservative).
    a[:, 1] = np.maximum.accumulate(raw)
    rec = None
    if target is not None:
        ok = a[:, 1] <= target
        rec = float(a[ok, 0].max()) if ok.any() else None
    return PollAdvice(intervals=a[:, 0], error=a[:, 1], mean=a[:, 2], sd=a[:, 3], samples=a[:, 4], ci=ci,
                      model=model, target=target, recommended=rec, h=h0,
                      meta={"name": series.name, "tau0": tau0, "error_per_interval": raw.tolist()})


__all__ = ["PollAdvice", "poll_advice"]
