# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""OpenMetrics (Prometheus) exporter for ``ntpstats monitor`` and ``ntpstats watch``.

``ntpstats monitor pool.ntp.org --metrics-port 9123`` serves ``/metrics``
(bound to 127.0.0.1 unless ``--metrics-host`` says otherwise). Besides the
latest measurement it exports what dashboards usually lack: an error bound
and rolling stability statistics computed from a window of recent samples.

Metrics (label ``source`` = server name, or ``chrony``/``ntpd`` for watch):

=========================================  ===========================================
``ntpstats_offset_seconds``                last offset, reference - local
``ntpstats_delay_seconds``                 last round-trip delay (monitor)
``ntpstats_offset_bound_seconds``          ``|offset| + delay/2 + root_delay/2 + root_dispersion``:
                                           how far the local clock can be from the
                                           source's reference, given this sample
``ntpstats_root_delay_seconds``            source's root delay
``ntpstats_root_dispersion_seconds``       source's root dispersion
``ntpstats_stratum``                       source's stratum
``ntpstats_frequency_ppm``                 local frequency correction (watch)
``ntpstats_authenticated``                 1 when the sample was NTS-authenticated
``ntpstats_last_sample_timestamp_seconds`` POSIX time of the last sample
``ntpstats_offset_stddev_seconds``         standard deviation of the offset over the window
``ntpstats_tdev_seconds{tau="..."}``       TDEV over the window at 1, 4 and 16 sample intervals
``ntpstats_samples_total``                 samples received (counter)
``ntpstats_errors_total{kind="..."}``      errors by kind, e.g. ``timeout``, ``kod_rate`` (counter)
=========================================  ===========================================
"""

from __future__ import annotations

import math
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

CONTENT_TYPE = "application/openmetrics-text; version=1.0.0; charset=utf-8"
TDEV_FACTORS = (1, 4, 16)

_GAUGES = (
    ("offset_seconds", "Last offset, reference minus local."),
    ("delay_seconds", "Last round-trip delay."),
    ("offset_bound_seconds", "Bound on the local clock error relative to the source's reference, from this sample."),
    ("root_delay_seconds", "Root delay reported by the source."),
    ("root_dispersion_seconds", "Root dispersion reported by the source."),
    ("stratum", "Stratum of the source."),
    ("frequency_ppm", "Local frequency correction."),
    ("authenticated", "1 when the last sample was authenticated with NTS."),
    ("last_sample_timestamp_seconds", "POSIX time of the last sample."),
    ("offset_stddev_seconds", "Standard deviation of the offset over the rolling window."),
)


def _label(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _num(v: float) -> str:
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "+Inf" if v > 0 else "-Inf"
    return repr(float(v))


class Registry:
    """Thread-safe store of the latest values and a rolling window per source."""

    def __init__(self, window: int = 1024):
        self.window = int(window)
        self._lock = threading.Lock()
        self._gauges: Dict[str, Dict[str, float]] = {}
        self._hist: Dict[str, Deque[Tuple[float, float]]] = {}
        self._samples: Dict[str, int] = {}
        self._errors: Dict[Tuple[str, str], int] = {}

    def observe(self, source: str, t: float, offset: float, **values: Optional[float]) -> None:
        """Record one sample. ``values`` may hold ``delay``, ``root_delay``,
        ``root_dispersion``, ``stratum``, ``frequency_ppm`` and ``authenticated``."""
        g = {k: float(v) for k, v in values.items() if v is not None}
        g["offset"] = float(offset)
        g["last_sample_timestamp"] = float(t)
        if "delay" in g or "root_delay" in g:
            g["offset_bound"] = (abs(g["offset"]) + g.get("delay", 0.0) / 2 + g.get("root_delay", 0.0) / 2
                                 + g.get("root_dispersion", 0.0))
        with self._lock:
            self._gauges.setdefault(source, {}).update(g)
            self._hist.setdefault(source, deque(maxlen=self.window)).append((float(t), float(offset)))
            self._samples[source] = self._samples.get(source, 0) + 1

    def error(self, source: str, kind: str) -> None:
        with self._lock:
            key = (source, kind)
            self._errors[key] = self._errors.get(key, 0) + 1

    def observe_ntp(self, r) -> None:
        """Record an :class:`ntpstats.sntp.NTPResult`."""
        self.observe(r.server, (r.t1 + r.t4) / 2, r.offset, delay=r.delay, root_delay=r.root_delay,
                     root_dispersion=r.root_dispersion, stratum=float(r.stratum),
                     authenticated=1.0 if getattr(r, "auth", "") == "nts" else 0.0)

    def observe_watch(self, daemon: str, d: dict) -> None:
        """Record a :class:`ntpstats.sources.LocalWatch` sample dict."""

        def f(*keys):
            for k in keys:
                if k in d:
                    try:
                        return float(d[k])
                    except (TypeError, ValueError):
                        return None
            return None

        self.observe(daemon, float(d["time"]), float(d["offset"]), frequency_ppm=f("frequency_ppm"),
                     root_delay=f("root_delay", "rootdelay"), root_dispersion=f("root_dispersion", "rootdisp"),
                     stratum=f("stratum"))

    # ------------------------------------------------------------ rendering
    def _rolling(self, hist: List[Tuple[float, float]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if len(hist) < 3:
            return out
        t = np.array([h[0] for h in hist])
        x = np.array([h[1] for h in hist])
        out["offset_stddev"] = float(np.std(x, ddof=1))
        tau0 = float(np.median(np.diff(t)))
        if tau0 <= 0:
            return out
        from .series import TimeSeries
        from .stability import compute

        _, xu, tau0 = TimeSeries(t=t, offset=x).to_uniform(tau0=tau0)
        ms = [m for m in TDEV_FACTORS if 3 * m + 1 <= xu.size]
        if ms:
            r = compute(xu, tau0, "tdev", ms, ci=None)
            out["tdev"] = list(zip(r.taus.tolist(), r.dev.tolist()))
        return out

    def render(self) -> str:
        with self._lock:
            gauges = {s: dict(v) for s, v in self._gauges.items()}
            hist = {s: list(v) for s, v in self._hist.items()}
            samples = dict(self._samples)
            errors = dict(self._errors)
        rolling = {s: self._rolling(h) for s, h in hist.items()}
        lines: List[str] = []
        for name, help_ in _GAUGES:
            key = name.rsplit("_seconds", 1)[0] if name.endswith("_seconds") else name
            rows = []
            for src in sorted(gauges):
                v = gauges[src].get(key, rolling[src].get(key))
                if isinstance(v, float):
                    rows.append(f'ntpstats_{name}{{source="{_label(src)}"}} {_num(v)}')
            if rows:
                lines += [f"# TYPE ntpstats_{name} gauge", f"# HELP ntpstats_{name} {help_}"] + rows
        tdev_rows = []
        for src in sorted(rolling):
            for tau, dev in rolling[src].get("tdev", []):
                tdev_rows.append(f'ntpstats_tdev_seconds{{source="{_label(src)}",tau="{tau:g}"}} {_num(dev)}')
        if tdev_rows:
            lines += ["# TYPE ntpstats_tdev_seconds gauge",
                      "# HELP ntpstats_tdev_seconds Time deviation over the rolling window."] + tdev_rows
        lines += ["# TYPE ntpstats_samples counter", "# HELP ntpstats_samples Samples received."]
        lines += [f'ntpstats_samples_total{{source="{_label(s)}"}} {n}' for s, n in sorted(samples.items())]
        lines += ["# TYPE ntpstats_errors counter", "# HELP ntpstats_errors Errors by kind."]
        lines += [f'ntpstats_errors_total{{source="{_label(s)}",kind="{_label(k)}"}} {n}'
                  for (s, k), n in sorted(errors.items())]
        lines.append("# EOF")
        return "\n".join(lines) + "\n"


def error_kind(exc: Exception) -> str:
    """Short, stable label for an exception (used as the ``kind`` label)."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return f"kod_{code.lower()}"
    name = type(exc).__name__
    if "timeout" in name.lower() or "timed out" in str(exc).lower():
        return "timeout"
    return name.lower()


def serve(registry: Registry, host: str = "127.0.0.1", port: int = 9123) -> ThreadingHTTPServer:
    """Serve ``/metrics`` in a daemon thread; returns the server (call ``shutdown()`` to stop)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            if self.path.split("?")[0] != "/metrics":
                self.send_error(404)
                return
            body = registry.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="ntpstats-metrics", daemon=True).start()
    return srv
