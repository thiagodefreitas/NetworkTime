# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Publication-quality static figures (matplotlib is an optional dependency).

Uses the object-oriented API with the Agg canvas only, so it works headless
and never touches a GUI toolkit.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from .analysis import detrend as _detrend
from .series import TimeSeries
from .stability import DESCRIPTIONS, TIME_KINDS, StabilityResult, series_stability


def _mpl():
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("matplotlib is required for static plots: pip install 'ntpstats[plot]'") from exc
    return Figure, FigureCanvasAgg


def _time_axis(ax, t0: float, span: float):
    if span > 3 * 86400:
        ax.set_xlabel("time since start [days]")
        return 86400.0
    if span > 3 * 3600:
        ax.set_xlabel("time since start [hours]")
        return 3600.0
    ax.set_xlabel("time since start [s]")
    return 1.0


def plot_offsets(ax, series: Sequence[TimeSeries], detrend: Optional[str] = None, unit: float = 1e-3):
    t0 = min(s.t[0] for s in series)
    span = max(s.t[-1] for s in series) - t0
    div = _time_axis(ax, t0, span)
    for s in series:
        y = _detrend(s.t, s.offset, detrend) if detrend else s.offset
        ax.plot((s.t - t0) / div, y / unit, lw=0.8, label=s.name)
    ax.set_ylabel("offset%s [ms]" % (f" ({detrend} detrended)" if detrend else ""))
    ax.grid(True, alpha=0.3)
    ax.set_title("Clock offset")


def plot_stability(ax, results: Iterable[StabilityResult], labels: Optional[Sequence[str]] = None, errorbars=True):
    results = list(results)
    for i, r in enumerate(results):
        label = labels[i] if labels else DESCRIPTIONS[r.kind]
        if errorbars and r.kind != "mtie":
            ax.errorbar(r.taus, r.dev, yerr=r.err, fmt="o-", ms=3, lw=1, capsize=2, label=label)
        else:
            ax.plot(r.taus, r.dev, "o-", ms=3, lw=1, label=label)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"averaging time $\tau$ [s]")
    if results and all(r.kind in TIME_KINDS for r in results):
        ax.set_ylabel("[s]")
    elif results and not any(r.kind in TIME_KINDS for r in results):
        ax.set_ylabel(r"$\sigma_y(\tau)$ [fractional frequency]")
    else:
        ax.set_ylabel(r"$\sigma_y(\tau)$ [-]  /  TDEV, MTIE [s]")
    ax.grid(True, which="both", alpha=0.3)
    ax.set_title("Stability")
    ax.legend(fontsize="small")


def plot_histogram(ax, series: Sequence[TimeSeries], detrend: Optional[str] = None, unit: float = 1e-3, bins=60):
    for s in series:
        y = _detrend(s.t, s.offset, detrend) if detrend else s.offset
        ax.hist(y / unit, bins=bins, density=True, histtype="stepfilled", alpha=0.45, label=s.name)
    ax.set_xlabel("offset [ms]")
    ax.set_ylabel("density")
    ax.grid(True, alpha=0.3)
    ax.set_title("Offset distribution")


def plot_extra(ax, series: Sequence[TimeSeries], column: str):
    t0 = min(s.t[0] for s in series)
    span = max(s.t[-1] for s in series) - t0
    div = _time_axis(ax, t0, span)
    for s in series:
        if column in s.extra:
            ax.plot((s.t - t0) / div, s.extra[column], lw=0.8, label=s.name)
    unit = {"delay": " [s]", "jitter": " [s]", "frequency_ppm": "", "wander_ppm": ""}.get(column, "")
    ax.set_ylabel(column + unit)
    ax.grid(True, alpha=0.3)
    ax.set_title(column.replace("_", " "))


def report_figure(
    series: List[TimeSeries],
    kinds: Sequence[str] = ("oadev", "mdev"),
    detrend: Optional[str] = None,
    taus="octave",
):
    """2x2 overview: offset, stability, histogram and an auxiliary column."""
    Figure, FigureCanvasAgg = _mpl()
    fig = Figure(figsize=(12, 8), layout="constrained")
    FigureCanvasAgg(fig)
    axs = fig.subplots(2, 2)
    plot_offsets(axs[0, 0], series, detrend)
    results, labels = [], []
    for s in series:
        for r in series_stability(s, kinds=kinds, taus=taus):
            results.append(r)
            labels.append(f"{s.name}: {r.kind.upper()}" if len(series) > 1 else DESCRIPTIONS[r.kind])
    plot_stability(axs[0, 1], results, labels)
    plot_histogram(axs[1, 0], series, detrend or "linear")
    aux = next((c for c in ("frequency_ppm", "delay", "jitter") if any(c in s.extra for s in series)), None)
    if aux:
        plot_extra(axs[1, 1], series, aux)
    else:
        axs[1, 1].set_axis_off()
    if len(series) > 1:
        axs[0, 0].legend(fontsize="small")
    return fig
