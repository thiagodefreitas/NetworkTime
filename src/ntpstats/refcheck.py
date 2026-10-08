# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Check a disciplined clock, its daemon's claims and every estimator against an independent reference.

The validation campaign of ``docs/validation-campaign.md``: a host is
disciplined over the network (chrony, ntpd, ...) while a reference it does
not use, typically a GNSS receiver's PPS logged by chrony as a ``noselect``
refclock, records the true error of its clock. :func:`validate` then answers
four questions from the logs:

1. **How good is the clock?** Error statistics, TDEV and MTIE of the
   reference series, which *is* the clock's error (reference - local). For
   chrony's ``refclocks.log`` the *raw* column is used: chrony's
   ``refclock.c`` logs there the pulse against the system clock as
   applications read it, while the cooked column also subtracts the
   correction chrony is still slewing out (and adds the refclock's
   ``offset`` option). ``reference_column="cooked"`` selects the latter.
2. **Is the daemon's error bound honest?** chrony.conf(5) defines the
   ``Max. error`` of ``tracking.log`` as "the maximum estimated error of the
   system clock in the interval since the previous update", so every
   reference sample between two updates must lie within the later update's
   value. Logs of chrony versions without that column are checked at the
   update times against root delay / 2 + root dispersion, which omits the
   offset being corrected and is marked approximate. Also reported: how well
   the daemon knew its own offset at each update.
3. **Is every server inside its correctness interval?** For each NTP
   measurement, ``theta - x`` (server error plus path asymmetry) must lie
   within the root distance ``(delay + root delay) / 2 + dispersion + root
   dispersion``, the correctness interval of RFC 5905 section 11.2.1 with
   the root distance of its appendix A.5.5.2 less the peer jitter term (a
   statistical allowance for a filtered sample, not part of one exchange's
   bound): a correct server cannot be farther away, whatever the asymmetry.
   Violations identify falsetickers.
4. **Which estimator is best on real data?** Every bench estimator runs on
   the measured exchanges of each server (multi-server ones on all servers)
   and is scored against the reference, the comparison that simulation
   alone cannot make.

The reference's own uncertainty (``ref_uncertainty``, default 1 us for a
timing receiver's PPS with kernel time stamps) is added to every bound.
:func:`synthetic_campaign` writes logs with a known truth for tests and
for trying the command.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .series import TimeSeries

#: estimators run by default: single-server ones per server, multi-server ones on all of them
DEFAULT_ESTIMATORS = ("raw", "mindelay", "kalman-dw", "regression", "hull", "ntpd", "median", "rfc5905",
                      "kalman-combine")


@dataclass
class ValidationReport:
    """Result of :func:`validate`; ``as_dict()`` for JSON."""

    reference: str
    samples: int
    span: float
    clock: Dict[str, Any]
    bound: Optional[Dict[str, Any]] = None
    servers: List[Dict[str, Any]] = field(default_factory=list)
    estimators: List[Dict[str, Any]] = field(default_factory=list)
    max_violation_rate: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """The daemon's bound held (within ``max_violation_rate``); servers are reported, not judged."""
        return self.bound is None or self.bound["violation_rate"] <= self.max_violation_rate

    def as_dict(self) -> Dict[str, Any]:
        return {"reference": self.reference, "samples": self.samples, "span_s": self.span, "clock": self.clock,
                "bound": self.bound, "servers": self.servers, "estimators": self.estimators,
                "passed": self.passed, "max_violation_rate": self.max_violation_rate, "meta": self.meta}


def truth_at(reference: TimeSeries, t: np.ndarray, max_gap: float = 4.0) -> np.ndarray:
    """The reference interpolated at ``t``; NaN where the neighbouring reference samples are farther apart
    than ``max_gap`` seconds or ``t`` is outside the reference."""
    r = reference.sorted()
    t = np.asarray(t, dtype=float)
    out = np.full(t.shape, np.nan)
    if len(r) < 2:
        return out
    j = np.searchsorted(r.t, t, side="right")
    jl, jr = np.clip(j - 1, 0, len(r) - 1), np.clip(j, 0, len(r) - 1)
    gap = np.where(r.t[jl] == t, 0.0, r.t[jr] - r.t[jl])
    ok = (t >= r.t[0]) & (t <= r.t[-1]) & (gap <= max_gap)
    out[ok] = np.interp(t[ok], r.t, r.offset)
    return out


