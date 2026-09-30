# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Lightweight local web UI: stdlib HTTP server + a static single-page app.

No web framework, no Node toolchain, no CDN: the page and its only
library (uPlot, ~50 kB) are served from this package, so it works offline
and uses a few MB of RAM. Heavy lifting (parsing, statistics) stays in
Python/numpy; the browser only draws decimated data.

Security: binds to 127.0.0.1 by default, rejects foreign ``Host`` headers
(DNS rebinding) and requires a custom request header on every mutating
call (cross-site requests cannot set it without a CORS preflight, which is
never granted).
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import socket
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

import numpy as np

from .. import __version__
from ..analysis import detrend as _detrend
from ..analysis import remove_outliers, summary
from ..filters import kalman
from ..masks import check as mask_check
from ..masks import load_mask
from ..monitor import Monitor
from ..network import delay_stats, floor_packet_percentage, min_delay_filter, wedge
from ..parsers import ParseError, load
from ..pcap import is_capture
from ..series import TimeSeries
from ..simulate import PRESETS, simulate_ntp
from ..sntp import NTPError, query
from ..sources import SourceError
from ..stability import (
    DESCRIPTIONS,
    KINDS,
    TIME_KINDS,
    dynamic,
    identify_noise,
    series_stability,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor")
MAX_UPLOAD = 512 * 1024 * 1024
CSRF_HEADER = "X-NTPStats"


# ------------------------------------------------------------------- state
class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.datasets: Dict[str, TimeSeries] = {}
        self._next = 1
        self.monitor: Optional[Any] = None  # Monitor or sources.LocalWatch
        self.monitor_id: Optional[str] = None
        self.monitor_log: List[str] = []
        self.masks: Dict[str, object] = {}

    def add(self, s: TimeSeries) -> str:
        with self.lock:
            sid = f"d{self._next}"
            self._next += 1
            self.datasets[sid] = s
            return sid

    def get(self, sid: str) -> TimeSeries:
        with self.lock:
            if sid not in self.datasets:
                raise KeyError(sid)
            return self.datasets[sid]

    def describe(self, sid: str) -> dict:
        s = self.get(sid)
        return {
            "id": sid,
            "name": s.name,
            "format": s.source_format,
            "samples": len(s),
            "peer": s.meta.get("peer"),
            "start": float(s.t[0]) if len(s) else None,
            "end": float(s.t[-1]) if len(s) else None,
            "columns": sorted(s.extra),
            "live": sid == self.monitor_id,
        }


STORE = Store()


# ----------------------------------------------------------------- helpers
def _disposition(filename: str) -> str:
    """Content-Disposition safe against header injection and non-latin-1 names (RFC 6266)."""
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:150] or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename[:150], safe='')}"


