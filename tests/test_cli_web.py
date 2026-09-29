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
