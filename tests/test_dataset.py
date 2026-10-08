# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Open interop dataset (#30): records written by docs/interop.py and read back by ntpstats."""

import importlib.util
import json
import os

import pytest

from ntpstats.parsers import detect_format, load
from ntpstats.sntp import NTPResult

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def interop_module():
    spec = importlib.util.spec_from_file_location("interop_script", os.path.join(ROOT, "docs", "interop.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ntp_result(offset, delay=0.02):
    return NTPResult(server="s", address="192.0.2.1", t1=0, t2=0, t3=0, t4=0, offset=offset, delay=delay,
                     stratum=1, leap=0, version=4, poll=6, precision=1e-6, root_delay=1e-4, root_dispersion=2e-4,
                     refid="GPS")


def write_week(mod, path, day, offsets, fail=False):
    mod.RECORDS.clear()
    mod.RUN.update({"run": f"{day}T06:17:00Z", "ntpstats": "test", "runner": "github-ubuntu24", "family": "ipv4"})
    for server, off in offsets.items():
        rec = mod.record("ntp4", server, True, **mod._ntp_fields(ntp_result(off)))
        rec["time"] = rec["time"]  # probe time from the clock
    if fail:
        mod.record("ntp4", "time.example", False, "timeout waiting for time.example")
    mod.record("roughtime-chain", "all", True, responses=6, violations=0, local_offset_interval=[-1.0, 0.5])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in mod.RECORDS:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def test_records_follow_schema(tmp_path):
    mod = interop_module()
    write_week(mod, str(tmp_path / "2026" / "2026-10-05.jsonl"), "2026-10-05", {"time.example": 1e-3}, fail=True)
    recs = [json.loads(x) for x in (tmp_path / "2026" / "2026-10-05.jsonl").read_text().splitlines()]
    ok = recs[0]
    assert ok["schema"] == 1 and ok["test"] == "ntp4" and ok["ok"] and ok["offset"] == 1e-3
    assert {"run", "time", "address", "stratum", "refid", "root_delay", "root_dispersion"} <= set(ok)
    assert recs[1]["ok"] is False and "timeout" in recs[1]["error"] and "offset" not in recs[1]
    assert detect_format([json.dumps(ok)]) == "interop"


def test_dataset_directory_loads_as_long_series(tmp_path, monkeypatch):
    mod = interop_module()
    clock = iter(range(1_790_000_000, 1_800_000_000, 604800))
    monkeypatch.setattr(mod.time, "time", lambda: float(next(clock)))
    for k, day in enumerate(["2026-10-05", "2026-10-12", "2026-10-19"]):
        write_week(mod, str(tmp_path / "interop" / "2026" / f"{day}.jsonl"), day,
                   {"time.example": 1e-3 * (k + 1), "ntp.example": -2e-3}, fail=(k == 1))
    (tmp_path / "interop" / "README.md").write_text("# not data\n")
    ss = {s.meta["peer"]: s for s in load(str(tmp_path / "interop"))}
    a = ss["time.example"]
    assert a.source_format == "interop" and len(a) == 3 and a.offset[2] == pytest.approx(3e-3)
    assert a.meta["probes"] == 4 and a.meta["failures"] == 1 and a.meta["availability"] == pytest.approx(0.75)
    assert a.meta["runs"] == 3 and a.extra["delay"][0] == pytest.approx(0.02)
    assert "all" not in ss  # the Roughtime chain summary has no offset


def test_dataset_summary_cli(tmp_path, capsys):
    from ntpstats.cli import main

    mod = interop_module()
    for k, day in enumerate(["2026-10-05", "2026-10-12"]):
        write_week(mod, str(tmp_path / "2026" / f"{day}.jsonl"), day, {"time.example": 1e-3}, fail=(k == 1))
    assert main(["dataset", str(tmp_path), "--json"]) == 0
    rows = {(r["test"], r["server"]): r for r in json.loads(capsys.readouterr().out)}
    r = rows[("ntp4", "time.example")]
    assert r["runs"] == 2 and r["probes"] == 3 and r["availability"] == pytest.approx(2 / 3)
    assert r["median_offset"] == pytest.approx(1e-3) and "timeout" in r["last_error"]
    assert main(["dataset", str(tmp_path)]) == 0
    assert "last error" in capsys.readouterr().out


def trend_records():
    """Three weekly runs; the runner's clock is off by +5, -3 and +1 ms."""
    from ntpstats.research import interop_trend  # noqa: F401

    runs = ["2026-10-05T06:17:00Z", "2026-10-12T06:17:00Z", "2026-10-19T06:17:00Z"]
    runner = [5e-3, -3e-3, 1e-3]
    recs = []

    def rec(k, test, server, ok=True, offset=None, delay=0.01, **kw):
        r = {"schema": 1, "run": runs[k], "time": 1_791_000_000.0 + 604800 * k, "test": test, "server": server,
             "ok": ok, "error": None if ok else "timeout"}
        if ok:
            r.update(offset=offset - runner[k], delay=delay, **kw)  # server - runner clock
        recs.append(json.dumps(r))

    for k in range(3):
        rec(k, "ntp4", "steady.example", offset=0.0)
        rec(k, "ntp4", "other.example", offset=1e-4)
        rec(k, "ntp4", "third.example", offset=-1e-4)
        rec(k, "ntp4", "stepped.example", offset=0.05 if k == 2 else 0.0)  # its clock moved 50 ms
        rec(k, "ntp4", "longpath.example", offset=[0.0, 0.03, -0.02][k], delay=0.1)  # asymmetry within delay/2
        rec(k, "nts", "dying.example", ok=k < 2, offset=0.0)
        if k:
            rec(k, "nts", "fresh.example", offset=0.0)
        rec(k, "roughtime", "rt.example", offset=0.3 * k, delay=0.05, radius=1.0)  # within its radius
    return recs


def test_trend_cancels_the_runner_clock_and_flags_servers():
    from ntpstats.research import interop_trend

    rows = {r["server"]: r for r in interop_trend(trend_records())}
    steady = rows["steady.example"]
    assert steady["status"] == "ok" and steady["runs"] == 3
    assert [t[2] for t in steady["timeline"]] == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)  # runner error gone
    assert steady["slope_per_week"] == pytest.approx(0.0, abs=1e-12)
    assert rows["stepped.example"]["status"] == "shift"
    assert rows["stepped.example"]["rel_last"] == pytest.approx(0.05, abs=1e-12)
    assert rows["longpath.example"]["status"] == "ok"  # a path change cannot exceed delay/2
    assert rows["rt.example"]["status"] == "ok"  # nor a Roughtime offset its radius
    assert rows["dying.example"]["status"] == "gone" and rows["dying.example"]["last_ok"] is False
    assert rows["fresh.example"]["status"] == "new" and rows["fresh.example"]["first"].startswith("2026-10-12")
    assert rows["dying.example"]["availability"] == pytest.approx(2 / 3)


def test_trend_cli_strict_exit_code(tmp_path, capsys):
    from ntpstats.cli import main

    path = tmp_path / "2026.jsonl"
    path.write_text("\n".join(trend_records()) + "\n")
    assert main(["dataset", str(path), "--trend"]) == 0
    out = capsys.readouterr().out
    assert "3 runs" in out and "stepped.example" in out and "shift" in out and "gone" in out
    assert main(["dataset", str(path), "--trend", "--strict"]) == 3
    assert main(["dataset", str(path), "--trend", "--strict", "--test", "ntp4", "--shift", "1"]) == 0
