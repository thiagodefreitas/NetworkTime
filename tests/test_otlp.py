# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""OpenTelemetry (OTLP/HTTP JSON) export of monitor/watch metrics (#36)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ntpstats import otlp
from ntpstats.metrics import Registry


def registry():
    r = Registry()
    for i in range(40):
        r.observe("time.example", 1.8e9 + 16 * i, 1e-4 * (i % 3), delay=0.02, root_delay=1e-3,
                  root_dispersion=2e-3, stratum=2.0, authenticated=1.0)
    r.error("time.example", "timeout")
    return r


@pytest.fixture
def collector():
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got.append((self.path, {k.lower(): v for k, v in self.headers.items()}, json.loads(body)))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", got
    srv.shutdown()


def test_payload_structure_and_names():
    d = otlp.to_otlp(registry(), resource={"host.name": "lab-1"}, now_ns=10, start_ns=5)
    rm = d["resourceMetrics"][0]
    res = {a["key"]: a["value"] for a in rm["resource"]["attributes"]}
    assert res["service.name"] == {"stringValue": "ntpstats"} and res["host.name"] == {"stringValue": "lab-1"}
    ms = {m["name"]: m for m in rm["scopeMetrics"][0]["metrics"]}
    off = ms["ntpstats.offset"]
    assert off["unit"] == "s" and off["gauge"]["dataPoints"][0]["timeUnixNano"] == "10"
    assert off["gauge"]["dataPoints"][0]["attributes"] == [{"key": "source", "value": {"stringValue": "time.example"}}]
    assert ms["ntpstats.offset_bound"]["gauge"]["dataPoints"][0]["asDouble"] > 0.01
    assert {p["attributes"][1]["value"]["doubleValue"] for p in ms["ntpstats.tdev"]["gauge"]["dataPoints"]} == {16.0, 64.0}  # 40 samples: TDEV needs 3m + 1
    s = ms["ntpstats.samples"]["sum"]
    assert s["isMonotonic"] and s["aggregationTemporality"] == 2
    assert s["dataPoints"][0]["asInt"] == "40" and s["dataPoints"][0]["startTimeUnixNano"] == "5"
    assert ms["ntpstats.errors"]["sum"]["dataPoints"][0]["attributes"][1]["value"] == {"stringValue": "timeout"}


def test_endpoint_resolution(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
    assert otlp.metrics_url() == "http://localhost:4318/v1/metrics"
    assert otlp.metrics_url("http://c:4318/") == "http://c:4318/v1/metrics"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example")
    assert otlp.metrics_url() == "https://otel.example/v1/metrics"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "https://m.example/custom")
    assert otlp.metrics_url() == "https://m.example/custom"


def test_push_headers_and_failures(collector, monkeypatch):
    url, got = collector
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20abc,x-team=time")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=lab")
    p = otlp.Pusher(registry(), url, interval=3600)
    p.flush()
    path, headers, body = got[0]
    assert path == "/v1/metrics" and headers["content-type"] == "application/json"
    assert headers["authorization"] == "Bearer abc" and headers["x-team"] == "time"
    keys = {a["key"] for a in body["resourceMetrics"][0]["resource"]["attributes"]}
    assert "deployment.environment" in keys
    dead = otlp.Pusher(registry(), "http://127.0.0.1:9", interval=3600)  # nothing listens: counted, not raised
    dead.flush()
    assert dead.failures == 1 and dead.last_error


def test_cli_flags(collector):
    from ntpstats.cli import build_parser

    url, _ = collector
    a = build_parser().parse_args(["monitor", "x.example", "--otlp", url, "--otlp-interval", "5"])
    assert a.otlp == url and a.otlp_interval == 5
    assert build_parser().parse_args(["watch", "chrony", "--otlp"]).otlp == "env"
