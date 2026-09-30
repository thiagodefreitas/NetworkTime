# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""UTC traceability audit (issue #22)."""

import json

import numpy as np
import pytest

from ntpstats.audit import AuditConfig, audit, components, public, to_html
from ntpstats.cli import main
from ntpstats.series import TimeSeries


def series(n=3600, tau0=10.0, offset=20e-6, delay=100e-6, root=True, gap=None):
    t = 1.8e9 + np.arange(n) * tau0
    if gap:
        keep = (t < t[0] + gap[0]) | (t >= t[0] + gap[1])
        t = t[keep]
    m = t.size
    extra = {"delay": np.full(m, delay)}
    if root:
        extra.update(root_delay=np.full(m, 40e-6), root_dispersion=np.full(m, 5e-6))
    return TimeSeries(t, np.full(m, offset), name="host", extra=extra)


def test_bound_components_and_rules():
    s = series()
    c = components(s, AuditConfig(limit=1e-3, reference_uncertainty=100e-9))
    b = c["offset"] + c["path"] + c["upstream"] + c["reference"]
    assert b[0] == pytest.approx(20e-6 + 50e-6 + 20e-6 + 5e-6 + 100e-9)
    assert "delay" in c["rules"]["path"] and "root_delay" in c["rules"]["upstream"]
    assert c["notes"] == []


def test_missing_terms_are_declared_as_assumptions():
    s = TimeSeries(np.arange(100.0), np.zeros(100), name="x")
    c = components(s, AuditConfig(limit=1e-3))
    assert "none" in c["rules"]["path"] and "none" in c["rules"]["upstream"]
    assert len(c["notes"]) == 3
    c2 = components(s, AuditConfig(limit=1e-3, asymmetry=1e-4, upstream=2e-4))
    assert c2["path"][0] == 1e-4 and c2["upstream"][0] == 2e-4


def test_pass_and_windows():
    r = audit(series(), AuditConfig(limit=100e-6))
    sm = r["summary"]
    assert sm["passed"] and sm["failing_windows"] == 0 and sm["coverage"] == pytest.approx(1.0)
    assert sm["windows"] == 10 and all(w["status"] == "pass" for w in r["windows"])
    assert sm["within_limit_fraction_of_period"] == pytest.approx(1.0)


def test_failure_is_localised_to_its_window():
    s = series()
    s.offset[1000] = 500e-6
    r = audit(s, AuditConfig(limit=100e-6))
    assert not r["summary"]["passed"] and r["summary"]["failing_windows"] == 1
    assert r["worst"][0]["time"] == pytest.approx(s.t[1000])
    assert r["summary"]["within_limit_fraction_of_period"] == pytest.approx(1 - 1 / 3600, rel=1e-6)


def test_gaps_are_unmonitored_not_compliant():
    s = series(gap=(7200, 14400))  # two hours without samples
    r = audit(s, AuditConfig(limit=100e-6))
    sm = r["summary"]
    assert sm["unmonitored_s"] == pytest.approx(7200, abs=40)
    assert sm["coverage"] == pytest.approx(0.8, abs=0.01) and not sm["passed"]
    status = [w["status"] for w in r["windows"]]
    assert status.count("insufficient") == 2 and "fail" not in status


def test_html_and_json_outputs(tmp_path, capsys):
    s = series(n=720)
    html = to_html([audit(s, AuditConfig(limit=100e-6))], [])
    assert "UTC traceability audit" in html and "Assumptions applied" in html and "PASS" in html
    p = tmp_path / "mon.csv"
    p.write_text("unix_time,offset,delay,root_delay,root_dispersion\n" + "".join(
        f"{1.8e9 + 64 * i},{2e-4},{3e-4},{1e-4},{1e-5}\n" for i in range(200)))
    out = tmp_path / "a.html"
    assert main(["audit", str(p), "--limit", "1ms", "--html", str(out), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["inputs"][0]["sha256"] and len(doc["inputs"][0]["sha256"]) == 64
    assert doc["audit"][0]["summary"]["max_bound"] == pytest.approx(2e-4 + 1.5e-4 + 5e-5 + 1e-5)
    assert "sha256" in out.read_text()
    assert main(["audit", str(p), "--limit", "100us"]) == 3
    assert "FAIL" in capsys.readouterr().out
    assert "_t" not in public(audit(s, AuditConfig(limit=1.0)))
