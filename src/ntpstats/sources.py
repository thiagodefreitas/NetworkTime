# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Live samples from the local time daemon (no log files needed).

* **chrony**: ``chronyc -c tracking`` (CSV). Field order from chrony's
  ``client.c``: RefID, name, stratum, ref time, *System time* (current
  correction; positive = system clock slow, i.e. the ntpd sign convention),
  last offset (positive = local fast), RMS offset, frequency, residual freq,
  skew, root delay, root dispersion, update interval, leap status.
  ``chronyc -c sourcestats`` adds per-source estimated offsets (same quantity
  as statistics.log "Est offset", positive = local fast, negated here).
* **ntpd / NTPsec**: ``ntpq -c rv`` system variables (``offset`` in ms, ntpd
  convention; ``frequency`` ppm; ``sys_jitter``/``clk_jitter`` ms).

* **linuxptp**: ``pmc -u -b 0 'GET CURRENT_DATA_SET' 'GET TIME_STATUS_NP'``
  (``offsetFromMaster`` and ``master_offset`` in ns, local - master, negated
  here; ``meanPathDelay`` ns; ``gmPresent``).
* **facebook/time**: ``ptpcheck stats`` JSON (``ptp.offset_ns``, local -
  master as reported by ptp4l, negated here; ``ptp.mean_path_delay_ns``).
* **ntpd-rs**: ``ntp-ctl -f prometheus status``, or the metrics exporter's
  HTTP endpoint (give its URL as the command). ntpd-rs 1.x exports per-source
  ``ntp_source_offset_seconds`` (source - local, the ntpd convention),
  ``ntp_source_uncertainty_seconds`` and ``ntp_source_delay_seconds``; the
  sample's offset is the inverse-variance mean over the sources, the
  combination ntpd-rs itself applies to the sources it selects. The 2.0
  pre-releases no longer export per-source offsets; they are reported as such.