def _decimate(t: np.ndarray, y: np.ndarray, max_points: int) -> np.ndarray:
    """Indices for min/max-per-bucket decimation (keeps spikes visible)."""
    n = t.size
    if n <= max_points:
        return np.arange(n)
    buckets = max(1, max_points // 2)
    edges = np.linspace(0, n, buckets + 1).astype(int)
    idx: List[int] = []
    yy = np.where(np.isfinite(y), y, 0.0)
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = yy[a:b]
        i, j = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        idx.extend(sorted({i, j}))
    return np.unique(np.array(idx + [0, n - 1]))


def _f(v):
    """JSON-safe float list (NaN/inf -> null)."""
    a = np.asarray(v, dtype=float)
    return [None if not np.isfinite(x) else float(x) for x in a]


def _q(params, key, default=None, cast=str):
    v = params.get(key, [default])[0]
    if v in (None, ""):
        return default
    return cast(v)


def _prepare(sid: str, params) -> TimeSeries:
    s = STORE.get(sid)
    start = _q(params, "start", None, float)
    end = _q(params, "end", None, float)
    if start is not None or end is not None:
        s = s.between(start, end)
    k = _q(params, "outliers", None, float)
    if k:
        s = remove_outliers(s, k)
    if len(s) < 3:
        raise ValueError("fewer than 3 samples in the selected range")
    return s


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return _f(o)
    return str(o)


def _clean(o):
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


# ----------------------------------------------------------------- handlers
def api_series(sid, params):
    s = _prepare(sid, params)
    det = _q(params, "detrend", None)
    max_points = _q(params, "max_points", 4000, int)
    y = _detrend(s.t, s.offset, det) if det and det != "none" else s.offset
    idx = _decimate(s.t, y, max_points)
    out = {
        "id": sid,
        "name": s.name,
        "t": _f(s.t[idx]),
        "offset": _f(y[idx]),
        "extra": {k: _f(v[idx]) for k, v in s.extra.items()},
        "summary": _clean(summary(s)),
        "decimated": bool(idx.size < len(s)),
    }
    overlay = _q(params, "overlay", None)
    trend = s.offset - y  # what detrending removed, re-applied to overlays
    if overlay in ("kalman", "rts"):
        kr = kalman(s, smooth=overlay == "rts")
        out["overlay"] = {
            "label": "RTS smoother" if overlay == "rts" else "Kalman filter",
            "t": out["t"],
            "offset": _f((kr.phase - trend)[idx]),
            "params": {"r": kr.r, "q_phase": kr.q_phase, "q_freq": kr.q_freq},
        }
    elif overlay == "mindelay" and "delay" in s.extra:
        md = min_delay_filter(s)
        keep = np.searchsorted(s.t, md.t)
        out["overlay"] = {"label": "min-delay filter", "t": _f(md.t), "offset": _f(md.offset - trend[keep])}
    if "true_offset" in s.extra:
        out["truth"] = _f((s.extra["true_offset"] - trend)[idx])
    return out


def api_stability(sid, params):
    s = _prepare(sid, params)
    kinds = [k for k in _q(params, "kinds", "oadev").split(",") if k]
    for k in kinds:
        if k not in KINDS:
            raise ValueError(f"unknown statistic {k}")
    taus = _q(params, "taus", "octave")
    det = _q(params, "detrend", None)
    det = None if det in (None, "none") else det
    max_gap = _q(params, "max_gap", 3.0, float)
    tau0 = _q(params, "tau0", None, float)
    ci = _q(params, "ci", 0.683, float) or None
    results = series_stability(s, kinds=kinds, taus=taus, tau0=tau0, max_gap=max_gap, detrend=det, ci=ci)
    mask = STORE.masks.get(_q(params, "mask", ""))
    out = []
    for r in results:
        d = dict(r.as_dict(), description=DESCRIPTIONS[r.kind], meta=r.meta,
                 noise=identify_noise(r) if r.kind not in TIME_KINDS else [])
        if mask is not None and mask.kind == r.kind:
            d["mask"] = dict(mask_check(r, mask), taus=mask.taus.tolist(), limits=mask.limits.tolist())
        out.append(d)
    return {"id": sid, "name": s.name, "results": out}


def api_dynamic(sid, params):
    s = _prepare(sid, params)
    det = _q(params, "detrend", None)
    det = None if det in (None, "none") else det
    d = dynamic(s, kind=_q(params, "kind", "oadev"), window=_q(params, "window", None, float),
                step=_q(params, "step", None, float), detrend=det)
    return dict(d.as_dict(), id=sid, name=s.name)


def api_histogram(sid, params):
    s = _prepare(sid, params)
    det = _q(params, "detrend", "linear")
    y = _detrend(s.t, s.offset, det) if det and det != "none" else s.offset
    bins = _q(params, "bins", 60, int)
    counts, edges = np.histogram(y, bins=bins, density=True)
    mu, sd = float(np.mean(y)), float(np.std(y))
    centers = 0.5 * (edges[1:] + edges[:-1])
    gauss = np.exp(-0.5 * ((centers - mu) / sd) ** 2) / (sd * np.sqrt(2 * np.pi)) if sd > 0 else np.zeros_like(centers)
    return {"id": sid, "name": s.name, "centers": _f(centers), "density": _f(counts), "gauss": _f(gauss), "mean": mu, "std": sd}


def api_events(sid, params):
    from ..events import detect, summary

    s = _prepare(sid, params)
    ev = detect(s)
    return _clean({"id": sid, "name": s.name, "events": [e.as_dict() for e in ev], "summary": summary(ev)})


def api_timeerror(sid, params):
    from ..timeerror import time_error

    s = _prepare(sid, params)
    r = time_error(s, lpf_hz=_q(params, "lpf_hz", 0.1, float), cte_window=_q(params, "cte_window", 1000.0, float))
    d = r.as_dict()
    d.update({"id": sid, "name": s.name})
    return _clean(d)


def api_network(sid, params):
    s = _prepare(sid, params)
    # Offset-vs-delay analysis is meaningless while a frequency offset
    # dominates the offsets, so always remove at least a linear trend.
    det = _q(params, "detrend", "linear")
    det = "linear" if det in (None, "none", "mean") else det
    s = TimeSeries(s.t, _detrend(s.t, s.offset, det), s.name, s.source_format, dict(s.extra), dict(s.meta))
    cluster = _q(params, "cluster", None, float)
    stats = delay_stats(s, cluster=cluster)
    idx = _decimate(s.t, s.extra["delay"], _q(params, "max_points", 4000, int))
    q, x, _ = wedge(s)
    ok = np.isfinite(q) & np.isfinite(x)
    q, x = q[ok], x[ok]
    if q.size > 4000:
        pick = np.random.default_rng(0).choice(q.size, 4000, replace=False)
        q, x = q[pick], x[pick]
    order = np.argsort(q, kind="stable")
    win = _q(params, "window", None, float) or max(200.0, 32 * s.median_interval())
    ft, fpp = floor_packet_percentage(s, window=win, cluster=stats["cluster_width"])
    return {
        "id": sid,
        "name": s.name,
        "stats": _clean(stats),
        "t": _f(s.t[idx]),
        "delay": _f(s.extra["delay"][idx]),
        "wedge": {"q": _f(q[order]), "offset": _f(x[order])},
        "fpp": {"t": _f(ft), "pct": _f(fpp), "window": win},
        "detrend": det,
    }


def api_simulate(body):
    preset = str(body.get("preset", "internet"))
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset}")
    from dataclasses import replace as _replace

    sc = _replace(PRESETS[preset], seed=int(body.get("seed", 1)))
    if body.get("duration"):
        sc.duration = float(body["duration"])
    if body.get("poll"):
        sc.poll = float(body["poll"])
    if sc.duration / sc.poll > 2e6:
        raise ValueError("simulation too large")
    meas, _truth = simulate_ntp(sc, name=f"simulated {preset} (seed {sc.seed})")
    return [STORE.describe(STORE.add(meas))]


