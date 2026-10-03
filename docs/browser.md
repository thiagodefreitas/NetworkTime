---
description: "Analyse NTP and PTP logs in the browser without installing anything: ntpstats runs locally in WebAssembly (Pyodide); files never leave your machine."
---

# In your browser

**[Open ntpstats in your browser →](https://thiagodefreitas.github.io/NetworkTime/app/)**

The same web UI as `ntpstats ui`, running entirely in the page. The Python code (ntpstats and
numpy) runs in WebAssembly through [Pyodide](https://pyodide.org). Nothing is installed, and the
files you open are analysed on your machine. They are never uploaded, which matters when logs are
sensitive.

- **First visit**: downloads about 15 MB (Python, numpy and ntpstats); later visits use the
  browser cache. Startup takes a few seconds.
- **Everything that needs no network sockets works**:
  - every input format (logs, captures, Stable32, research data);
  - stability with confidence intervals, the noise model, spectra, network metrics, time error
    and events;
  - holdover, simulation, CSV and HTML-report downloads.
- **Needs the installed version** (`pip install ntpstats`): live NTP/NTS queries, `monitor`,
  `watch` of local daemons, and the command line. The UI greys out the *Live* button.

How it works:
- **One API, two transports.** The UI talks to the same small JSON API as the local server. In
  the browser edition, a Web Worker answers it by calling `ntpstats.web.server.dispatch` under
  Pyodide.
- **Same code, same numbers.** The ntpstats code is identical in both editions. CI loads the
  example logs in Chromium and checks that every number matches the installed package (to 1e-9,
  since WebAssembly and native numpy can differ in the last bits).

Build it yourself (for example for an intranet without CDN access):

```bash
python docs/build_app.py site-app/                 # Pyodide from the jsDelivr CDN
python docs/build_app.py site-app/ ../pyodide/     # or from a local copy of the Pyodide files
python -m http.server -d site-app
```