Only a subprocess is used; nothing is installed or configured. The command
can be overridden (e.g. ``["ssh", "host", "chronyc"]``) to watch a remote host.
"""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence

TRACKING_FIELDS = (
    "refid", "name", "stratum", "ref_time", "system_time", "last_offset", "rms_offset", "frequency_ppm",
    "residual_freq_ppm", "skew_ppm", "root_delay", "root_dispersion", "update_interval", "leap",
)


class SourceError(RuntimeError):
    pass


def _run(cmd: Sequence[str], timeout: float = 5.0) -> str:
    try:
        res = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise SourceError(f"{cmd[0]} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"{' '.join(cmd)} timed out") from exc
    if res.returncode != 0:
        raise SourceError((res.stderr or res.stdout or f"{cmd[0]} failed").strip())
    return res.stdout


def parse_chronyc_tracking(text: str) -> Dict[str, object]:
    row = next(csv.reader(io.StringIO(text.strip())))
    if len(row) < 13:
        raise SourceError(f"unexpected chronyc tracking output: {text[:80]!r}")
    raw = dict(zip(TRACKING_FIELDS, row))
    d: Dict[str, object] = dict(raw)
    for k in TRACKING_FIELDS[2:13]:
        d[k] = float(raw[k])
    # ntpd convention (reference - local): System time is already that way.
    d["offset"] = d["system_time"]
    d["last_offset"] = -float(raw["last_offset"])
    return d


def parse_chronyc_sourcestats(text: str) -> List[Dict[str, object]]:
    out = []
    for row in csv.reader(io.StringIO(text.strip())):
        if len(row) < 8:
            continue
        try:
            out.append({
                "name": row[0], "np": int(row[1]), "nr": int(row[2]), "span": float(row[3]),
                "frequency_ppm": float(row[4]), "freq_skew_ppm": float(row[5]),
                "offset": -float(row[6]), "std_dev": float(row[7]),
            })
        except ValueError:
            continue
    return out


_RV = re.compile(r"([a-z_]+)=([^,\s]+)")


def parse_ntpq_rv(text: str) -> Dict[str, object]:
    kv = dict(_RV.findall(text))
    if "offset" not in kv:
        raise SourceError("ntpq output has no offset variable")

    def ms(key):
        return float(kv[key]) * 1e-3 if key in kv else float("nan")

    return {
        "offset": ms("offset"),
        "frequency_ppm": float(kv.get("frequency", "nan")),
        "sys_jitter": ms("sys_jitter"),
        "clk_jitter": ms("clk_jitter"),
        "clk_wander_ppm": float(kv.get("clk_wander", "nan")),
        "stratum": float(kv.get("stratum", "nan")),
        "rootdelay": ms("rootdelay"),
        "rootdisp": ms("rootdisp"),
        "refid": kv.get("refid", ""),
    }


def sample_chrony(cmd: Sequence[str] = ("chronyc",)) -> Dict[str, object]:
    d = parse_chronyc_tracking(_run([*cmd, "-c", "tracking"]))
    d["time"] = time.time()
    return d


def sample_ntpq(cmd: Sequence[str] = ("ntpq",)) -> Dict[str, object]:
    d = parse_ntpq_rv(_run([*cmd, "-c", "rv"]))
    d["time"] = time.time()
    return d


_PMC_KV = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s+(\S+)\s*$")


def parse_pmc(text: str) -> Dict[str, object]:
    """Parse ``pmc`` CURRENT_DATA_SET / TIME_STATUS_NP responses."""
    kv: Dict[str, str] = {}
    for line in text.splitlines():
        m = _PMC_KV.match(line)
        if m and m.group(1) not in kv:
            kv[m.group(1)] = m.group(2)
    if "offsetFromMaster" not in kv and "master_offset" not in kv:
        raise SourceError("pmc output has no offsetFromMaster/master_offset (is ptp4l running?)")

    def ns(key):
        try:
            return float(kv[key]) * 1e-9
        except (KeyError, ValueError):
            return float("nan")

    off = ns("offsetFromMaster")
    if off != off:  # NaN: fall back to TIME_STATUS_NP
        off = ns("master_offset")
    return {
        "offset": -off,
        "mean_path_delay": ns("meanPathDelay"),
        "master_offset": ns("master_offset"),
        "steps_removed": float(kv.get("stepsRemoved", "nan")),
        "gm_present": 1.0 if kv.get("gmPresent") == "true" else 0.0 if "gmPresent" in kv else float("nan"),
        "gm_identity": kv.get("gmIdentity", ""),
    }


def sample_pmc(cmd: Sequence[str] = ("pmc", "-u", "-b", "0")) -> Dict[str, object]:
    d = parse_pmc(_run([*cmd, "GET CURRENT_DATA_SET", "GET TIME_STATUS_NP"]))
    d["time"] = time.time()
    return d


def parse_ptpcheck_stats(text: str) -> Dict[str, object]:
    """Parse ``ptpcheck stats`` JSON (facebook/time)."""
    import json

    try:
        j = json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise SourceError(f"unexpected ptpcheck output: {text[:80]!r}") from exc
    if "ptp.offset_ns" not in j:
        raise SourceError("ptpcheck stats output has no ptp.offset_ns")
    return {
        "offset": -float(j["ptp.offset_ns"]) * 1e-9,
        "mean_path_delay": float(j.get("ptp.mean_path_delay_ns", float("nan"))) * 1e-9,
        "steps_removed": float(j.get("ptp.steps_removed", float("nan"))),
        "gm_present": float(j.get("ptp.gm_present", float("nan"))),
    }


def sample_ptpcheck(cmd: Sequence[str] = ("ptpcheck",)) -> Dict[str, object]:
    d = parse_ptpcheck_stats(_run([*cmd, "stats"]))
    d["time"] = time.time()
    return d


def parse_prometheus_text(text: str) -> List[tuple]:
    """Samples of the Prometheus/OpenMetrics text format: ``(name, labels, value)`` per line."""
    out = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        m = _PROM_LINE.match(ln)
        if not m:
            continue
        name, lab, rest = m.group(1), m.group(2) or "", m.group(3).split()
        labels = {k: v.replace('\\"', '"').replace("\\\\", "\\") for k, v in _PROM_LABEL.findall(lab)}
        try:
            out.append((name, labels, float(rest[0])))
        except (ValueError, IndexError):
            continue
    return out


_PROM_LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(.+)$")
_PROM_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def parse_ntpdrs_metrics(text: str) -> Dict[str, object]:
    """One ntpd-rs observation from its Prometheus text output (``ntp-ctl -f prometheus status``)."""
    sources: Dict[str, Dict[str, float]] = {}
    system: Dict[str, float] = {}
    for name, labels, value in parse_prometheus_text(text):
        if name.startswith("ntp_source_"):
            key = labels.get("id") or labels.get("address") or labels.get("name", "?")
            src = sources.setdefault(key, {})
            src[name[len("ntp_source_"):]] = value
        elif name.startswith("ntp_system_"):
            system[name[len("ntp_system_"):]] = value
    if not sources and not system:
        raise SourceError("no ntpd-rs metrics in the output (expected ntp_source_* / ntp_system_* lines)")
    rows = [(v["offset_seconds"], v.get("uncertainty_seconds", float("nan")), v.get("delay_seconds", float("nan")))
            for v in sources.values() if "offset_seconds" in v]
    if not rows:
        raise SourceError("this ntpd-rs does not export per-source offsets (the 2.0 pre-releases removed "
                          "ntp_source_offset_seconds); use ntpd-rs 1.x, a packet capture or the Prometheus history")
    off = [r[0] for r in rows]
    unc = [r[1] if r[1] == r[1] and r[1] > 0 else float("nan") for r in rows]
    if all(u == u for u in unc):
        w = [1.0 / (u * u) for u in unc]
        offset = sum(wi * o for wi, o in zip(w, off)) / sum(w)
        best = min(range(len(rows)), key=lambda i: unc[i])
    else:
        offset = sorted(off)[len(off) // 2]
        best = 0
    return {
        "offset": float(offset),
        "sources": float(len(rows)),
        "min_uncertainty": float(rows[best][1]),
        "delay": float(rows[best][2]),
        "root_delay": system.get("root_delay_seconds", float("nan")),
        "root_dispersion": system.get("root_dispersion_seconds", float("nan")),
        "stratum": system.get("stratum", float("nan")),
    }


def sample_ntpdrs(cmd: Sequence[str] = ("ntp-ctl", "-f", "prometheus", "status")) -> Dict[str, object]:
    """Sample ntpd-rs with ``ntp-ctl``, or from its metrics exporter when ``cmd`` is one http(s) URL."""
    if len(cmd) == 1 and str(cmd[0]).startswith(("http://", "https://")):
        import urllib.request

        try:
            with urllib.request.urlopen(str(cmd[0]), timeout=5.0) as resp:  # noqa: S310 (scheme checked above)
                text = resp.read().decode("utf-8", "replace")
        except OSError as exc:
            raise SourceError(f"{cmd[0]}: {exc}") from exc
    else:
        text = _run(cmd)
    d = parse_ntpdrs_metrics(text)
    d["time"] = time.time()
    return d


def prometheus_query_range(url: str, query: str, start: float, end: float, step="60",
                           timeout: float = 30.0) -> dict:
    """Run a Prometheus ``/api/v1/query_range`` request and return the JSON document."""
    import json
    import urllib.parse
    import urllib.request

    qs = urllib.parse.urlencode({"query": query, "start": f"{start:.3f}", "end": f"{end:.3f}", "step": str(step)})
    full = url.rstrip("/") + "/api/v1/query_range?" + qs
    if not full.startswith(("http://", "https://")):
        raise SourceError("Prometheus URL must start with http:// or https://")
    try:
        with urllib.request.urlopen(full, timeout=timeout) as resp:  # noqa: S310 (scheme checked above)
            doc = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceError(f"Prometheus query failed: {exc}") from exc
    if doc.get("status") != "success":
        raise SourceError(f"Prometheus error: {doc.get('error', doc)}")
    return doc


#: daemon -> sampler function name (resolved at call time so it can be patched/replaced)
SAMPLERS: Dict[str, str] = {"chrony": "sample_chrony", "ntpd": "sample_ntpq", "ptp4l": "sample_pmc",
                            "ptpcheck": "sample_ptpcheck", "ntpd-rs": "sample_ntpdrs"}
NUMERIC_EXTRAS = {
    "chrony": ("last_offset", "rms_offset", "frequency_ppm", "skew_ppm", "root_delay", "root_dispersion", "stratum"),
    "ntpd": ("frequency_ppm", "sys_jitter", "clk_jitter", "clk_wander_ppm", "rootdelay", "rootdisp", "stratum"),
    "ptp4l": ("mean_path_delay", "master_offset", "steps_removed", "gm_present"),
    "ptpcheck": ("mean_path_delay", "steps_removed", "gm_present"),
    "ntpd-rs": ("sources", "min_uncertainty", "delay", "root_delay", "root_dispersion", "stratum"),
}


class LocalWatch:
    """Poll the local daemon periodically (same interface as :class:`ntpstats.monitor.Monitor`)."""

    def __init__(self, daemon: str = "chrony", interval: float = 16.0, out_path: Optional[str] = None,
                 on_sample: Optional[Callable[[Dict[str, object]], None]] = None,
                 on_error: Optional[Callable[[str, Exception], None]] = None,
                 count: Optional[int] = None, cmd: Optional[Sequence[str]] = None):
        if daemon not in SAMPLERS:
            raise ValueError(f"unknown daemon {daemon!r}; choose from {', '.join(SAMPLERS)}")
        self.daemon = daemon
        self.servers = [f"local {daemon}"]
        self.interval = float(interval)
        self.out_path = out_path
        self.on_sample = on_sample
        self.on_error = on_error
        self.count = count
        self.cmd = cmd
        self.samples = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def sample(self) -> Dict[str, object]:
        fn: Callable[..., Dict[str, object]] = globals()[SAMPLERS[self.daemon]]
        return fn(self.cmd) if self.cmd else fn()

    def start(self) -> "LocalWatch":
        self._thread = threading.Thread(target=self.run, name="ntpstats-watch", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> None:
        cols = ("unix_time", "offset") + NUMERIC_EXTRAS[self.daemon]
        fh = writer = None
        if self.out_path:
            new = not os.path.exists(self.out_path) or os.path.getsize(self.out_path) == 0
            fh = open(self.out_path, "a", newline="", encoding="utf-8")
            writer = csv.writer(fh)
            if new:
                writer.writerow(cols)
        try:
            n = 0
            while not self._stop.is_set():
                try:
                    d = self.sample()
                except SourceError as exc:
                    if self.on_error:
                        self.on_error(self.servers[0], exc)
                else:
                    self.samples += 1
                    if writer is not None and fh is not None:
                        writer.writerow([f"{d['time']:.6f}", f"{d['offset']:.9e}"] + [d.get(k, "") for k in cols[2:]])
                        fh.flush()
                    if self.on_sample:
                        self.on_sample(d)
                n += 1
                if self.count is not None and n >= self.count:
                    break
                self._stop.wait(self.interval)
        finally:
            if fh:
                fh.close()
