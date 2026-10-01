#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Assemble the in-browser edition (Pyodide) into a static directory, by default docs/app/.

The web UI's files are copied unchanged. A wheel of this checkout is built
next to them, and the page loads ``static/bridge.js`` before ``static/app.js``,
which sends the UI's /api requests to a Web Worker running ntpstats under
Pyodide instead of the local server. ``mkdocs build`` then publishes it at
/app/ on the docs site.
"""

import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "src", "ntpstats", "web")


def main(out: str, pyodide: str = "") -> None:
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    shutil.copytree(os.path.join(WEB, "static"), os.path.join(out, "static"))
    shutil.copytree(os.path.join(WEB, "vendor"), os.path.join(out, "vendor"))
    os.remove(os.path.join(out, "static", "index.html"))
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", out, ROOT], check=True)
    wheel = os.path.basename(glob.glob(os.path.join(out, "ntpstats-*.whl"))[0])
    with open(os.path.join(out, "static", "config.js"), "w", encoding="utf-8") as fh:
        cfg = {"wheel": "../" + wheel, **({"pyodide": pyodide} if pyodide else {})}
        fh.write(f"window.NTPSTATS_CONFIG = {json.dumps(cfg)};\n")
    with open(os.path.join(WEB, "static", "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace('href="/vendor/', 'href="vendor/').replace('src="/vendor/', 'src="vendor/')
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    html = html.replace('<script src="static/app.js"></script>',
                        '<script src="static/config.js"></script>\n<script src="static/bridge.js"></script>\n'
                        '<script src="static/app.js"></script>')
    html = html.replace("<title>", "<title>(in your browser) ", 1)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"in-browser edition in {out} ({wheel})")


if __name__ == "__main__":
    # optional second argument: where Pyodide is served from (default: the jsDelivr CDN)
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "app"), *(sys.argv[2:3]))
