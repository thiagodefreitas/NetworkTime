# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ntpstats.cli import main
from ntpstats.web import server as web

EX = os.path.join(os.path.dirname(__file__), os.pardir, "examples", "data")


def test_cli_info_json(capsys):
    assert main(["info", os.path.join(EX, "loopstats.2012"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["samples"] == 52


def test_cli_stability_table_and_csv(capsys):
    main(["stability", os.path.join(EX, "peerstats.example"), "--peer", "192.0.2.10", "-k", "oadev,tdev,mtie"])
    out = capsys.readouterr().out
    assert "Allan deviation (overlapping)" in out and "Time deviation" in out and "white PM" in out
    main(["stability", os.path.join(EX, "chrony-tracking.log"), "--csv", "-k", "mdev"])
    assert capsys.readouterr().out.startswith("tau,mdev,err,n,lo,hi,edf,alpha")


def test_cli_network_filter_simulate(capsys, tmp_path):
    main(["network", os.path.join(EX, "chrony-measurements.log"), "--all-peers"])
    assert "floor" in capsys.readouterr().out
    out = tmp_path / "f.csv"
    main(["filter", os.path.join(EX, "peerstats.example"), "-m", "rts", "-o", str(out)])
    assert out.read_text().startswith("unix_time,offset")
    main(["simulate", "--preset", "lan", "--duration", "3600", "--benchmark"])
    assert "min-delay filter" in capsys.readouterr().out


def test_cli_plot(tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "r.png"
    main(["plot", os.path.join(EX, "peerstats.example"), "--all-peers", "-o", str(out)])
    assert out.stat().st_size > 10000


def test_cli_time_filter(capsys):
    main(["info", os.path.join(EX, "peerstats.example"), "--start", "2023-11-15T00:00:00", "--json"])
    s = json.loads(capsys.readouterr().out)[0]
    assert s["start"] >= 1700006400


# ------------------------------------------------------------------ web API
@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(url, data=None, method=None, headers=None, raw=False):
    h = {"X-NTPStats": "1"}
    h.update(headers or {})
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    with urllib.request.urlopen(req) as r:
        payload = r.read()
        return payload.decode() if raw else json.loads(payload)


def test_web_static_and_info(base_url):
    html = call(base_url + "/", raw=True)
    assert "uPlot.iife.min.js" in html and "Thiago de Freitas" in html
    assert "uPlot" in call(base_url + "/vendor/uPlot.iife.min.js", raw=True)[:2000]
    assert "oadev" in call(base_url + "/api/info")["kinds"]


def test_web_upload_and_analyses(base_url):
    text = open(os.path.join(EX, "peerstats.example"), "rb").read()
    ds = call(base_url + "/api/upload", data=text, headers={"X-Filename": "peerstats"})
    assert len(ds) == 2
    sid = ds[0]["id"]
    s = call(f"{base_url}/api/series/{sid}?detrend=linear&overlay=kalman&max_points=200")
    assert len(s["t"]) <= 204 and s["overlay"]["label"] == "Kalman filter"
    st = call(f"{base_url}/api/stability/{sid}?kinds=oadev,mdev,mtie&ci=0.95")
    assert [r["kind"] for r in st["results"]] == ["oadev", "mdev", "mtie"]
    assert st["results"][0]["lo"][0] < st["results"][0]["dev"][0] < st["results"][0]["hi"][0]
    net = call(f"{base_url}/api/network/{sid}")
    assert net["stats"]["delay_min"] > 0 and net["fpp"]["pct"]
    hist = call(f"{base_url}/api/histogram/{sid}?bins=20")
    assert len(hist["centers"]) == 20
    csv = call(f"{base_url}/api/export/{sid}/stability.csv?kinds=oadev", raw=True)
    assert csv.startswith("kind,tau,dev")


def test_web_simulate_and_delete(base_url):
    ds = call(base_url + "/api/simulate", data={"preset": "lan", "duration": 3600})
    sid = ds[0]["id"]
    s = call(f"{base_url}/api/series/{sid}?overlay=mindelay")
    assert "truth" in s and s["overlay"]["label"] == "min-delay filter"
    assert call(f"{base_url}/api/datasets/{sid}", method="DELETE")["deleted"]


def test_web_security(base_url):
    # POST without the custom header (what a cross-site form would send) is refused.
    req = urllib.request.Request(base_url + "/api/simulate", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    # DNS-rebinding style foreign Host header is refused.
    req = urllib.request.Request(base_url + "/api/datasets", headers={"Host": "evil.example:80"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    # Path traversal on static files.
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base_url + "/static/..%2F..%2Fcli.py")
    assert e.value.code == 404


def test_web_errors(base_url):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base_url + "/api/series/nope")
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base_url + "/api/upload", data=b"hello world\n", headers={"X-Filename": "junk"})
    assert e.value.code == 400


# ------------------------------------------------------------ 2.1 - 2.3 commands
def test_cli_mask_exit_code(tmp_path, capsys):
    mask = tmp_path / "m.csv"
    mask.write_text("tau,oadev\n64,1e-9\n10000,1e-9\n")  # impossible OADEV limit -> FAIL
    rc = main(["stability", os.path.join(EX, "peerstats.example"), "--peer", "192.0.2.10", "-k", "oadev", "--mask", str(mask)])
    assert rc == 3 and "FAIL" in capsys.readouterr().out


def test_cli_dynamic_and_report(tmp_path, capsys):
    main(["dynamic", os.path.join(EX, "chrony-tracking.log"), "-k", "mdev"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith("time,") and len(lines) > 5
    out = tmp_path / "r.html"
    main(["report", os.path.join(EX, "linuxptp.log"), "--all-peers", "-o", str(out)])
    assert out.stat().st_size > 50_000 and "ptp4l" in out.read_text()


def test_cli_bench(tmp_path, capsys):
    html = tmp_path / "b.html"
    csvp = tmp_path / "b.csv"
    assert main(["bench", "lan", "--seeds", "1-2", "--duration", "1800", "--warmup", "300",
                 "-e", "raw,mindelay", "--csv", str(csvp), "--html", str(html)]) == 0
    out = capsys.readouterr().out
    assert "mindelay" in out and csvp.read_text().count("\n") == 5 and html.exists()
    main(["bench", "--list"])
    assert "rfc5905" in capsys.readouterr().out


def test_cli_query_fake_server(capsys):
    from test_sntp import FakeServer

    srv = FakeServer(offset=0.5)
    srv.start()
    try:
        import ntpstats.sntp as sn

        real = sn.query
        sn_query = lambda host, **kw: real("127.0.0.1", port=srv.port, **{k: v for k, v in kw.items() if k != "port"})  # noqa: E731
        import ntpstats.cli as cli_mod

        orig = sn.query
        sn.query = sn_query
        try:
            assert cli_mod.main(["query", "fake.example", "--json"]) == 0
        finally:
            sn.query = orig
        r = json.loads(capsys.readouterr().out.splitlines()[0])
        assert abs(r["offset"] - 0.5) < 0.01
    finally:
        srv.close()


def test_cli_info_pcap_and_ptp(capsys):
    main(["info", os.path.join(EX, "ntp-capture.pcap"), os.path.join(EX, "linuxptp.log"), "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert {r["format"] for r in rows} == {"pcap", "linuxptp"}


def test_web_mask_dynamic_report(base_url):
    ds = call(base_url + "/api/simulate", data={"preset": "internet", "duration": 6 * 3600})
    sid = ds[0]["id"]
    m = call(base_url + "/api/mask", data=b"tau,oadev\n64,1\n100000,1\n", headers={"X-Filename": "loose.csv"})
    assert m["kind"] == "oadev"
    st = call(f"{base_url}/api/stability/{sid}?kinds=oadev&mask={m['id']}")
    assert st["results"][0]["mask"]["passed"] is True
    d = call(f"{base_url}/api/dynamic/{sid}?kind=oadev")
    assert len(d["times"]) > 3 and len(d["dev"][0]) == len(d["taus"])
    html = call(f"{base_url}/api/export/{sid}/report.html?kinds=oadev,tdev", raw=True)
    assert html.startswith("<!doctype html>") and "const REPORT=" in html


def test_web_upload_pcap_binary(base_url):
    data = open(os.path.join(EX, "ntp-capture.pcap"), "rb").read()
    ds = call(base_url + "/api/upload", data=data, headers={"X-Filename": "cap.pcap"})
    assert ds[0]["format"] == "pcap" and ds[0]["samples"] == 240


def test_web_monitor_local_watch(base_url, tmp_path, monkeypatch):
    import sys as _sys

    from test_sources import TRACKING

    from ntpstats import sources

    fake = tmp_path / "chronyc.py"
    fake.write_text(f"print({TRACKING!r}, end='')\n")
    monkeypatch.setattr(sources, "sample_chrony", lambda cmd=None: sources.parse_chronyc_tracking(
        sources._run([_sys.executable, str(fake)])) | {"time": __import__("time").time()})
    r = call(base_url + "/api/monitor/start", data={"source": "chrony", "interval": 1})
    import time as _t

    for _ in range(30):
        if call(base_url + "/api/monitor")["samples"] >= 1:
            break
        _t.sleep(0.1)
    st = call(base_url + "/api/monitor")
    assert st["running"] and st["servers"] == ["local chrony"] and st["samples"] >= 1
    call(base_url + "/api/monitor/stop", data={})
    ds = {d["id"]: d for d in call(base_url + "/api/datasets")}
    assert ds[r["id"]]["samples"] >= 1 and "frequency_ppm" in ds[r["id"]]["columns"]


# ------------------------------------------------------------ review regressions
def test_web_content_disposition_is_safe(base_url):
    ds = call(base_url + "/api/upload", data=b"unix_time,offset\n1,0\n2,0\n3,0\n4,0\n",
              headers={"X-Filename": "a%0d%0aSet-Cookie:%20x=1%E6%97%A5.csv"})
    req = urllib.request.Request(f"{base_url}/api/export/{ds[0]['id']}/series.csv")
    with urllib.request.urlopen(req) as r:
        assert r.headers.get("Set-Cookie") is None
        cd = r.headers["Content-Disposition"]
        assert "\r" not in cd and "\n" not in cd and "filename*=UTF-8''" in cd
        r.read()


def test_web_negative_content_length_rejected(base_url):
    import http.client

    host, port = base_url.split("//")[1].split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=5)
    c.putrequest("POST", "/api/simulate")
    c.putheader("X-NTPStats", "1")
    c.putheader("Content-Length", "-1")
    c.endheaders()
    assert c.getresponse().status == 400


def test_web_mask_is_never_read_from_server_path(base_url, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("1 2\n3 4\n")
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base_url + "/api/mask", data=str(secret).encode(), headers={"X-Filename": "m"})
    assert e.value.code == 400
    ok = call(base_url + "/api/mask", data=b"10 1e-6", headers={"X-Filename": "one-line"})  # single-line mask text
    assert ok["taus"] == [10.0]


def test_mask_applies_to_its_kind_only(capsys, tmp_path):
    mask = tmp_path / "t.csv"
    mask.write_text("tau,tdev\n64,1e-12\n10000,1e-12\n")  # TDEV mask: must not judge OADEV
    rc = main(["stability", os.path.join(EX, "peerstats.example"), "--peer", "192.0.2.10", "-k", "oadev", "--mask", str(mask)])
    assert rc == 0 and "not computed" in capsys.readouterr().err


def test_simulate_does_not_mutate_presets():
    from ntpstats.simulate import PRESETS

    before = PRESETS["internet"].duration
    main(["simulate", "--duration", "600"])
    assert PRESETS["internet"].duration == before


def test_report_with_ci_off(tmp_path):
    out = tmp_path / "r.html"
    main(["report", os.path.join(EX, "chrony-tracking.log"), "--ci", "0", "-o", str(out)])
    assert "CI off" in out.read_text()


def test_cli_compare(tmp_path, capsys):
    from ntpstats.simulate import PRESETS, simulate_ntp

    meas, truth = simulate_ntp(PRESETS["lan"])
    a, b = tmp_path / "meas.csv", tmp_path / "truth.csv"
    meas.to_csv(str(a))
    truth.to_csv(str(b))
    assert main(["compare", str(a), str(b), "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["samples"] == len(meas) and r["rms"] < 1e-4 and r["tdev"]["taus"] and r["mtie"]["dev"]
