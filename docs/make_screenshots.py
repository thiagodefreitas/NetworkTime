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
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    for theme in ("light", "dark"):
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=theme)
        errors = []
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        page.goto(url)
        page.wait_for_timeout(600)
        if theme == "light":
            page.screenshot(path=f"{OUT}/ui-welcome.png")
        # simulated dataset with ground truth
        page.click("text=Simulate")
        page.select_option("#dlg-sim select[name=preset]", "internet")
        page.click("#dlg-sim button[value=ok]")
        page.wait_for_timeout(900)
        page.select_option("#detrend", "linear")
        page.select_option("#overlay", "rts")
        page.wait_for_timeout(1200)
        page.screenshot(path=f"{OUT}/ui-offset-{theme}.png")
        if theme == "dark":
            break
        page.click("[data-tab=stability]")
        page.click("#kinds button[data-kind=tdev]")
        page.wait_for_timeout(300)
        page.check("#slopes")
        page.wait_for_timeout(900)
        page.screenshot(path=f"{OUT}/ui-stability.png")
        page.click("[data-tab=network]")
        page.wait_for_timeout(900)
        page.screenshot(path=f"{OUT}/ui-network.png")
        # compare the two peers from the peerstats example
        page.click(".datasets li:nth-child(1) .nm")
        page.click(".datasets li:nth-child(2) input")
        page.click("[data-tab=overview]")
        page.wait_for_timeout(800)
        page.screenshot(path=f"{OUT}/ui-overview-compare.png")
        page.click("[data-tab=stability]")
        page.wait_for_timeout(900)
        page.screenshot(path=f"{OUT}/ui-stability-compare.png")
        if errors:
            raise SystemExit(f"page errors: {errors}")
    browser.close()
httpd.shutdown()
print("screenshots written to", OUT)
