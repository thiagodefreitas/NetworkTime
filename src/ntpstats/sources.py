# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
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
    d: Dict[str, object] = dict(zip(TRACKING_FIELDS, row))
    for k in TRACKING_FIELDS[2:13]:
        d[k] = float(d[k])
    # ntpd convention (reference - local): System time is already that way.
    d["offset"] = d["system_time"]
    d["last_offset"] = -float(d["last_offset"])
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


SAMPLERS: Dict[str, Callable[..., Dict[str, object]]] = {"chrony": sample_chrony, "ntpd": sample_ntpq}
NUMERIC_EXTRAS = {
    "chrony": ("last_offset", "rms_offset", "frequency_ppm", "skew_ppm", "root_delay", "root_dispersion", "stratum"),
    "ntpd": ("frequency_ppm", "sys_jitter", "clk_jitter", "clk_wander_ppm", "rootdelay", "rootdisp", "stratum"),
}


class LocalWatch:
    """Poll the local daemon periodically (same interface as :class:`ntpstats.monitor.Monitor`)."""

    def __init__(self, daemon: str = "chrony", interval: float = 16.0, out_path: Optional[str] = None,
                 on_sample: Optional[Callable[[Dict[str, object]], None]] = None,
                 on_error: Optional[Callable[[str, Exception], None]] = None,
                 count: Optional[int] = None, cmd: Optional[Sequence[str]] = None):
        if daemon not in SAMPLERS:
            raise ValueError(f"unknown daemon {daemon!r}; choose chrony or ntpd")
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
        fn = SAMPLERS[self.daemon]
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
                    if writer:
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
