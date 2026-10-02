#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Regenerate the README screenshots (needs `pip install playwright` + Chromium).

    python docs/make_screenshots.py [output_dir]
"""

import glob
import os
import sys
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from ntpstats.parsers import load
from ntpstats.web import server as web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "img")

for s in load(os.path.join(ROOT, "examples", "data", "peerstats.example")):
    web.STORE.add(s)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{httpd.server_address[1]}/"

exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome") or [None])[0]


def shot(page, name, wait=900):
    page.wait_for_timeout(wait)
    page.screenshot(path=f"{OUT}/{name}.png")


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    for theme in ("light", "dark"):
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=theme,
                                bypass_csp=True)  # waits below use eval
        errors = []
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        if theme == "light":
            page.goto(url + "#/analyze/overview")
            shot(page, "ui-welcome", 600)
        page.goto(url + "#/lab/simulate")
        page.wait_for_timeout(600)
        # simulated dataset with ground truth
        page.click("#presets [data-preset=internet]")
        page.wait_for_function("location.hash === '#/analyze/offset'")
        page.select_option("#detrend", "linear")
        page.select_option("#overlay", "rts")
        shot(page, f"ui-offset-{theme}", 3400)  # after the toast
        if theme == "dark":
            break
        page.goto(url + "#/analyze/stability")
        page.click("#kinds button[data-kind=tdev]")
        page.check("#slopes")
        shot(page, "ui-stability")
        page.goto(url + "#/analyze/network")
        shot(page, "ui-network")
        page.goto(url + "#/comply/audit")
        page.fill("#au-limit", "10ms")
        page.press("#au-limit", "Enter")
        page.dispatch_event("#au-limit", "change")
        shot(page, "ui-audit", 1400)
        page.goto(url + "#/lab/chain")
        page.fill("#ch-hops", "12")
        page.click("#ch-run")
        page.wait_for_selector("#ch-table table", timeout=120000)
        shot(page, "ui-chain")
        # compare the two peers from the peerstats example
        page.goto(url + "#/analyze/overview")
        page.click(".datasets li:nth-child(1) .nm")
        page.click(".datasets li:nth-child(2) input")
        page.goto(url + "#/analyze/stability")
        shot(page, "ui-stability-compare")
        page.goto(url + "#/analyze/overview")
        shot(page, "ui-overview-compare")
        page.keyboard.press("Control+k")
        page.keyboard.type("time")
        shot(page, "ui-palette", 400)
        page.keyboard.press("Escape")
        if errors:
            raise SystemExit(f"page errors: {errors}")
    browser.close()
httpd.shutdown()
print("screenshots written to", OUT)