def _stats(err: np.ndarray) -> Dict[str, float]:
    e = err[np.isfinite(err)]
    if e.size == 0:
        return {"samples": 0}
    return {"samples": int(e.size), "bias": float(np.mean(e)), "rms": float(np.sqrt(np.mean(e ** 2))),
            "std": float(np.std(e)), "p95_abs": float(np.percentile(np.abs(e), 95)),
            "max_abs": float(np.max(np.abs(e)))}


def _clock(reference: TimeSeries, t0: float) -> Dict[str, Any]:
    from .stability import compute

    r = reference.sorted().between(t0, math.inf)
    out: Dict[str, Any] = _stats(r.offset)
    if len(r) >= 8:
        _, x, tau0 = r.to_uniform()
        for kind in ("tdev", "mtie"):
            res = compute(x, tau0, kind, "octave", ci=None)
            out[kind] = {f"{tau:g}": float(v) for tau, v in zip(res.taus, res.dev) if np.isfinite(v)}
    return out


def _tracking_bound(tracking: TimeSeries, reference: TimeSeries, t0: float, max_gap: float,
                    ref_uncertainty: float) -> Optional[Dict[str, Any]]:
    tr = tracking.sorted()
    ex = tr.extra
    x_upd = truth_at(reference, tr.t, max_gap)
    keep = tr.t >= t0
    self_est = _stats((tr.offset - x_upd)[keep])
    if "max_error" in ex:
        # chrony.conf(5): the bound holds over the interval since the previous update
        bound = np.asarray(ex["max_error"], dtype=float)
        r = reference.sorted().between(t0, math.inf)
        k = np.searchsorted(tr.t, r.t, side="left")  # the first update at or after each sample
        ok = (k >= 1) & (k < len(tr))
        k = k[ok]
        x, b, times = r.offset[ok], bound[k] + ref_uncertainty, r.t[ok]
        ok2 = np.isfinite(x) & np.isfinite(b)
        x, b, times, k = x[ok2], b[ok2], times[ok2], k[ok2]
        source, unit, approximate = "max error over each update interval (tracking.log)", "samples", False
    elif "root_delay" in ex and "root_dispersion" in ex:
        bound = np.asarray(ex["root_delay"], dtype=float) / 2 + np.asarray(ex["root_dispersion"], dtype=float)
        ok = keep & np.isfinite(x_upd) & np.isfinite(bound)
        x, b, times, k = x_upd[ok], bound[ok] + ref_uncertainty, tr.t[ok], np.flatnonzero(ok)
        source, unit, approximate = "root delay / 2 + root dispersion at the updates (tracking.log)", "updates", True
    else:
        return None
    if x.size == 0:
        return None
    viol = np.abs(x) > b
    ratio = np.abs(x) / np.where(b > 0, b, np.nan)
    return {"source": source, "approximate": approximate, "checked": int(x.size), "unit": unit,
            "updates": int(np.unique(k).size), "violations": int(viol.sum()),
            "violated_updates": int(np.unique(k[viol]).size), "violation_rate": float(viol.mean()),
            "worst_ratio": float(np.nanmax(ratio)), "median_bound": float(np.median(b)),
            "median_abs_error": float(np.median(np.abs(x))),
            "violation_times": [float(v) for v in times[viol][:20]], "self_estimate": self_est}


def _server(s: TimeSeries, reference: TimeSeries, t0: float, max_gap: float,
            ref_uncertainty: float) -> Dict[str, Any]:
    s = s.sorted().between(t0, math.inf)
    x = truth_at(reference, s.t, max_gap)
    ex = s.extra

    def col(name):
        return np.asarray(ex.get(name, np.zeros(len(s))), dtype=float)

    lam = (col("delay") + col("root_delay")) / 2 + col("dispersion") + col("root_dispersion") + ref_uncertainty
    err = s.offset - x
    ok = np.isfinite(err) & np.isfinite(lam)
    row: Dict[str, Any] = {"peer": s.meta.get("peer", s.name), **_stats(err[ok])}
    if ok.any():
        viol = np.abs(err[ok]) > lam[ok]
        row.update(within_bound=float(1 - viol.mean()), violations=int(viol.sum()),
                   worst_ratio=float(np.max(np.abs(err[ok]) / np.where(lam[ok] > 0, lam[ok], np.nan))),
                   median_delay=float(np.median(col("delay")[ok])), median_root_distance=float(np.median(lam[ok])))
    return row


