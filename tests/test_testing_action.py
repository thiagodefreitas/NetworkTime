# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Timing assertions (pytest plugin) and the GitHub Action summary (issue #36)."""

import importlib.util
import os

import numpy as np
import pytest

from ntpstats import testing as T
from ntpstats.series import TimeSeries

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples", "data")


def te_series(level=10e-9, n=600):
    t = 1.8e9 + np.arange(n) * 1.0
    return TimeSeries(t, -np.full(n, level) - np.random.default_rng(0).normal(0, 1e-9, n), name="dut")


def test_max_te_and_limits():
    T.assert_max_te(te_series(), 30e-9)
    with pytest.raises(AssertionError, match="max\\|TE\\|"):
        T.assert_max_te(te_series(level=50e-9), 30e-9)
    T.assert_time_error_within(te_series(), {"max_te": 30e-9, "cte": 20e-9})
    with pytest.raises(AssertionError, match="cTE"):
        T.assert_time_error_within(te_series(), "cte, 5ns\n")


def test_stability_audit_bounds_and_events_on_example_files(tmp_path):
    mask = tmp_path / "m.csv"
    mask.write_text("tau,tdev\n16,1\n1024,1\n")
    T.assert_stability_within(os.path.join(EX, "chrony-tracking.log"), str(mask))
    mask.write_text("tau,tdev\n16,1e-9\n1024,1e-9\n")
    with pytest.raises(AssertionError, match="TDEV above mask"):
        T.assert_stability_within(os.path.join(EX, "chrony-tracking.log"), str(mask))
    T.assert_audit_passes(os.path.join(EX, "chrony-tracking.log"), 50e-3)
    with pytest.raises(AssertionError, match="audit failed"):
        T.assert_audit_passes(os.path.join(EX, "chrony-tracking.log"), 1e-3)
    with pytest.raises(AssertionError, match="violated"):
        T.assert_bounds_valid(os.path.join(EX, "clockbound.txt"), os.path.join(EX, "clockbound-reference.csv"))
    T.assert_no_events(os.path.join(EX, "ptp-capture.pcapng"))
    with pytest.raises(AssertionError, match="phase_step"):
        T.assert_no_events(os.path.join(EX, "clockbound-reference.csv"))


def test_pytest_fixture(timing_log):
    s = timing_log(os.path.join(EX, "w32tm-stripchart.txt"))
    assert s.source_format == "w32tm"


def _summary_module():
    spec = importlib.util.spec_from_file_location("summary", os.path.join(ROOT, "contrib", "action", "summary.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_action_summary(tmp_path, monkeypatch, capsys):
    mod = _summary_module()
    md, out = tmp_path / "summary.md", tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(md))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert mod.main(["audit", os.path.join(EX, "chrony-tracking.log"), "--limit", "50ms"]) == 0
    assert "✅ pass" in md.read_text() and out.read_text().strip() == "result=pass"
    lim = tmp_path / "l.csv"
    lim.write_text("max_te, 1ns\n")
    assert mod.main(["timeerror", os.path.join(EX, "ptp-capture.pcapng"), "--limits", str(lim)]) == 3
    assert "❌ fail" in md.read_text() and out.read_text().strip().endswith("result=fail")
    assert mod.main(["nonsense"]) == 2


def test_action_metadata():
    yaml = pytest.importorskip("yaml")

    a = yaml.safe_load(open(os.path.join(ROOT, "action.yml")))
    assert a["runs"]["using"] == "composite" and {"command", "args"} <= set(a["inputs"])
    run = a["runs"]["steps"][-1]["run"]
    assert "${{" not in run  # inputs are passed through env, never interpolated into the script
