# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Power spectral densities of clock data (IEEE Std 1139, NIST SP 1065 section 6).

One-sided PSDs, in the usual time-and-frequency units:

* ``S_x(f)``: phase (time) fluctuations, s²/Hz;
* ``S_y(f)``: fractional frequency, 1/Hz; ``S_y = (2πf)² S_x``;
* ``L(f)``: single-sideband phase noise of a carrier ``nu0``,
  ``L(f) = S_phi(f)/2 = (2π nu0)² S_x(f) / 2``, usually in dBc/Hz.

Estimation is Welch's method (Hann window, 50 % overlap) or sine multitaper
(Riedel & Sidorenko 1995), on each gap-free stretch of the data; stretches
are combined by weighting with their number of segments. ``S_y`` is taken
from first differences of the phase, which keeps leakage small for the steep
spectra of random-walk FM. Log-spaced frequency bins average the raw
ordinates and carry their degrees of freedom, so they can be used in fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .series import TimeSeries


@dataclass
class Spectrum:
    kind: str  # "x", "y" or "phi" (L(f) is derived from "x")
    f: np.ndarray  # Hz
    psd: np.ndarray
    dof: np.ndarray  # approximate chi-squared degrees of freedom per point
    tau0: float
    meta: Dict[str, object] = field(default_factory=dict)

    def lf_dbc(self, nu0: float) -> np.ndarray:
        """L(f) in dBc/Hz for a carrier ``nu0`` (Hz), from a phase spectrum."""
        if self.kind != "x":
            raise ValueError("L(f) needs the phase spectrum (kind='x')")
        return 10 * np.log10((2 * np.pi * nu0) ** 2 * self.psd / 2)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "f": self.f.tolist(), "psd": self.psd.tolist(), "dof": self.dof.tolist(),
                "tau0": self.tau0, "meta": self.meta}


def _runs(ok: np.ndarray) -> List[tuple]:
    """(start, end) of runs of True."""
    d = np.diff(np.concatenate(([0], ok.astype(int), [0])))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def _sine_tapers(n: int, k: int) -> np.ndarray:
    j = np.arange(1, k + 1)[:, None]
    i = np.arange(1, n + 1)[None, :]
    return np.sqrt(2.0 / (n + 1)) * np.sin(np.pi * j * i / (n + 1))


def _segment_psd(seg: np.ndarray, tau0: float, method: str, tapers: int):
    """One-sided PSD of one segment (mean removed) and its degrees of freedom."""
    seg = seg - seg.mean()
    n = seg.size
    if method == "multitaper":
        w = _sine_tapers(n, tapers)
        spec = np.abs(np.fft.rfft(w * seg[None, :], axis=1)) ** 2  # tapers have unit energy
        p = spec.mean(axis=0) * tau0
        dof = 2.0 * tapers
    else:
        w = np.hanning(n + 2)[1:-1]
        p = np.abs(np.fft.rfft(w * seg)) ** 2 * tau0 / np.sum(w * w)
        dof = 2.0
    p[1:] *= 2.0
    if n % 2 == 0:
        p[-1] /= 2.0  # Nyquist ordinate is not doubled
    return p, dof


def psd(values: np.ndarray, tau0: float, nperseg: Optional[int] = None, method: str = "welch",
        tapers: int = 5, min_run: Optional[int] = None) -> Spectrum:
    """PSD of an evenly sampled sequence with NaN gaps (units²/Hz).

    ``nperseg`` defaults to the longest power of two that gives at least
    eight segments in the longest stretch (Welch) or the whole stretch
    (multitaper). Stretches shorter than ``nperseg`` are skipped.
    """
    v = np.asarray(values, dtype=float)
    runs = [(a, b) for a, b in _runs(np.isfinite(v)) if b - a >= (min_run or 16)]
    if not runs:
        raise ValueError("no gap-free stretch long enough for a spectrum")
    longest = max(b - a for a, b in runs)
    if nperseg is None:
        nperseg = longest if method == "multitaper" else max(16, 1 << int(np.log2(max(16, longest // 4))))
    nperseg = int(min(nperseg, longest))
    step = nperseg if method == "multitaper" else nperseg // 2
    acc, segs, dof_per = None, 0, 2.0
    for a, b in runs:
        for s in range(a, b - nperseg + 1, step):
            p, dof_per = _segment_psd(v[s: s + nperseg], tau0, method, tapers)
            acc = p if acc is None else acc + p
            segs += 1
    if acc is None:
        raise ValueError("no gap-free stretch long enough for a spectrum")
    f = np.fft.rfftfreq(nperseg, tau0)
    # Welch with 50 % Hann overlap: each extra segment adds ~0.95 of a segment's dof.
    eff = 1 + (segs - 1) * (0.95 if method == "welch" else 1.0)
    dof = np.full(f.size, dof_per * eff)
    return Spectrum("", f[1:], acc[1:] / segs, dof[1:], tau0,
                    {"method": method, "nperseg": nperseg, "segments": segs, "stretches": len(runs)})


def log_bins(sp: Spectrum, per_decade: int = 10) -> Spectrum:
    """Average ordinates in log-spaced bins; dof adds up. Low bins with one ordinate are kept as is."""
    lf = np.log10(sp.f)
    edges = np.arange(np.floor(lf[0] * per_decade), np.ceil(lf[-1] * per_decade) + 1) / per_decade
    idx = np.clip(np.digitize(lf, edges) - 1, 0, edges.size - 2)
    f, p, d = [], [], []
    for k in np.unique(idx):
        sel = idx == k
        f.append(10 ** np.mean(lf[sel]))
        p.append(np.mean(sp.psd[sel]))
        d.append(np.sum(sp.dof[sel]))
    return Spectrum(sp.kind, np.array(f), np.array(p), np.array(d), sp.tau0, dict(sp.meta, per_decade=per_decade))


def phase_psd(x: np.ndarray, tau0: float, **kw) -> Spectrum:
    """S_x(f) of phase data (s), linear trend (frequency offset) removed per stretch."""
    x = np.asarray(x, dtype=float).copy()
    for a, b in _runs(np.isfinite(x)):
        if b - a > 2:
            k = np.arange(b - a)
            x[a:b] -= np.polyval(np.polyfit(k, x[a:b], 1), k)
    sp = psd(x, tau0, **kw)
    sp.kind = "x"
    return sp


def frequency_psd(x: np.ndarray, tau0: float, **kw) -> Spectrum:
    """S_y(f) from first differences of phase data, y = Δx/τ0."""
    y = np.diff(np.asarray(x, dtype=float)) / tau0
    sp = psd(y, tau0, **kw)
    sp.kind = "y"
    return sp


def series_spectrum(series: TimeSeries, kind: str = "y", tau0: Optional[float] = None, max_gap: float = 3.0,
                    per_decade: Optional[int] = 10, **kw) -> Spectrum:
    """Spectrum of a :class:`TimeSeries` offset (resampled to a uniform grid; gaps stay gaps)."""
    grid, x, tau0 = series.to_uniform(tau0=tau0, max_gap=max_gap)
    sp = phase_psd(x, tau0, **kw) if kind == "x" else frequency_psd(x, tau0, **kw)
    if per_decade:
        sp = log_bins(sp, per_decade)
    sp.meta["name"] = series.name
    return sp
