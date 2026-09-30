# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""2.9 sources: linuxptp pmc, ptpcheck, w32tm, Prometheus, clock-error bounds, profiles (#21, #35)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from ntpstats import sources
from ntpstats.bounds import parse_bounds, validate
from ntpstats.cli import main
from ntpstats.parsers import ParseError, detect_format, load
from ntpstats.profiles import load_profile, parse_with_profile
from ntpstats.series import TimeSeries

PMC = """sending: GET CURRENT_DATA_SET
\t001122.fffe.334455-1 seq 0 RESPONSE MANAGEMENT CURRENT_DATA_SET
\t\tstepsRemoved     1
\t\toffsetFromMaster -12.0
\t\tmeanPathDelay    597.0
sending: GET TIME_STATUS_NP
\t001122.fffe.334455-1 seq 1 RESPONSE MANAGEMENT TIME_STATUS_NP
\t\tmaster_offset              -13
\t\tingress_time               1712345678123456789
\t\tcumulativeScaledRateOffset +0.000000000
\t\tgmPresent                  true
\t\tgmIdentity                 aabbcc.fffe.ddeeff
"""


def test_pmc_parser_sign_and_fields():
    d = sources.parse_pmc(PMC)
    assert d["offset"] == pytest.approx(12e-9)  # local - master = -12 ns -> reference - local = +12 ns
    assert d["mean_path_delay"] == pytest.approx(597e-9)
    assert d["master_offset"] == pytest.approx(-13e-9)
    assert d["steps_removed"] == 1 and d["gm_present"] == 1 and d["gm_identity"] == "aabbcc.fffe.ddeeff"
    with pytest.raises(sources.SourceError):
        sources.parse_pmc("sending: GET CURRENT_DATA_SET\n")


def test_ptpcheck_stats_parser():
    d = sources.parse_ptpcheck_stats('{"ptp.offset_ns":-25,"ptp.mean_path_delay_ns":410,"ptp.steps_removed":2,'
                                     '"ptp.gm_present":1}\n')
    assert d["offset"] == pytest.approx(25e-9) and d["mean_path_delay"] == pytest.approx(410e-9)
    with pytest.raises(sources.SourceError):
        sources.parse_ptpcheck_stats("not json")


def test_localwatch_ptp4l_with_fake_command(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "_run", lambda cmd, timeout=5.0: PMC)
    out = tmp_path / "w.csv"
    w = sources.LocalWatch("ptp4l", interval=0.01, out_path=str(out), count=3)
    w.run()
    lines = out.read_text().splitlines()
    assert lines[0].startswith("unix_time,offset,mean_path_delay") and len(lines) == 4
    (s,) = load(str(out))
    assert s.offset[0] == pytest.approx(12e-9)


# ------------------------------------------------------------------ w32tm
W32_TEXT = """Tracking time.windows.com [20.101.57.9:123].
Collecting 4 samples.
The current time is 9/30/2026 11:59:58 PM.
23:59:58, d:+00.0541615s o:-00.0031265s
23:59:59, d:+00.0540000s o:-00.0031000s
00:00:00, error: 0x800705B4
00:00:01, d:+00.0539000s o:-00.0030000s
"""


