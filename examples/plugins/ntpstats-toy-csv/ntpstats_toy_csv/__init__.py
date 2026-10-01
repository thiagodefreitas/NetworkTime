# SPDX-License-Identifier: MIT
"""Example ntpstats plugin (template for your own).

The "toy CSV" format: a ``#TOYCSV 1`` first line, then ``epoch_ms;offset_us``
rows where the offset is local - reference (so it is negated).
"""

import numpy as np

from ntpstats.events import Event
from ntpstats.plugins import DetectorPlugin, ParserPlugin
from ntpstats.series import TimeSeries

# 64 readings, 16 s apart: a slow wander plus deterministic pseudo-random jitter (offsets in us)
EXAMPLE = "#TOYCSV 1\n" + "".join(f"{1_790_000_000_000 + 16000 * i};{8 * np.sin(i / 9) + 5 * ((i * 7919) % 13 - 6) / 6:.3f}\n"
                                  for i in range(64))


def detect(lines):
    return 1.0 if lines and lines[0].startswith("#TOYCSV") else 0.0


def parse(lines, name="toycsv"):
    t, x = [], []
    for ln in lines[1:]:
        if ln.strip() and not ln.startswith("#"):
            ms, us = ln.split(";")
            t.append(int(ms) / 1000.0)
            x.append(-float(us) * 1e-6)  # local - reference -> reference - local
    return [TimeSeries(np.array(t), np.array(x), name=name, source_format="toycsv").sorted()]


def big_offsets(series, limit=1e-3):
    return [Event(float(t), "toy_big_offset", float(x), "s", 1.0) for t, x in zip(series.t, series.offset)
            if abs(x) > limit]


def _example_series():
    t = 1.79e9 + 16 * np.arange(100.0)
    x = np.zeros(100)
    x[50] = 5e-3
    return TimeSeries(t, x, name="example")


PARSER = ParserPlugin("toycsv", parse, detect, "Toy CSV dialect (example plugin)", EXAMPLE)
DETECTOR = DetectorPlugin("toy-big-offset", big_offsets, "offsets above 1 ms (example plugin)", _example_series)
MASK = "tau,tdev\n1,1e-6\n100,1e-5\n10000,1e-4\n"
PROFILE = {"description": "toy counter: one reading per line in us", "value_column": 0, "units": "us",
           "quantity": "te", "tau0": 1.0}