def export_csv(sid, params) -> str:
    s = _prepare(sid, params)
    det = _q(params, "detrend", None)
    if det and det != "none":
        s = TimeSeries(s.t, _detrend(s.t, s.offset, det), s.name, s.source_format, dict(s.extra), dict(s.meta))
    buf = io.StringIO()
    s.to_csv(buf)
    return buf.getvalue()


def export_stability_csv(sid, params) -> str:
    data = api_stability(sid, params)
    buf = io.StringIO()
    buf.write("kind,tau,dev,err,n\n")
    for r in data["results"]:
        for t, d, e, n in zip(r["taus"], r["dev"], r["err"], r["n"]):
            buf.write(f"{r['kind']},{t:.9g},{d:.9g},{e:.9g},{n}\n")
    return buf.getvalue()


def _monitor_sample(r, sid):
    with STORE.lock:
        # the dataset id is bound when the monitor starts, so a late sample from a
        # stopped monitor can never leak into a newer live dataset
        old = STORE.datasets.get(sid)
        if old is None:
            return
        if isinstance(r, dict):  # local daemon sample (sources.LocalWatch)
            t, off = float(r["time"]), float(r["offset"])
            vals = {k: float(r[k]) for k in old.extra if isinstance(r.get(k), (int, float))}
        else:
            t, off = (r.t1 + r.t4) / 2, r.offset
            vals = {"delay": r.delay, "stratum": float(r.stratum)}
        extra = {k: np.append(v, vals.get(k, np.nan)) for k, v in old.extra.items()}
        STORE.datasets[sid] = TimeSeries(np.append(old.t, t), np.append(old.offset, off), old.name, "live", extra, old.meta)


def _monitor_error(server, exc):
    with STORE.lock:
        STORE.monitor_log.append(f"{time.strftime('%H:%M:%S')} {server}: {exc}")
        del STORE.monitor_log[:-50]


def api_monitor_start(body):
    source = str(body.get("source", "sntp"))
    servers = [s.strip() for s in str(body.get("servers", "")).replace(",", " ").split() if s.strip()]
    interval = float(body.get("interval", 64))
    if interval < 1:
        raise ValueError("interval must be >= 1 s")
    if source == "sntp" and not servers:
        raise ValueError("no server given")
    api_monitor_stop({})
    with STORE.lock:
        out = body.get("log") or None
        if source in ("chrony", "ntpd", "ptp4l", "ptpcheck"):
            from ..sources import NUMERIC_EXTRAS, LocalWatch

            cols = {k: np.array([]) for k in NUMERIC_EXTRAS[source]}
            label, servers = f"live: local {source}", [f"local {source}"]
        else:
            version = int(body.get("version", 4))
            cols = {"delay": np.array([]), "stratum": np.array([])}
            label = f"live{' NTPv5' if version == 5 else ''}: {', '.join(servers)}"
        sid = STORE.add(TimeSeries(np.array([]), np.array([]), label, "live", cols, {"peer": servers[0]}))

        def on_sample(r, sid=sid):
            _monitor_sample(r, sid)

        if source in ("chrony", "ntpd", "ptp4l", "ptpcheck"):
            mon = LocalWatch(source, interval, out_path=out, on_sample=on_sample, on_error=_monitor_error)
        else:
            mon = Monitor(servers, interval, out_path=out, on_sample=on_sample, on_error=_monitor_error,
                          version=version)
        STORE.monitor_id = sid
        STORE.monitor_log = []
        STORE.monitor = mon.start()
    return {"id": sid, "servers": servers, "interval": interval}


