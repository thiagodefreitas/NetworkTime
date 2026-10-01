# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Contract tests every ntpstats plugin should pass.

Run them against the plugins installed in the current environment::

    pytest --pyargs ntpstats.testing.plugin_contract

Set ``NTPSTATS_PLUGIN=name`` to check only one plugin. Tests for a kind of
plugin that is not installed are skipped.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from ntpstats import plugins
from ntpstats.series import TimeSeries

ONLY = os.environ.get("NTPSTATS_PLUGIN")
UNRELATED = [
    "1700000000.0,0.001",
    "60000 3600.000 0.000123 1.234 0.000010 0.001 6",
    "2026-01-01 00:00:00 192.0.2.1 N 2 111 111 1111 10 10 0.98 1.0e-04 2.0e-03 1.0e-06 1.0e-06 3.0e-04 192.0.2.1 4B D K",
]


def _keep(name):
    return ONLY is None or name == ONLY


def _ids(d):
    return [n for n in d if _keep(n)]


PARSERS = plugins.external_parsers()
DETECTORS = plugins.detectors()
MASKS = plugins.discover("masks").items
PROFILES = plugins.discover("profiles").items


def test_plugins_load_without_errors():
    errors = {f"{k}:{n}": e for k in plugins.GROUPS for n, e in plugins.discover(k).errors.items() if _keep(n)}
    assert not errors, f"plugins failed to load: {errors}"


@pytest.mark.parametrize("name", _ids(PARSERS) or [pytest.param(None, marks=pytest.mark.skip("no parser plugins"))])
def test_parser_example_parses(name):
    p = PARSERS[name]
    assert p.name == name and p.description, "give the parser a name and a one-line description"
    assert p.example.strip(), "set ParserPlugin.example to a short sample of the format"
    series = p.parse(p.example.splitlines(), "example")
    assert isinstance(series, list) and series, "parse() must return a non-empty list of TimeSeries"
    for s in series:
        assert isinstance(s, TimeSeries) and len(s) >= 2
        assert np.all(np.isfinite(s.t)) and np.all(np.diff(s.t) >= 0), "times must be finite and sorted"
        assert s.offset.dtype.kind == "f" and np.isfinite(s.offset).any()
        assert 1e8 < s.t[0] < 1e10, "times must be POSIX seconds"


@pytest.mark.parametrize("name", _ids(PARSERS) or [pytest.param(None, marks=pytest.mark.skip("no parser plugins"))])
def test_parser_detection_and_load(name):
    from ntpstats.parsers import detect_format, load

    p = PARSERS[name]
    lines = p.example.splitlines()
    if p.detect is not None:
        score = float(p.detect(lines))
        assert 0.0 <= score <= 1.0
        assert score >= 0.5, "detect() should recognise the plugin's own example"
        for other in UNRELATED:
            assert float(p.detect([other])) < 0.9, "detect() must not claim unrelated formats with certainty"
        if score >= 0.9:
            assert detect_format(lines) == name
    assert load(p.example if "\n" in p.example else p.example + "\n", fmt=name)


@pytest.mark.parametrize("name", _ids(DETECTORS) or [pytest.param(None, marks=pytest.mark.skip("no detector plugins"))])
def test_detector_runs(name):
    from ntpstats.events import Event, detect

    d = DETECTORS[name]
    assert d.example is not None, "set DetectorPlugin.example to a function returning a TimeSeries"
    s = d.example()
    events = d.detect(s)
    assert isinstance(events, list) and all(isinstance(e, Event) for e in events)
    assert all(np.isfinite(e.time) for e in events)
    assert len(detect(s)) >= len(events)  # also wired into ntpstats.events.detect


@pytest.mark.parametrize("name", _ids(MASKS) or [pytest.param(None, marks=pytest.mark.skip("no mask plugins"))])
def test_mask_loads(name):
    from ntpstats.masks import load_mask

    m = load_mask(name)
    assert m.taus.size >= 1 and np.all(m.taus > 0) and np.all(m.limits > 0)


@pytest.mark.parametrize("name", _ids(PROFILES) or [pytest.param(None, marks=pytest.mark.skip("no profile plugins"))])
def test_profile_validates(name):
    from ntpstats.profiles import load_profile

    prof = load_profile(name)
    assert prof["name"] == name and "value_column" in prof
