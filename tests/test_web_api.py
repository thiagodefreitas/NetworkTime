# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Web API endpoints added with the UI overhaul (2.17): audit, trace, compare, hat, bench, chain."""

import json
import os

import pytest

from ntpstats.web import server as S

EX = os.path.join(os.path.dirname(__file__), "..", "examples", "data")


def call(method, path, body=b""):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()
    r = S.dispatch(method, path, {"X-Filename": "f"}, body)
    return r.status, (json.loads(r.body) if r.content_type.startswith("application/json") else r.body)


@pytest.fixture()
def ids():
    S.STORE.datasets.clear()
    st, ds = call("POST", "/api/upload", open(os.path.join(EX, "chrony-measurements.log"), "rb").read())
    assert st == 200
    return [d["id"] for d in ds]


def test_datasets_carry_a_sparkline(ids):
    st, ds = call("GET", "/api/datasets")
    assert len(ds[0]["spark"]) == 48 and all(v is None or isinstance(v, float) for v in ds[0]["spark"])


def test_audit_and_evidence_report(ids):
    st, a = call("GET", f"/api/audit/{ids[0]}?limit=100ms&window=3600")
    assert st == 200 and a["summary"]["passed"] and len(a["t"]) == len(a["bound"]) == len(a["offset"])
    st, a = call("GET", f"/api/audit/{ids[0]}?limit=1ms")
    assert not a["summary"]["passed"] and a["summary"]["failing_windows"] > 0
    st, html = call("GET", f"/api/export/{ids[0]}/audit.html?limit=1ms")
    assert st == 200 and b"<html" in html.lower()


def test_trace_and_compare(ids):
    st, t = call("GET", f"/api/trace/{ids[0]}")
    assert st == 200 and t["stats"]["to_ref"]["floor"] > 0 and len(t["to_ref"]) == len(t["t"])
    st, c = call("GET", f"/api/compare/{ids[0]}?ref={ids[1]}")
    assert st == 200 and c["stats"]["rms"] > 0 and {r["kind"] for r in c["stability"]} == {"tdev", "mtie"}
    st, err = call("GET", f"/api/compare/{ids[0]}?ref=nope")
    assert st == 404


def test_timeerror_series_only_on_request(ids):
    st, plain = call("GET", f"/api/timeerror/{ids[0]}")
    assert "te" not in plain  # unchanged answer (the in-browser parity test compares it)
    st, full = call("GET", f"/api/timeerror/{ids[0]}?series=1")
    assert len(full["te"]) == len(full["tel"]) == len(full["t"])


def test_hat_needs_three(ids):
    st, err = call("GET", f"/api/hat?ids={ids[0]},{ids[1]}")
    assert st == 400 and "three" in err["error"]
    sims = [call("POST", "/api/simulate", {"preset": "internet", "duration": 43200, "seed": k})[1][0]["id"]
            for k in (1, 2, 3)]
    st, h = call("GET", f"/api/hat?ids={','.join(sims)}")
    assert st == 200 and len(h["sources"]) == 3 and h["ids"] == sims


def test_estimators_bench_with_a_trace_and_chain(ids):
    st, e = call("GET", "/api/estimators")
    assert "lan" in e["presets"] and any(x["name"] == "mindelay" for x in e["estimators"])
    st, b = call("POST", "/api/bench", {"scenarios": ["lan", f"trace:{ids[0]}"], "estimators": ["raw", "mindelay"],
                                        "seeds": [1], "duration": 7200, "warmup": 600})
    assert st == 200 and {r["scenario"] for r in b["table"]} == {"lan", f"trace: {S.STORE.get(ids[0]).name}"}
    st, err = call("POST", "/api/bench", {"scenarios": ["mars"]})
    assert st == 400
    st, c = call("POST", "/api/chain", {"hops": 2, "duration": 600, "sync_rate": 4, "store": True,
                                        "asymmetry_spread": 5e-9})
    assert st == 200 and c["verdict"]["passed"] and len(c["te"]) == 2 and len(c["datasets"]) == 2
    st, err = call("POST", "/api/chain", {"hops": 200, "duration": 3600})
    assert st == 400 and "too large" in err["error"]
