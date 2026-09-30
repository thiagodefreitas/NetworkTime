# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""OpenTelemetry export of ``monitor``/``watch`` metrics (OTLP/HTTP, JSON encoding, standard library only).

``ntpstats monitor time.example --otlp http://collector:4318`` pushes the same
metrics as the Prometheus endpoint (:mod:`ntpstats.metrics`) to an OpenTelemetry
Collector (or any OTLP/HTTP receiver) every ``--otlp-interval`` seconds. Names
use the OpenTelemetry style (``ntpstats.offset`` with unit ``s``). The usual
environment variables are honoured: ``OTEL_EXPORTER_OTLP_ENDPOINT``,
``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``, ``OTEL_EXPORTER_OTLP_HEADERS``,
``OTEL_SERVICE_NAME`` and ``OTEL_RESOURCE_ATTRIBUTES``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Mapping, Optional

from . import __version__
from .metrics import Registry

DEFAULT_ENDPOINT = "http://localhost:4318"


def _attrs(d: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for k, v in d.items():
        if isinstance(v, bool):
            val: Dict[str, Any] = {"boolValue": v}
        elif isinstance(v, int):
            val = {"intValue": str(v)}
        elif isinstance(v, float):
            val = {"doubleValue": v}
        else:
            val = {"stringValue": str(v)}
        out.append({"key": k, "value": val})
    return out


def _split_kv(text: str) -> Dict[str, str]:
    out = {}
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[urllib.parse.unquote(k.strip())] = urllib.parse.unquote(v.strip())
    return out


def _name_unit(name: str):
    if name.endswith("_seconds"):
        return "ntpstats." + name[: -len("_seconds")], "s"
    if name.endswith("_ppm"):
        return "ntpstats." + name[: -len("_ppm")], "ppm"
    return "ntpstats." + name, "1"


def to_otlp(registry: Registry, resource: Optional[Mapping[str, Any]] = None, start_ns: Optional[int] = None,
            now_ns: Optional[int] = None) -> Dict[str, Any]:
    """ExportMetricsServiceRequest (OTLP JSON) for the registry's current state."""
    now = int(now_ns if now_ns is not None else time.time_ns())
    start = str(int(start_ns if start_ns is not None else now))
    snap = registry.snapshot()
    by_name: Dict[str, Dict[str, Any]] = {}
    for name, help_, src, v in registry.values():
        mname, unit = _name_unit(name)
        m = by_name.setdefault(mname, {"name": mname, "unit": unit, "description": help_, "gauge": {"dataPoints": []}})
        m["gauge"]["dataPoints"].append({"attributes": _attrs({"source": src}), "timeUnixNano": str(now),
                                         "asDouble": v})
    tdev = [{"attributes": _attrs({"source": src, "tau": float(tau)}), "timeUnixNano": str(now), "asDouble": dev}
            for src, r in sorted(snap["rolling"].items()) for tau, dev in r.get("tdev", [])]
    metrics = list(by_name.values())
    if tdev:
        metrics.append({"name": "ntpstats.tdev", "unit": "s", "description": "Time deviation over the rolling window.",
                        "gauge": {"dataPoints": tdev}})

    def counter(name, desc, rows):
        return {"name": name, "unit": "1", "description": desc,
                "sum": {"aggregationTemporality": 2, "isMonotonic": True,
                        "dataPoints": [{"attributes": _attrs(a), "startTimeUnixNano": start, "timeUnixNano": str(now),
                                        "asInt": str(n)} for a, n in rows]}}

    metrics.append(counter("ntpstats.samples", "Samples received.",
                           [({"source": s}, n) for s, n in sorted(snap["samples"].items())]))
    if snap["errors"]:
        metrics.append(counter("ntpstats.errors", "Errors by kind.",
                               [({"source": s, "kind": k}, n) for (s, k), n in sorted(snap["errors"].items())]))
    res = {"service.name": os.environ.get("OTEL_SERVICE_NAME", "ntpstats"), "service.version": __version__}
    res.update(_split_kv(os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")))
    res.update(resource or {})
    return {"resourceMetrics": [{"resource": {"attributes": _attrs(res)},
                                 "scopeMetrics": [{"scope": {"name": "ntpstats", "version": __version__},
                                                   "metrics": metrics}]}]}


def metrics_url(endpoint: Optional[str] = None) -> str:
    """Resolve the OTLP/HTTP metrics URL from an explicit endpoint or the standard environment variables."""
    if endpoint:
        return endpoint if endpoint.rstrip("/").endswith("/v1/metrics") else endpoint.rstrip("/") + "/v1/metrics"
    full = os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    if full:
        return full
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/") + "/v1/metrics"


def push(registry: Registry, url: str, headers: Optional[Mapping[str, str]] = None, timeout: float = 10.0,
         **kw) -> int:
    """POST one export; returns the HTTP status (raises ``OSError`` on network errors)."""
    body = json.dumps(to_otlp(registry, **kw)).encode("utf-8")
    hdr = {"Content-Type": "application/json", "User-Agent": f"ntpstats/{__version__}"}
    hdr.update(_split_kv(os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")))
    hdr.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (user-configured collector URL)
        return int(resp.status)


class Pusher(threading.Thread):
    """Background exporter: pushes every ``interval`` seconds until :meth:`stop`."""

    def __init__(self, registry: Registry, endpoint: Optional[str] = None, interval: float = 60.0,
                 headers: Optional[Mapping[str, str]] = None):
        super().__init__(daemon=True)
        self.registry, self.url, self.interval, self.headers = registry, metrics_url(endpoint), float(interval), headers
        self.start_ns = time.time_ns()
        self.failures = 0
        self.last_error: Optional[str] = None
        self._stop_evt = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.wait(self.interval):
            self.flush()

    def flush(self) -> None:
        try:
            push(self.registry, self.url, self.headers, start_ns=self.start_ns)
            self.last_error = None
        except (OSError, ValueError) as exc:  # keep measuring when the collector is down
            self.failures += 1
            self.last_error = str(exc)

    def stop(self) -> None:
        self._stop_evt.set()
        self.flush()
