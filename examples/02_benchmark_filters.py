#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Evaluate clock-offset estimators against simulated ground truth.

Shows how ntpstats can be used as a test bench for synchronisation
algorithms: define a clock and a network, generate exchanges, run the
estimators, score them. Plug your own estimator in ``ESTIMATORS``.
"""

from ntpstats.analysis import compare, format_seconds
from ntpstats.filters import kalman_series
from ntpstats.network import min_delay_filter
from ntpstats.simulate import ClockModel, PathModel, Scenario, simulate_ntp

ESTIMATORS = {
    "raw": lambda s: s,
    "Kalman": lambda s: kalman_series(s, delay_weighting=False),
    "Kalman+delay": kalman_series,
    "RTS+delay": lambda s: kalman_series(s, smooth=True),
    "min-delay(8)": min_delay_filter,
}

for asym in (0.0, 1e-3, 3e-3):
    sc = Scenario(
        duration=24 * 3600, poll=64, seed=7,
        clock=ClockModel(freq_offset=-8e-6, white_fm_adev1=1e-9, rw_fm_adev1=1e-11),
        forward=PathModel(base=10e-3, queue_mean=1e-3, load=0.5),
        backward=PathModel(base=10e-3, queue_mean=1e-3 + asym, load=0.5),
    )
    meas, truth = simulate_ntp(sc)
    print(f"\nreturn-path extra mean queueing = {format_seconds(asym) if asym else '0'}")
    for name, fn in ESTIMATORS.items():
        c = compare(fn(meas), truth)
        print(f"  {name:14s} rms {format_seconds(c['rms']):>9}  bias {format_seconds(c['bias']):>9}")
