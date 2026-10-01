# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""In-browser edition (#31): the Pyodide page gives the same numbers as the installed package.

Needs Playwright with Chromium, network access to the Pyodide CDN and ``python docs/build_app.py``.
Runs when NTPSTATS_BROWSER_TEST=1 (the CI "browser" job); skipped otherwise.
"""

import functools
import glob
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "docs", "app")
pytestmark = pytest.mark.skipif(os.environ.get("NTPSTATS_BROWSER_TEST") != "1",
                                reason="set NTPSTATS_BROWSER_TEST=1 (needs Playwright, Chromium and the Pyodide CDN)")
FILES = ["loopstats.2012", "peerstats.example", "chrony-tracking.log", "ptp-capture.pcapng"]


@pytest.fixture(scope="module")
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    assert os.path.isfile(os.path.join(APP, "index.html")), "run python docs/build_app.py first"
    handler = functools.partial(SimpleHTTPRequestHandler, directory=APP)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    kw = {}
    exe = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
    if exe:
        kw["executable_path"] = exe[0]
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        kw["proxy"] = {"server": proxy, "bypass": "127.0.0.1,localhost"}
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(**kw)
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://127.0.0.1:{httpd.server_address[1]}/index.html")
        pg.wait_for_function("window.NTPSTATS_READY !== undefined")
        pg.evaluate("window.NTPSTATS_READY", None)  # waits for Pyodide, numpy and the wheel
        pg.errors = errors
        yield pg
        browser.close()
    httpd.shutdown()


def call(pg, method, path, body=None):
    out = pg.evaluate("""async ([m, p, b]) => {
        const r = await window.NTPSTATS_TRANSPORT(m, p, {"X-NTPStats": "1", "X-Filename": "f"}, b === null ? null
                    : Uint8Array.from(atob(b), c => c.charCodeAt(0)).buffer);
        return {status: r.status, type: r.contentType, text: new TextDecoder().decode(r.bytes)};
    }""", [method, path, body])
    return out


def close(a, b, rel=1e-9, path="$"):
    """Same structure; numbers equal to ``rel`` (WebAssembly and native numpy differ in the last bits)."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), path
        for k in a:
            close(a[k], b[k], rel, f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            close(x, y, rel, f"{path}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert b == pytest.approx(a, rel=rel, abs=1e-12), path  # 1 ps: zero up to rounding
    else:
        assert a == b, path


def local(method, path, body=b""):
    from ntpstats.web import server

    r = server.dispatch(method, path, {"X-Filename": "f"}, body)
    return r.status, r.body.decode()


@pytest.mark.parametrize("name", FILES)
def test_same_numbers_as_the_installed_package(page, name):
    import base64

    from ntpstats.web import server

    raw = open(os.path.join(ROOT, "examples", "data", name), "rb").read()
    up = call(page, "POST", "/api/upload?format=auto", base64.b64encode(raw).decode())
    assert up["status"] == 200, up["text"]
    bid = json.loads(up["text"])[0]["id"]
    server.STORE.datasets.clear()
    st, txt = local("POST", "/api/upload?format=auto", raw)
    lid = json.loads(txt)[0]["id"]
    for q in ("stability/{}?kinds=oadev,mdev,tdev&taus=octave&ci=0.683", "series/{}?max_points=500", "network/{}",
              "timeerror/{}"):
        b = call(page, "GET", "/api/" + q.format(bid))
        ls, lt = local("GET", "/api/" + q.format(lid))
        assert b["status"] == ls
        if ls == 200:
            bj, lj = json.loads(b["text"]), json.loads(lt)
            bj.pop("id", None), lj.pop("id", None)
            close(lj, bj)


def test_report_download_and_no_live_features(page):
    info = json.loads(call(page, "GET", "/api/info")["text"])
    assert info["live"] is False and any(f["name"] == "cggtts" for f in info["formats"])
    sim = call(page, "POST", "/api/simulate", None)
    assert sim["status"] in (200, 400)
    ds = json.loads(call(page, "GET", "/api/datasets")["text"])
    r = call(page, "GET", f"/api/export/{ds[0]['id']}/report.html?kinds=oadev")
    assert r["status"] == 200 and "<html" in r["text"].lower()
    assert not page.errors
