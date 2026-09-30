#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Plug your own synchronisation algorithm into the ntpstats test bench.

Register an Estimator and benchmark it against the built-in reference
algorithms on simulated scenarios with ground truth. To ship it as a
package instead, expose it through the entry point group
``ntpstats.estimators`` in your pyproject.toml:

    [project.entry-points."ntpstats.estimators"]
    ewma = "my_package.module:EWMA"
"""

import os

import numpy as np

from ntpstats.bench import load_scenarios, run_bench, summarize
from ntpstats.estimators import Estimator, register
from ntpstats.series import TimeSeries


class EWMA(Estimator):
    """Exponentially weighted moving average of low-delay samples (toy example)."""

    name = "ewma"
    description = "EWMA of samples within 2x the floor delay"

    def __init__(self, alpha=0.2):
        self.alpha = alpha

    def fit(self, s: TimeSeries) -> TimeSeries:
        d = s.extra["delay"]
        good = d <= 2 * d.min()
        out, est = [], s.offset[0]
        for x, g in zip(s.offset, good):
            if g:
                est = (1 - self.alpha) * est + self.alpha * x
            out.append(est)
        return TimeSeries(s.t, np.array(out), name=f"{s.name} (ewma)")


register(EWMA())
here = os.path.dirname(__file__)
scen = load_scenarios(["internet", os.path.join(here, "scenarios", "wan-route-change.toml")])
rows = run_bench(scen, ["raw", "ewma", "mindelay", "kalman-dw", "regression"], seeds=range(1, 4), duration=43200)
for r in summarize(rows):
    print(f"{r['scenario']:18} {r['estimator']:11} rms {r['rms'] * 1e6:8.1f} us  bias {r['bias'] * 1e6:8.1f} us")
