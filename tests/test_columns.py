# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""3.8: column mapping without a profile file (--columns, ntpstats columns, the UI dialog) (#35)."""

import json

import pytest

from ntpstats.cli import main
from ntpstats.parsers import ParseError, load
from ntpstats.profiles import columns_profile, columns_spec, guess_columns, load_profile, profile_toml
from ntpstats.web import server as S

INSTRUMENT = "# exported\nTime,TIE (ns),Delay (ns),Status\n" + "".join(
    f"2026-10-20T10:00:{k:02d}Z,{12 + k % 3},{1520 + k},OK\n" for k in range(20))


def test_columns_spec_parses_every_key():
    p = columns_profile("time=Time:iso,te=TIE (ns),units=ns,extra=Delay+3,delimiter=semicolon,skip=2,header=yes")
    assert p == {"name": "columns", "time_column": "Time", "time_format": "iso", "value_column": "TIE (ns)",
                 "quantity": "te", "units": "ns", "extra_columns": ["Delay", 3], "delimiter": ";", "skip_rows": 2,
                 "header": True}
    p = columns_profile("offset=1,tau0=0.5,delimiter=tab")
    assert p["value_column"] == 1 and p["quantity"] == "offset" and p["tau0"] == 0.5 and p["delimiter"] == "\t"
    assert columns_profile("time=0:mjd,value=2,quantity=te")["time_format"] == "mjd"


@pytest.mark.parametrize("bad", ["time=0", "nope=1", "value=1,units=furlongs", "value=1,quantity=x", "value"])
def test_columns_spec_errors(bad):
    with pytest.raises(ValueError):
        columns_profile(bad)


def test_spec_and_toml_round_trip(tmp_path):
    p = columns_profile("time=Time:iso,te=TIE,units=ns,extra=Delay,delimiter=comma")
    assert columns_profile(columns_spec(p)) == p
    f = tmp_path / "p.toml"
    f.write_text(profile_toml(dict(p, name="vendor", description='say "hi"')))
    try:
        q = load_profile(str(f))
    except ImportError:  # Python < 3.11 without tomli
        pytest.skip("no TOML reader")
    assert q == dict(p, name="vendor", description='say "hi"')


def test_guess_instrument_export():
    g = guess_columns(INSTRUMENT.splitlines())
    p = g["profile"]
    assert (p["time_column"], p["time_format"], p["value_column"], p["units"], p["quantity"]) == \
        ("Time", "iso", "TIE (ns)", "ns", "te")
    assert p["extra_columns"] == ["Delay (ns)"] and [c["kind"] for c in g["columns"]] == ["iso", "number", "number", "text"]
    assert g["spec"].startswith("time=Time:iso,te=TIE (ns),units=ns")


def test_guess_headerless_unix_mjd_elapsed_and_offsets():
    g = guess_columns([f"{1761000000 + k} {1e-5 * (k % 3)}" for k in range(10)])
    assert g["profile"]["time_column"] == 0 and g["profile"]["time_format"] == "unix" and g["profile"]["units"] == "s"
    assert g["header"] is None
    g = guess_columns([f"{61000 + k / 86400:.8f};{k % 5 * 10}" for k in range(10)])
    assert g["profile"]["time_format"] == "mjd" and g["profile"]["delimiter"] == ";" and g["profile"]["units"] == "ns"
    g = guess_columns(["elapsed_s,offset_us"] + [f"{k * 2},{k % 4}" for k in range(10)])
    p = g["profile"]
    assert (p["time_format"], p["units"], p["quantity"], p["value_column"]) == ("elapsed", "us", "offset", "offset_us")
    g = guess_columns([f"{12 + k % 3}" for k in range(10)])
    assert "time_column" not in g["profile"] and g["profile"]["tau0"] == 1.0
    with pytest.raises(ValueError):
        guess_columns(["a,b", "x,y"])


def test_load_with_columns_format(tmp_path):
    f = tmp_path / "i.csv"
    f.write_text(INSTRUMENT)
    with pytest.raises(ParseError, match="--columns"):  # the generic CSV reader explains what to do
        load(str(f))
    (s,) = load(str(f), fmt="columns:time=Time:iso,te=TIE (ns),units=ns,extra=Delay (ns)")
    assert len(s) == 20 and s.offset[0] == pytest.approx(-12e-9) and s.extra["Delay (ns)"][1] == 1521
    assert s.t[1] - s.t[0] == pytest.approx(1.0)


def test_cli_columns_command_and_option(tmp_path, capsys):
    f = tmp_path / "i.csv"
    f.write_text(INSTRUMENT)
    prof = tmp_path / "vendor.toml"
    assert main(["columns", str(f), "--save", str(prof), "--name", "vendor"]) == 0
    out = capsys.readouterr().out
    assert "--columns 'time=Time:iso,te=TIE (ns),units=ns" in out and "20 samples" in out
    assert main(["columns", str(f), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["profile"]["units"] == "ns"
    assert main(["timeerror", str(f), "--columns", "time=Time:iso,te=TIE (ns),units=ns", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["max_abs_te"] == pytest.approx(14e-9)
    if prof.exists():
        try:
            assert main(["info", str(f), "-f", f"profile:{prof}"]) == 0
        except ImportError:
            pass
    with pytest.raises(SystemExit):
        main(["info", str(f), "--columns", "nope=1"])
    with pytest.raises(SystemExit, match="exclusive"):
        main(["info", str(f), "--columns", "value=1", "-f", "csv"])


def test_web_columns_endpoint_and_upload():
    r = S.dispatch("POST", "/api/columns", {"X-NTPStats": "1"}, INSTRUMENT.encode())
    g = json.loads(r.body)
    assert r.status == 200 and g["profile"]["value_column"] == "TIE (ns)" and len(g["rows"]) == 5
    r = S.dispatch("POST", "/api/upload?format=" + "columns:time=0:iso,te=1,units=ns",
                   {"X-NTPStats": "1", "x-filename": "i.csv"}, INSTRUMENT.encode())
    assert r.status == 200 and json.loads(r.body)[0]["samples"] == 20
    r = S.dispatch("POST", "/api/columns", {"X-NTPStats": "1"}, b"a,b\nx,y\n")
    assert r.status == 400