def validate(reference: TimeSeries, tracking: Optional[TimeSeries] = None,
             measurements: Optional[Sequence[TimeSeries]] = None,
             estimators: Optional[Sequence[str]] = DEFAULT_ESTIMATORS, ref_uncertainty: float = 1e-6,
             max_gap: float = 4.0, warmup: float = 0.0, max_violation_rate: float = 0.0,
             min_samples: int = 16, reference_column: str = "raw") -> ValidationReport:
    """Score a clock, its daemon's bound, its servers and the estimators against ``reference``.

    ``reference`` is the true error of the clock, reference - local (chrony's
    ``refclocks.log`` cooked offset of a ``noselect`` PPS refclock, or any
    series in that convention). ``tracking`` is the daemon's own record
    (chrony ``tracking.log``), ``measurements`` the per-server exchanges
    (chrony ``measurements.log``, ntpd ``peerstats``, a capture). The first
    ``warmup`` seconds of the reference are excluded everywhere. With
    ``reference_column="raw"`` (default) a reference carrying chrony's raw
    refclock error (``extra["raw_error"]``) is read from that column.
    """
    if reference_column not in ("raw", "cooked"):
        raise ValueError("reference_column must be 'raw' or 'cooked'")
    ref = reference.sorted()
    if reference_column == "raw" and "raw_error" in ref.extra:
        raw = np.asarray(ref.extra["raw_error"], dtype=float)
        ok = np.isfinite(raw)
        ref = TimeSeries(ref.t[ok], raw[ok], name=ref.name, meta={**ref.meta, "reference_column": "raw"})
    if len(ref) < 2:
        raise ValueError("the reference needs at least two samples")
    t0 = float(ref.t[0]) + float(warmup)
    report = ValidationReport(reference=ref.name, samples=int(np.sum(ref.t >= t0)),
                              span=float(ref.t[-1] - t0), clock=_clock(ref, t0),
                              max_violation_rate=float(max_violation_rate),
                              meta={"ref_uncertainty": ref_uncertainty, "max_gap": max_gap, "warmup": warmup,
                                    "reference_column": ref.meta.get("reference_column", "offset")})
    if tracking is not None and len(tracking):
        report.bound = _tracking_bound(tracking, ref, t0, max_gap, ref_uncertainty)
    meas = [m for m in (measurements or []) if len(m) >= min_samples]
    report.servers = [_server(m, ref, t0, max_gap, ref_uncertainty) for m in meas]
    if meas and estimators:
        from . import estimators as est_mod

        for name in estimators:
            e = est_mod.get(name)
            groups = [meas] if e.multi else [[m] for m in meas]
            if e.multi and len(meas) < 2:
                continue
            for g in groups:
                peer = "all" if e.multi else str(g[0].meta.get("peer", g[0].name))
                try:
                    out = est_mod.run(e, g).sorted().between(t0, math.inf)
                    row = {"estimator": name, "peer": peer,
                           **_stats(out.offset - truth_at(ref, out.t, max_gap))}
                except Exception as exc:  # a failing estimator must not abort the validation
                    row = {"estimator": name, "peer": peer, "samples": 0, "error": f"{type(exc).__name__}: {exc}"}
                report.estimators.append(row)
        report.estimators.sort(key=lambda r: (r.get("rms", math.inf)))
    return report


