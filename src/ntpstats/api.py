# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""The stable public API of ntpstats, in one flat namespace.

::

    from ntpstats import api as nt

    s = nt.load_one("measurements.log", peer="192.0.2.10")
    for r in nt.series_stability(s, kinds=("oadev", "tdev")):
        print(r.kind, r.taus, r.dev)

Everything listed in ``__all__`` is covered by the deprecation policy
(:mod:`ntpstats.deprecation`): it does not change incompatibly without at
least one minor release of :class:`NtpstatsDeprecationWarning` first. The
surface is frozen in ``tests/data/api_surface.json`` and checked in CI.

Other module-level names keep working but are *provisional*: the protocol
clients (``sntp``, ``nts``, ``roughtime``) follow drafts that still change, and
helpers that are not listed here may move. The objects are the same as in
their home modules, so ``nt.TimeSeries is ntpstats.series.TimeSeries``.
"""

from __future__ import annotations

from .adapters import from_pandas, read_parquet, to_pandas, write_parquet
from .analysis import compare, detrend, format_seconds, remove_outliers, summary
from .audit import AuditConfig, audit
from .bench import load_scenarios, run_bench, score
from .bounds import parse_bounds
from .bounds import validate as validate_bounds
from .deprecation import NtpstatsDeprecationWarning
from .edf import edf
from .estimators import Estimator, FunctionEstimator
from .estimators import available as available_estimators
from .estimators import get as get_estimator
from .estimators import register as register_estimator
from .estimators import run as run_estimator
from .events import Event
from .events import detect as detect_events
from .filters import kalman_series
from .hat import HatResult, hat_series
from .holdover import HoldoverResult, holdover_series
from .masks import Mask, load_mask
from .masks import check as check_mask
from .network import delay_stats, floor_packet_percentage, min_delay_filter, wedge
from .noisefit import NoiseFit
from .noisefit import fit_series as fit_noise
from .parsers import ParseError, all_formats, detect_format, load, load_one
from .plugins import DetectorPlugin, ParserPlugin
from .profiles import load_profile
from .ptpsim import ChainResult, ChainScenario, Link, LinRegServo, PIServo, simulate_chain
from .report import bench_report, dataset_report
from .series import TimeSeries
from .simio import inet_oscillator, read_omnetpp_vec, write_omnetpp_vec
from .simulate import ClockModel, PathEvent, PathModel, Scenario, ServerSpec, simulate_multi, simulate_ntp
from .spectrum import Spectrum, series_spectrum
from .stability import (
    KINDS,
    DynamicResult,
    StabilityResult,
    chi2_interval,
    compute,
    compute_many,
    dynamic,
    identify_noise,
    series_stability,
)
from .stream import iter_chunks, load_large
from .timeerror import TimeErrorResult, time_error
from .timeerror import check as check_time_error
from .trace import DelayTrace, TracePath, load_trace
from .trace import from_series as trace_from_series

__all__ = [
    # data and input
    "TimeSeries", "load", "load_one", "load_large", "iter_chunks", "detect_format", "all_formats",
    "ParseError", "load_profile", "to_pandas", "from_pandas", "read_parquet", "write_parquet",
    # stability
    "KINDS", "compute", "compute_many", "series_stability", "dynamic", "StabilityResult", "DynamicResult",
    "edf", "chi2_interval", "identify_noise",
    # analysis and network
    "summary", "compare", "detrend", "remove_outliers", "format_seconds",
    "delay_stats", "wedge", "floor_packet_percentage", "min_delay_filter",
    # metrology
    "series_spectrum", "Spectrum", "fit_noise", "NoiseFit", "hat_series", "HatResult",
    "holdover_series", "HoldoverResult",
    # time error, masks and assurance
    "time_error", "TimeErrorResult", "check_time_error", "Mask", "load_mask", "check_mask",
    "audit", "AuditConfig", "detect_events", "Event", "parse_bounds", "validate_bounds",
    # estimators, simulation and the bench
    "Estimator", "FunctionEstimator", "register_estimator", "get_estimator", "available_estimators",
    "run_estimator", "kalman_series", "Scenario", "ClockModel", "PathModel", "PathEvent", "ServerSpec",
    "simulate_ntp", "simulate_multi", "load_scenarios", "run_bench", "score",
    # traces, PTP chains and network simulators (2.16-2.17)
    "DelayTrace", "TracePath", "load_trace", "trace_from_series",
    "ChainScenario", "Link", "ChainResult", "simulate_chain", "PIServo", "LinRegServo",
    "read_omnetpp_vec", "write_omnetpp_vec", "inet_oscillator",
    # reports
    "dataset_report", "bench_report",
    # extension points
    "ParserPlugin", "DetectorPlugin", "NtpstatsDeprecationWarning",
]
