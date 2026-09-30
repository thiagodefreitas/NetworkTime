#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Write a publication-style figure comparing two peers (needs matplotlib)."""

import os
import sys

from ntpstats import load
from ntpstats.plotting import report_figure

path = os.path.join(os.path.dirname(__file__), "data", "peerstats.example")
out = sys.argv[1] if len(sys.argv) > 1 else "peers-report.png"
fig = report_figure(load(path), kinds=("oadev", "tdev"), detrend="linear")
fig.savefig(out, dpi=150)
print("wrote", out)
