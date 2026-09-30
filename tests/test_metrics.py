# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""OpenMetrics exporter and the shipped Grafana/Prometheus files (issue #36)."""

import json
import os
import re
import urllib.request

import numpy as np
import pytest
from test_sntp import server  # noqa: F401 (fixture)

from ntpstats import sntp
from ntpstats.metrics import CONTENT_TYPE, Registry, error_kind, serve
from ntpstats.monitor import Monitor
from ntpstats.sntp import KissOfDeath

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = re.compile(r'^(ntpstats_[a-z_]+)(\{[^}]*\})? (\S+)$')


def parse(text):
    """Minimal OpenMetrics parser: {(name, labels): value}; checks the syntax as it goes."""
    assert text.endswith("# EOF\n")
    out = {}
    for ln in text.splitlines():
        if ln.startswith("#"):
            assert re.match(r"^# (TYPE|HELP|EOF)", ln), ln
            continue
        m = SAMPLE.match(ln)
        assert m, ln
        out[(m.group(1), m.group(2) or "")] = float(m.group(3))
    return out


def test_registry_values_bound_and_rolling_tdev():
    reg = Registry(window=256)
    rng = np.random.default_rng(1)
    for i in range(200):
        reg.observe("s1", 1.7e9 + 16 * i, 1e-3 + rng.normal(0, 1e-5), delay=2e-3, root_delay=4e-3,
                    root_dispersion=1e-3, stratum=2.0, authenticated=1.0)
    reg.error("s1", "timeout")
    reg.error("s1", "timeout")
    m = parse(reg.render())
    lab = '{source="s1"}'
    off = m[("ntpstats_offset_seconds", lab)]
    assert m[("ntpstats_offset_bound_seconds", lab)] == pytest.approx(abs(off) + 1e-3 + 2e-3 + 1e-3)
    assert m[("ntpstats_samples_total", lab)] == 200
    assert m[("ntpstats_errors_total", '{source="s1",kind="timeout"}')] == 2
    assert m[("ntpstats_authenticated", lab)] == 1
    assert m[("ntpstats_offset_stddev_seconds", lab)] == pytest.approx(1e-5, rel=0.2)
    tdev = {k[1]: v for k, v in m.items() if k[0] == "ntpstats_tdev_seconds"}
    assert set(tdev) == {'{source="s1",tau="16"}', '{source="s1",tau="64"}', '{source="s1",tau="256"}'}
    # white PM: TDEV(tau0) equals the phase noise sigma
    assert tdev['{source="s1",tau="16"}'] == pytest.approx(1e-5, rel=0.3)


def test_label_escaping_and_watch_samples():
    reg = Registry()
    reg.observe_watch("chrony", {"time": 1.0, "offset": -2e-6, "frequency_ppm": 3.5, "root_delay": 1e-3,
                                 "root_dispersion": 5e-4, "stratum": "3"})
    reg.observe('we"ird\\name', 1.0, 0.0)
    m = parse(reg.render())
    assert m[("ntpstats_frequency_ppm", '{source="chrony"}')] == 3.5
    assert m[("ntpstats_stratum", '{source="chrony"}')] == 3
    assert ("ntpstats_offset_seconds", '{source="we\\"ird\\\\name"}') in m


def test_error_kind():
    assert error_kind(KissOfDeath("RATE")) == "kod_rate"
    assert error_kind(TimeoutError("timed out")) == "timeout"
    assert error_kind(OSError("x")) == "oserror"


def test_http_endpoint(server, monkeypatch):  # noqa: F811
    real = sntp.query
    monkeypatch.setattr("ntpstats.monitor.query", lambda host: real(host, port=server.port))
    reg = Registry()
    Monitor(["127.0.0.1"], interval=0.05, count=3, on_sample=reg.observe_ntp).run()
    srv = serve(reg, "127.0.0.1", 0)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/metrics"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.headers["Content-Type"] == CONTENT_TYPE
            m = parse(resp.read().decode())
        assert m[("ntpstats_samples_total", '{source="127.0.0.1"}')] == 3
        assert m[("ntpstats_offset_seconds", '{source="127.0.0.1"}')] == pytest.approx(0.25, abs=0.01)
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url.replace("/metrics", "/other"), timeout=5)
    finally:
        srv.shutdown()


def _exported_names():
    return {"ntpstats_offset_seconds", "ntpstats_delay_seconds", "ntpstats_offset_bound_seconds",
            "ntpstats_root_delay_seconds", "ntpstats_root_dispersion_seconds", "ntpstats_stratum",
            "ntpstats_frequency_ppm", "ntpstats_authenticated", "ntpstats_last_sample_timestamp_seconds",
            "ntpstats_offset_stddev_seconds", "ntpstats_tdev_seconds", "ntpstats_samples_total",
            "ntpstats_errors_total"}


def test_exported_names_cover_registry_output():
    reg = Registry()
    for i in range(20):
        reg.observe("a", float(i), 0.0, delay=1e-3, root_delay=1e-3, root_dispersion=1e-3, stratum=1.0,
                    frequency_ppm=1.0, authenticated=0.0)
    reg.error("a", "timeout")
    names = {k[0] for k in parse(reg.render())}
    assert names == _exported_names()


def test_dashboard_and_rules_only_use_exported_metrics():
    dash = json.load(open(os.path.join(ROOT, "contrib", "grafana", "ntpstats-dashboard.json")))
    exprs = [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]
    assert len(exprs) >= 8
    rules = open(os.path.join(ROOT, "contrib", "prometheus", "ntpstats-rules.yml")).read()
    used = set(re.findall(r"\bntpstats_[a-z_]+", " ".join(exprs) + rules))
    assert used and used <= _exported_names(), used - _exported_names()
    assert {p["title"] for p in dash["panels"]} >= {"Offset", "Offset bound", "TDEV (rolling)"}
