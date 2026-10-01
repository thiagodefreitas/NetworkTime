# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Plugin architecture (#37): discovery, use in parsers/events/masks/profiles, broken plugins, listing."""

import json
import os
import sys

import pytest

from ntpstats import plugins

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "examples", "plugins", "ntpstats-toy-csv"))
import ntpstats_toy_csv as toy  # noqa: E402


class FakeEP:
    def __init__(self, name, obj, error=None):
        self.name, self.value, self.dist = name, f"toy:{name}", None
        self._obj, self._error = obj, error

    def load(self):
        if self._error:
            raise self._error
        return self._obj


@pytest.fixture
def installed(monkeypatch):
    eps = {
        "ntpstats.parsers": [FakeEP("toycsv", toy.PARSER), FakeEP("broken", None, ImportError("no module named x")),
                             FakeEP("csv", toy.PARSER)],  # cannot shadow a built-in format
        "ntpstats.detectors": [FakeEP("toy-big-offset", toy.DETECTOR)],
        "ntpstats.masks": [FakeEP("toy-tdev", toy.MASK)],
        "ntpstats.profiles": [FakeEP("toy-counter", toy.PROFILE)],
        "ntpstats.estimators": [],
    }
    monkeypatch.setattr(plugins, "_entry_points", lambda group: eps.get(group, []))
    plugins._CACHE.clear()
    yield
    plugins._CACHE.clear()


def test_parser_plugin_is_detected_and_used(installed, tmp_path):
    from ntpstats.parsers import all_formats, detect_format, load

    assert "toycsv" in all_formats() and list(plugins.external_parsers()) == ["toycsv"]
    assert detect_format(toy.EXAMPLE.splitlines()) == "toycsv"
    p = tmp_path / "x.toy"
    p.write_text(toy.EXAMPLE)
    (s,) = load(str(p))
    assert s.source_format == "toycsv" and len(s) == 64
    assert detect_format(["1700000000.0,0.001", "1700000016.0,0.002"]) == "csv"  # does not grab other formats


def test_detector_mask_profile_plugins(installed):
    from ntpstats.events import detect
    from ntpstats.masks import load_mask
    from ntpstats.profiles import load_profile

    ev = detect(toy._example_series())
    assert any(e.kind == "toy_big_offset" for e in ev)
    m = load_mask("toy-tdev")
    assert m.kind == "tdev" and list(m.taus) == [1, 100, 10000]
    assert load_profile("toy-counter")["units"] == "us"


def test_broken_plugin_is_reported_not_fatal(installed, capsys):
    from ntpstats.cli import main

    assert "broken" in plugins.discover("parsers").errors
    assert main(["plugins", "--json"]) == 1  # load errors -> non-zero, for CI
    doc = json.loads(capsys.readouterr().out)
    assert any(r["name"] == "toycsv" and r["description"] for r in doc["parsers"])
    assert doc["errors"][0]["name"] == "parsers: broken"
    assert main(["plugins"]) == 1
    out = capsys.readouterr().out
    assert "toy-big-offset" in out and "toy-tdev" in out and "ImportError" in out


def test_builtin_formats_use_the_plugin_api():
    from ntpstats.parsers import format_descriptions

    builtin = plugins.parsers()
    assert {"cggtts", "circular-t", "ripe-atlas", "interop"} <= set(builtin)
    assert all(p.source == "built-in" for p in builtin.values())
    assert format_descriptions()["cggtts"].startswith("CGGTTS")


def test_contract_suite_passes_for_the_example(installed):
    pytest.importorskip("pytest")
    import importlib

    import ntpstats.testing.plugin_contract as pc

    importlib.reload(pc)
    pc.test_parser_example_parses("toycsv")
    pc.test_parser_detection_and_load("toycsv")
    pc.test_detector_runs("toy-big-offset")
    pc.test_mask_loads("toy-tdev")
    pc.test_profile_validates("toy-counter")
