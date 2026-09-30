#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Load a log, print a summary and the stability table (pure numpy, no plotting)."""

import os

from ntpstats import load_one
from ntpstats.analysis import format_seconds, summary
from ntpstats.stability import NOISE_NAMES, series_stability

path = os.path.join(os.path.dirname(__file__), "data", "chrony-measurements.log")
s = load_one(path, peer="198.51.100.7")  # any supported format; auto-detected

info = summary(s)
print(f"{s.name}: {info['samples']} samples over {info['span_s'] / 3600:.1f} h")
print(f"offset mean {format_seconds(info['mean'])}, rms {format_seconds(info['rms'])}, "
      f"90% range {format_seconds(info['range_90'])}")

for r in series_stability(s, kinds=("oadev", "tdev"), ci=0.95):
    print(f"\n{r.kind.upper()}  (95% CI)")
    for tau, dev, lo, hi, a in zip(r.taus, r.dev, r.lo, r.hi, r.alpha):
        print(f"  tau={tau:8.0f} s  {dev:.3e}  [{lo:.3e}, {hi:.3e}]  {NOISE_NAMES[int(a)]}")
