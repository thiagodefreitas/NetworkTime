# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""3.8: fleet view, many hosts ranked against the same thresholds, and matching alert rules (#36)."""

import json
import os

import numpy as np
import pytest

from ntpstats.cli import main
from ntpstats.fleet import Thresholds, alert_rules, assess, fleet, format_age, host_of, hosts_of_paths, summary
from ntpstats.masks import load_mask
from ntpstats.series import TimeSeries
from ntpstats.web import server as S

T0 = 1_760_000_000.0


def host(name, offset, jitter, n=600, step=60.0, delay=None, end=T0):
    rng = np.random.default_rng(len(name))
    t = end - step * np.arange(n)[::-1]
    extra = {"delay": np.full(n, delay)} if delay is not None else {}
    return TimeSeries(t=t, offset=offset + jitter * rng.standard_normal(n), name=name, extra=extra,
                      meta={"file": name})


def test_assess_values_verdicts_and_usage():
    th = Thresholds(max_offset=1e-3, max_jitter=1e-4, max_bound=2e-3, max_age=600)
    r = assess(host("a", 2e-4, 1e-5, delay=1e-3), th, now=T0 + 60)
    assert r["verdict"] == "ok" and r["host"] == "a" and r["samples"] == 600
    assert r["bound_max"] == pytest.approx(r["offset_max_abs"] + 5e-4)
    assert r["worst"] == "bound" and r["usage"] == pytest.approx(r["bound_max"] / 2e-3)
    r = assess(host("b", 3e-3, 1e-5), th, now=T0)
    assert r["verdict"] == "fail" and r["reasons"][0].startswith("offset 3") and r["bound_max"] is None
    r = assess(host("c", 0.0, 1e-6), th, now=T0 + 3600)
    assert r["verdict"] == "stale" and r["age"] == pytest.approx(3600) and r["reasons"] == ["age 60 min > 10 min"]
    assert assess(host("d", 0.0, 1e-6), Thresholds(max_offset=None), now=T0)["verdict"] == "unchecked"


def test_window_limits_the_assessment_to_recent_samples():
    s = host("w", 0.0, 1e-6)
    s.offset[:300] = 5e-3  # an old excursion, more than 5 h before the end
    assert assess(s, Thresholds(window=3 * 3600), now=T0)["verdict"] == "ok"
    assert assess(s, Thresholds(window=None), now=T0)["verdict"] == "fail"


def test_ranking_failures_first_then_nearest_limit():
    rows = fleet([host("calm", 1e-5, 1e-6), host("bad", 4e-3, 1e-6), host("close", 9e-4, 1e-6)],
                 Thresholds(max_offset=1e-3), now=T0)
    assert [r["host"] for r in rows] == ["bad", "close", "calm"] and [r["rank"] for r in rows] == [1, 2, 3]
    assert summary(rows) == {"fail": 1, "stale": 0, "ok": 2, "unchecked": 0, "hosts": 3}


def test_mask_counts_as_a_limit(tmp_path):
    m = tmp_path / "m.csv"
    m.write_text("tau,tdev\n1,1e-9\n100000,1e-9\n")
    r = assess(host("m", 0.0, 1e-5), Thresholds(max_offset=None, mask=load_mask(str(m))), now=T0)
    assert r["verdict"] == "fail" and r["mask"]["passed"] is False and r["worst"] == "mask"


def test_host_names():
    s = host("x", 0, 0)
    s.meta["labels"] = "instance=web1:9123,source=chrony"
    assert host_of(s) == "web1:9123"
    assert hosts_of_paths(["a/h1/tracking.log", "a/h2/tracking.log"]) == ["h1", "h2"]
    assert hosts_of_paths(["a/h1.log", "a/h2.log"]) == ["h1.log", "h2.log"]
    assert format_age(30) == "30 s" and format_age(3 * 3600) == "3 h" and format_age(4 * 31557600) == "4 y"


def test_alert_rules_match_the_thresholds():
    y = alert_rules(Thresholds(max_offset=1e-3, max_jitter=1e-4, max_bound=5e-3, max_age=600))
    assert "abs(ntpstats_offset_seconds) > 0.001" in y and "ntpstats_offset_stddev_seconds > 0.0001" in y
    assert "ntpstats_offset_bound_seconds > 0.005" in y and "ntpstats_last_sample_timestamp_seconds > 600" in y
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(y)
    assert [r["alert"] for r in doc["groups"][0]["rules"]] == ["NtpstatsFleetOffset", "NtpstatsFleetJitter",
                                                               "NtpstatsFleetBound", "NtpstatsFleetStale"]


def _write(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("unix_time,offset,delay\n" + "".join(f"{a:.3f},{b:.9g},0.001\n" for a, b in zip(s.t, s.offset)))


def test_cli_fleet_directories_json_csv_strict_and_rules(tmp_path, capsys):
    _write(str(tmp_path / "f" / "web1" / "x.csv"), host("web1", 1e-4, 1e-6))
    _write(str(tmp_path / "f" / "web2" / "x.csv"), host("web2", 3e-3, 1e-6))
    assert main(["fleet", str(tmp_path / "f"), "--max-bound", "2ms", "--now", str(T0 + 30)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("2 hosts: 1 fail, 0 stale, 1 ok")
    assert out.index("web2") < out.index("web1")
    assert main(["fleet", str(tmp_path / "f"), "--json", "--csv", str(tmp_path / "f.csv"), "--max-age", "1m",
                 "--now", str(T0 + 3600), "--strict"]) == 3
    doc = json.loads(capsys.readouterr().out)
    assert doc["summary"]["stale"] == 1 and doc["summary"]["fail"] == 1
    assert (tmp_path / "f.csv").read_text().splitlines()[0].startswith("rank,host,source,verdict")
    assert main(["fleet", "--rules", str(tmp_path / "r.yml"), "--max-jitter", "50us"]) == 0
    assert "ntpstats_offset_stddev_seconds > 5e-05" in (tmp_path / "r.yml").read_text()
    with pytest.raises(SystemExit):
        main(["fleet"])


def test_web_fleet_endpoint_and_rules():
    S.STORE.datasets.clear()
    a, b = S.STORE.add(host("ok-host", 1e-5, 1e-6)), S.STORE.add(host("bad-host", 2e-3, 1e-6))
    r = S.dispatch("GET", f"/api/fleet?max_offset=1ms&window=86400&now={T0}", {}, b"")
    doc = json.loads(r.body)
    assert r.status == 200 and [h["id"] for h in doc["hosts"]] == [b, a] and doc["summary"]["fail"] == 1
    r = S.dispatch("GET", "/api/fleet/rules.yml?max_offset=2ms", {}, b"")
    assert r.status == 200 and b"abs(ntpstats_offset_seconds) > 0.002" in r.body
    S.STORE.datasets.clear()
