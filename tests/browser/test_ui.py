# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""The web UI in a real browser: every page renders without script errors (Playwright, Chromium).

Runs when NTPSTATS_BROWSER_TEST=1 (the CI "browser" job); skipped otherwise.
"""

import glob
import os
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EX = os.path.join(ROOT, "examples", "data")
pytestmark = pytest.mark.skipif(os.environ.get("NTPSTATS_BROWSER_TEST") != "1",
                                reason="set NTPSTATS_BROWSER_TEST=1 (needs Playwright and Chromium)")
PAGES = ["analyze/overview", "analyze/offset", "analyze/stability", "analyze/distribution", "analyze/network",
         "analyze/spectrum", "analyze/holdover", "analyze/events", "compare/table", "compare/reference", "compare/hat",
         "comply/timeerror", "comply/audit", "lab/simulate", "lab/bench", "lab/chain", "live/monitor"]


@pytest.fixture(scope="module")
def ui():
    sync_api = pytest.importorskip("playwright.sync_api")
    from http.server import ThreadingHTTPServer

    from ntpstats.web import server

    server.STORE.datasets.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    kw = {}
    exe = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
    if exe:
        kw["executable_path"] = exe[0]
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(**kw)
        page = browser.new_page(viewport={"width": 1400, "height": 900}, bypass_csp=True)  # waits use eval
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.base = f"http://127.0.0.1:{httpd.server_address[1]}/"
        page.errors = errors
        yield page
        browser.close()
    httpd.shutdown()


def test_every_page_renders(ui):
    ui.goto(ui.base)
    ui.wait_for_selector("#empty-side:not([hidden])")
    ui.set_input_files("#file-input", [os.path.join(EX, "chrony-measurements.log")])
    ui.wait_for_selector("#datasets li", timeout=20000)
    for seed in (1, 2):
        ui.goto(ui.base + "#/lab/simulate")
        ui.fill("#sim-hours", "6")
        ui.fill("#sim-seed", str(seed))
        ui.click("#presets [data-preset=internet]")
        ui.wait_for_function(f"document.querySelectorAll('#datasets li').length >= {2 + seed}", timeout=20000)
    for box in ui.query_selector_all("#datasets li input:not([disabled])")[-2:]:
        box.check()
    for page in PAGES:
        ui.goto(ui.base + "#/" + page)
        ui.wait_for_timeout(700)
        ui.wait_for_function("document.querySelectorAll('.page.active .chart.loading').length === 0", timeout=30000)
        assert ui.evaluate("document.querySelector('.page.active').dataset.page") == page
    assert not ui.errors, ui.errors


def test_charts_and_lab_runs(ui):
    ui.goto(ui.base + "#/analyze/stability")
    ui.wait_for_selector("#chart-stability canvas", timeout=20000)
    ui.goto(ui.base + "#/comply/audit")
    ui.wait_for_selector("#au-verdict .verdict", timeout=20000)
    ui.goto(ui.base + "#/compare/hat")
    ui.wait_for_selector("#chart-hat canvas", timeout=30000)
    ui.goto(ui.base + "#/lab/chain")
    ui.select_option("#ch-dur", "600")
    ui.fill("#ch-hops", "3")
    ui.click("#ch-run")
    ui.wait_for_selector("#ch-table table", timeout=60000)
    ui.goto(ui.base + "#/lab/bench")
    ui.fill("#bench-hours", "2")
    ui.fill("#bench-seeds", "1")
    ui.click("#bench-run")
    ui.wait_for_selector("#bench-table table", timeout=120000)
    assert not ui.errors, ui.errors


def test_palette_keyboard_and_theme(ui):
    ui.goto(ui.base + "#/analyze/overview")
    ui.keyboard.press("Control+k")
    ui.keyboard.type("audit")
    ui.keyboard.press("Enter")
    ui.wait_for_function("location.hash === '#/comply/audit'")
    ui.keyboard.press("4")
    ui.wait_for_timeout(500)
    assert ui.evaluate("location.hash").startswith("#/lab/")
    ui.keyboard.press("t")
    assert ui.evaluate("document.documentElement.dataset.theme") in ("light", "dark")
    ui.keyboard.press("?")
    assert ui.evaluate("document.querySelector('#help').open")
    assert not ui.errors, ui.errors