def test_w32tm_dataonly_with_date_and_midnight():
    assert detect_format(W32_TEXT.splitlines()) == "w32tm"
    (s,) = load(W32_TEXT)
    assert len(s) == 3 and s.meta["peer"] == "time.windows.com"
    assert s.offset[0] == pytest.approx(-0.0031265) and s.extra["delay"][0] == pytest.approx(0.0541615)
    assert s.t[-1] - s.t[0] == pytest.approx(3.0)  # rolled over midnight
    import datetime as dt
    assert dt.datetime.fromtimestamp(s.t[0], dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") == "2026-09-30 23:59:58"


def test_w32tm_old_style_and_rdtsc():
    (s,) = load("Tracking 192.0.2.1.\n12:00:00, +00.0010000s\n12:00:02, +00.0012000s\n12:00:04, +00.0011000s\n")
    assert len(s) == 3 and "note" in s.meta
    ft = (1_800_000_000 + 11644473600) * 10**7
    rd = "RdtscStart,RdtscEnd,FileTime,RoundtripDelay,NtpOffset\n" + "".join(
        f"{100 + i},{200 + i},{ft + i * 2 * 10**7},0.0100000,{0.001 * i:.7f}\n" for i in range(4))
    (r,) = load(rd)
    assert r.meta["mode"] == "rdtsc" and r.t[0] == pytest.approx(1_800_000_000)
    np.testing.assert_allclose(r.offset, [0, 0.001, 0.002, 0.003])


# ------------------------------------------------------------- prometheus
def prom_doc():
    vals = [[1.8e9 + 60 * i, str(1e-5 * np.sin(i))] for i in range(30)]
    return {"status": "success", "data": {"resultType": "matrix", "result": [
        {"metric": {"__name__": "ntp_source_offset_seconds", "name": "ntp.example:123", "address": "192.0.2.5:123"},
         "values": vals},
        {"metric": {"__name__": "ntp_source_offset_seconds", "name": "b.example:123"}, "values": vals[:10]}]}}


def test_prometheus_json_file(tmp_path):
    p = tmp_path / "prom.json"
    p.write_text(json.dumps(prom_doc()))
    a, b = load(str(p))
    assert a.source_format == "prometheus" and len(a) == 30 and a.meta["peer"] == "ntp.example:123"
    assert len(b) == 10


def test_prom_command_against_fake_server(tmp_path, capsys):
    doc = prom_doc()
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["path"] = self.path
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = tmp_path / "o.json"
        main(["prom", f"http://127.0.0.1:{srv.server_address[1]}", "ntp_source_offset_seconds", "--since", "1h",
              "-o", str(out)])
        assert "/api/v1/query_range?query=ntp_source_offset_seconds" in seen["path"]
        main(["info", str(out), "--all-peers"])
        assert "ntp.example:123" in capsys.readouterr().out
    finally:
        srv.shutdown()
    with pytest.raises(SystemExit):
        main(["prom", "ftp://x", "q"])


# ----------------------------------------------------------------- bounds
def test_clockbound_lines_and_validation():
    t0 = 1.8e9
    # exact decimal strings, as ClockBound prints them (ns digits)
    lines = [f'When clockbound_now was called true time was somewhere within {int(t0) + i - 1}.999500000 and '
             f'{int(t0) + i}.000500000 seconds since Jan 1 1970. The clock status is "Synchronized".' for i in range(100)]
    assert detect_format(lines) == "bounds"
    (b,) = parse_bounds(lines)
    assert b.meta["bounds_source"] == "clockbound" and b.meta["statuses"] == ["Synchronized"]
    np.testing.assert_allclose(b.extra["bound"], 5e-4, rtol=1e-12)
    tt = t0 + np.arange(0, 100, 0.5)
    good = TimeSeries(tt, np.full(tt.size, 1e-4))  # true time 100 us ahead: inside +-500 us
    r = validate(b, good)
    assert r["compared"] == 100 and r["violations"] == 0 and r["inside"] == 100
    assert r["tightness"] == pytest.approx(0.2, rel=1e-3)
    bad = TimeSeries(tt, np.where(tt > t0 + 50, 2e-3, 1e-4))
    r2 = validate(b, bad)
    assert r2["violations"] == 49 and r2["violation_rate"] == pytest.approx(0.49)
    fuzzy = TimeSeries(tt, np.full(tt.size, 4.5e-4), extra={"delay": np.full(tt.size, 2e-4)})
    r3 = validate(b, fuzzy)
    assert r3["indeterminate"] == 100  # |error| 450 us, bound 500 us, reference +-100 us


def test_bounds_csv_with_local_time(tmp_path, capsys):
    t0 = 1.8e9
    rows = ["unix_time,earliest,latest,status"] + [
        f"{t0 + i},{t0 + i + 2e-3 - 1e-3},{t0 + i + 2e-3 + 1e-3},Synchronized" for i in range(60)]
    bp = tmp_path / "b.csv"
    bp.write_text("\n".join(rows) + "\n")
    (b,) = load(str(bp))
    np.testing.assert_allclose(b.offset, 2e-3, atol=1e-6)  # window centred 2 ms ahead of local time
    ref = tmp_path / "ref.csv"
    ref.write_text("unix_time,offset\n" + "".join(f"{t0 + i},{2.2e-3}\n" for i in range(60)))
    assert main(["bounds", str(bp), str(ref)]) == 0
    assert "[PASS]" in capsys.readouterr().out
    ref.write_text("unix_time,offset\n" + "".join(f"{t0 + i},{5e-3}\n" for i in range(60)))
    assert main(["bounds", str(bp), str(ref), "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["violations"] == 60


# --------------------------------------------------------------- profiles
def test_builtin_tic_profile_and_cli(tmp_path, capsys):
    p = tmp_path / "tic.txt"
    p.write_text("# 53230A export\n" + "".join(f"{v}\n" for v in [12.0, 13.0, 11.0, 12.5] * 10))
    (s,) = load(str(p), fmt="profile:tic-ns")
    assert s.offset[0] == pytest.approx(-12e-9) and s.meta["synthetic_time"] is True
    assert main(["timeerror", str(p), "-f", "profile:tic-ns", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["cte"] == pytest.approx(12.125e-9)


def test_user_profile_toml_with_header_iso_and_extras(tmp_path):
    prof = tmp_path / "vendor.toml"
    prof.write_text('name = "vendor-x"\nvalue_column = "TE (ns)"\nunits = "ns"\nquantity = "te"\n'
                    'time_column = "Timestamp"\ntime_format = "iso"\nskip_rows = 2\ndelimiter = ";"\n'
                    'extra_columns = ["Temp"]\n')
    data = tmp_path / "x.csv"
    data.write_text("Instrument X v1.2\nexported 2026-09-30\nTimestamp;TE (ns);Temp\n" + "".join(
        f"2026-09-30T12:00:{i:02d}Z;{i};{20 + i / 10}\n" for i in range(20)))
    (s,) = load(str(data), fmt=f"profile:{prof}")
    assert s.source_format == "profile:vendor-x" and len(s) == 20
    assert s.offset[3] == pytest.approx(-3e-9) and s.extra["Temp"][0] == pytest.approx(20.0)
    assert s.t[1] - s.t[0] == pytest.approx(1.0)


def test_profile_errors(tmp_path):
    with pytest.raises(ValueError):
        load_profile("no-such-profile")
    bad = tmp_path / "bad.toml"
    bad.write_text('value_column = 0\nunits = "furlongs"\n')
    with pytest.raises(ValueError):
        load_profile(str(bad))
    with pytest.raises(ValueError):
        parse_with_profile(["1", "2"], {"name": "x", "value_column": 0})  # no time, no tau0
    with pytest.raises(ParseError):
        load("a,b\nx,y\n", fmt="profile:te-csv")


def test_negate_flag(capsys, tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("unix_time,offset\n" + "".join(f"{i},{1e-3}\n" for i in range(10)))
    main(["info", str(p), "--negate", "--json"])
    assert json.loads(capsys.readouterr().out)[0]["mean"] == pytest.approx(-1e-3)