def api_monitor_stop(_body):
    with STORE.lock:
        m = STORE.monitor
        STORE.monitor = None
    if m:
        m.stop()
    return {"stopped": bool(m)}


def api_monitor_status():
    with STORE.lock:
        m = STORE.monitor
        return {
            "running": bool(m and m.running),
            "id": STORE.monitor_id if m else None,
            "samples": m.samples if m else 0,
            "servers": m.servers if m else [],
            "interval": m.interval if m else None,
            "log": list(STORE.monitor_log[-10:]),
        }


# ------------------------------------------------------------------ server
class Handler(BaseHTTPRequestHandler):
    server_version = f"ntpstats/{__version__}"
    allowed_hosts = ("127.0.0.1", "localhost", "[::1]")

    def log_message(self, fmt, *args):  # quieter default logging
        if os.environ.get("NTPSTATS_DEBUG"):
            super().log_message(fmt, *args)

    # -- plumbing
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0] if not (self.headers.get("Host") or "").startswith("[") else (self.headers.get("Host") or "").split("]")[0] + "]"
        if getattr(self.server, "any_host", False):
            return True
        return host in self.allowed_hosts or host in getattr(self.server, "extra_hosts", ())

    def _send(self, code, body: bytes, ctype="application/json", extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'",
        )
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=_json_default, allow_nan=False).encode())

    def _error(self, code, msg):
        self._json({"error": msg}, code)

    def _body(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("invalid Content-Length") from None
        if n < 0:
            raise ValueError("invalid Content-Length")
        if n > MAX_UPLOAD:
            raise ValueError("upload too large")
        return self.rfile.read(n) if n else b""

    def _static(self, path):
        base = VENDOR_DIR if path.startswith("vendor/") else STATIC_DIR
        rel = path[len("vendor/"):] if path.startswith("vendor/") else path
        full = os.path.realpath(os.path.join(base, rel))
        if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype, {"Cache-Control": "no-cache"})

    # -- verbs
    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        url = urlparse(self.path)
        params = parse_qs(url.query)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        try:
            if not parts:
                return self._static("index.html")
            if parts[0] in ("static", "vendor"):
                return self._static("/".join(parts[1:]) if parts[0] == "static" else "/".join(parts))
            if parts[0] != "api":
                return self._error(404, "not found")
            route = parts[1:]
            if route == ["info"]:
                return self._json({"version": __version__, "kinds": {k: DESCRIPTIONS[k] for k in KINDS}})
            if route == ["datasets"]:
                with STORE.lock:
                    return self._json([STORE.describe(i) for i in STORE.datasets])
            if route == ["monitor"]:
                return self._json(api_monitor_status())
            if len(route) == 2 and route[0] == "series":
                return self._json(api_series(route[1], params))
            if len(route) == 2 and route[0] == "stability":
                return self._json(api_stability(route[1], params))
            if len(route) == 2 and route[0] == "histogram":
                return self._json(api_histogram(route[1], params))
            if len(route) == 2 and route[0] == "network":
                return self._json(api_network(route[1], params))
            if len(route) == 2 and route[0] == "events":
                return self._json(api_events(route[1], params))
            if len(route) == 2 and route[0] == "timeerror":
                return self._json(api_timeerror(route[1], params))
            if len(route) == 2 and route[0] == "dynamic":
                return self._json(api_dynamic(route[1], params))
            if len(route) == 3 and route[0] == "export":
                sid, what = route[1], route[2]
                name = STORE.get(sid).name.replace(" ", "_").replace("/", "_")
                if what == "series.csv":
                    body = export_csv(sid, params)
                elif what == "stability.csv":
                    body = export_stability_csv(sid, params)
                elif what == "report.html":
                    from ..report import dataset_report

                    kinds = [k for k in _q(params, "kinds", "oadev,mdev,tdev").split(",") if k in KINDS]
                    det = _q(params, "detrend", None)
                    body = dataset_report([_prepare(sid, params)], kinds=kinds or ["oadev"],
                                          detrend=None if det in (None, "none") else det,
                                          ci=_q(params, "ci", 0.683, float) or 0.683, title=f"ntpstats report: {name}")
                    return self._send(200, body.encode(), "text/html; charset=utf-8",
                                      {"Content-Disposition": _disposition(f"{name}-report.html")})
                elif what == "summary.json":
                    body = json.dumps(_clean(summary(_prepare(sid, params))), indent=2)
                else:
                    return self._error(404, "unknown export")
                ctype = "application/json" if what.endswith(".json") else "text/csv"
                return self._send(200, body.encode(), ctype, {"Content-Disposition": _disposition(f"{name}-{what}")})
            return self._error(404, "unknown endpoint")
        except KeyError:
            return self._error(404, "unknown dataset")
        except (ValueError, ParseError) as exc:
            return self._error(400, str(exc))
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            traceback.print_exc()
            return self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        if self.headers.get(CSRF_HEADER) != "1":
            return self._error(403, "missing request header")
        url = urlparse(self.path)
        params = parse_qs(url.query)
        route = [unquote(p) for p in url.path.strip("/").split("/") if p][1:]
        try:
            if route == ["upload"]:
                name = unquote(self.headers.get("X-Filename") or "upload")
                body = self._body()
                fmt = _q(params, "format", "auto")
                tau0 = _q(params, "tau0", None, float)
                src = body if is_capture(body[:4]) else io.StringIO(body.decode("utf-8", errors="replace"))
                series = load(src, fmt=fmt, tau0=tau0, name=name)
                ids = [STORE.add(s) for s in series]
                return self._json([STORE.describe(i) for i in ids])
            if route == ["mask"]:
                name = unquote(self.headers.get("X-Filename") or "mask")
                mask = load_mask(io.StringIO(self._body().decode("utf-8", errors="replace")), name=name,
                                 kind=_q(params, "kind", None))
                with STORE.lock:
                    mid = f"m{len(STORE.masks) + 1}"
                    STORE.masks[mid] = mask
                return self._json(dict(mask.as_dict(), id=mid))
            body = json.loads(self._body() or b"{}")
            if route == ["query"]:
                r = query(str(body.get("server", "")).strip(), timeout=float(body.get("timeout", 2.0)),
                          version=int(body.get("version", 4)))
                return self._json(r.as_dict())
            if route == ["simulate"]:
                return self._json(api_simulate(body))
            if route == ["monitor", "start"]:
                return self._json(api_monitor_start(body))
            if route == ["monitor", "stop"]:
                return self._json(api_monitor_stop(body))
            if len(route) == 2 and route[0] == "rename":
                with STORE.lock:
                    STORE.get(route[1]).name = str(body.get("name", ""))[:200]
                return self._json(STORE.describe(route[1]))
            return self._error(404, "unknown endpoint")
        except KeyError:
            return self._error(404, "unknown dataset")
        except (ValueError, ParseError, NTPError, SourceError, OSError) as exc:
            return self._error(400, str(exc))
        except Exception as exc:  # pragma: no cover
            traceback.print_exc()
            return self._error(500, f"{type(exc).__name__}: {exc}")

    def do_DELETE(self):
        if not self._host_ok() or self.headers.get(CSRF_HEADER) != "1":
            return self._error(403, "forbidden")
        route = [p for p in urlparse(self.path).path.strip("/").split("/") if p][1:]
        if len(route) == 2 and route[0] == "datasets":
            with STORE.lock:
                if route[1] == STORE.monitor_id:
                    api_monitor_stop({})
                    STORE.monitor_id = None
                existed = STORE.datasets.pop(route[1], None) is not None
            return self._json({"deleted": existed})
        return self._error(404, "unknown endpoint")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    any_host = False  # accept any Host header (explicit non-loopback bind)
    extra_hosts: tuple = ()


class _ServerV6(_Server):
    address_family = socket.AF_INET6


def serve(
    files=(),
    host: str = "127.0.0.1",
    port: int = 8123,
    open_browser: bool = True,
    fmt: str = "auto",
):
    for path in files:
        for s in load(path, fmt=fmt):
            STORE.add(s)
    server_cls = _ServerV6 if ":" in host else _Server  # IPv6 literal -> AF_INET6
    httpd = server_cls((host, port), Handler)
    httpd.daemon_threads = True
    if host not in ("127.0.0.1", "localhost", "::1"):
        # Explicitly exposed: accept any Host header (DNS-rebinding protection is
        # only meaningful for loopback binds); the custom-header CSRF check stays.
        httpd.any_host = host in ("0.0.0.0", "::")
        httpd.extra_hosts = (host, f"[{host}]")
        print(f"warning: listening on {host}; the UI has no authentication")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{httpd.server_address[1]}/"
    print(f"ntpstats UI running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        api_monitor_stop({})
        httpd.server_close()
    return httpd