# ------------------------------------------------------------------ synthetic campaign
def synthetic_campaign(directory: str, hours: float = 6.0, seed: int = 1, poll: float = 64.0,
                       falseticker: bool = True, bound_scale: float = 1.0) -> Dict[str, str]:
    """Write chrony ``tracking.log``, ``measurements.log`` and ``refclocks.log`` with a known truth.

    The clock's true error wanders by tens of microseconds; three servers
    (plus a falseticker 20 ms off with a 10 ms delay, if ``falseticker``)
    are polled every ``poll`` seconds with exponential queueing delays; the
    PPS refclock records the true error every second with 20 ns of noise.
    ``bound_scale`` scales the maximum error written to ``tracking.log``
    (below 1 to make the daemon's bound dishonest). Returns the paths.
    """
    import datetime as _dt

    rng = np.random.default_rng(seed)
    t0 = 1_791_000_000.0
    n = int(hours * 3600)
    t = t0 + np.arange(n, dtype=float)
    # the disciplined clock's true error (reference - local): a smoothed random walk of a few tens of us
    w = np.cumsum(rng.normal(0, 2e-7, n))
    x = 3e-5 * np.sin(2 * np.pi * (t - t0) / 5400.0) + w - np.convolve(w, np.ones(600) / 600, mode="same")

    def ts(v, frac=False):
        d = _dt.datetime.fromtimestamp(v, _dt.timezone.utc)
        return d.strftime("%Y-%m-%d %H:%M:%S") + (".000000" if frac else "")

    os.makedirs(directory, exist_ok=True)
    paths = {k: os.path.join(directory, f) for k, f in
             (("tracking", "tracking.log"), ("measurements", "measurements.log"), ("refclocks", "refclocks.log"))}
    with open(paths["refclocks"], "w") as fh:
        fh.write("=" * 79 + "\n   Date (UTC) Time         Refid  DP L P  Raw offset   Cooked offset      Disp.\n"
                 + "=" * 79 + "\n")
        pending = 2e-6 * np.exp(-((t - t0) % poll) / 20.0)  # correction chrony is still slewing out
        for i in range(n):
            raw = x[i] + rng.normal(0, 2e-8)  # reference - system clock as applications read it
            fh.write(f"{ts(t[i], True)} PPS     {i % 16:2d} N 1 {raw: .6e} {raw - pending[i]: .6e}  1.000e-06\n")
    # servers: (address, stratum, base delay, error + mean asymmetry, root delay, root dispersion)
    servers = [("192.0.2.1", 1, 2e-3, 2e-4, 1e-5, 1e-4), ("192.0.2.2", 2, 3e-2, -2e-3, 8e-3, 5e-4),
               ("198.51.100.3", 2, 9e-2, 6e-3, 2e-2, 1e-3)]
    if falseticker:
        servers.append(("203.0.113.4", 1, 1e-2, 2e-2, 1e-5, 1e-4))
    rows = []
    for k, (addr, st, d0, b, rd, rdisp) in enumerate(servers):
        for tp in np.arange(t0 + 5 + 7 * k, t0 + n - 1, poll):
            i = int(tp - t0)
            q1, q2 = rng.exponential(0.1 * d0), rng.exponential(0.1 * d0)
            delay = d0 + q1 + q2
            theta = x[i] + b + (q2 - q1) / 2  # asymmetric queueing shifts the offset by half the difference
            rows.append((tp, f"{ts(tp)} {addr:15s} N {st:2d} 111 111 1111   6  6 0.00 {theta: .3e} {delay: .3e}  "
                             f"1.200e-06  {rd: .3e}  {rdisp: .3e} C0000201 4B K K"))
    with open(paths["measurements"], "w") as fh:
        fh.write("=" * 120 + "\n   Date (UTC) Time     IP Address   L St 123 567 ABCD  LP RP Score    Offset  "
                 "Peer del. Peer disp.  Root del. Root disp. Refid     MTxRx\n" + "=" * 120 + "\n")
        for _, line in sorted(rows):
            fh.write(line + "\n")
    with open(paths["tracking"], "w") as fh:
        fh.write("=" * 127 + "\n   Date (UTC) Time     IP Address   St   Freq ppm   Skew ppm     Offset L Co  "
                 "Offset sd Rem. corr. Root delay Root disp. Max. error\n" + "=" * 127 + "\n")
        rd, rdisp = 2e-3, 3.5e-4
        for tp in np.arange(t0 + 30, t0 + n - 1, poll):
            i = int(tp - t0)
            est = x[i] + rng.normal(0, 5e-6)  # chrony's estimate of reference - local
            maxerr = (rd / 2 + rdisp) * bound_scale
            fh.write(f"{ts(tp)} 192.0.2.1        2 {-3.5: 10.3f} {0.05: 10.3f} {-est: .3e} N  3  {5e-6: .3e} "
                     f"{0.0: .3e}  {rd: .3e}  {rdisp: .3e}  {maxerr: .3e}\n")
    return paths
