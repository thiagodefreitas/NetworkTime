# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Periodic SNTP measurement logger (replaces the 2012 ``estimators.py`` online mode).

Writes CSV rows ``unix_time,offset,delay,server,address,stratum,root_delay,root_dispersion``
readable by :func:`ntpstats.parsers.load`.

Be a good citizen: public servers (pool.ntp.org, NIST, PTB, ...) expect
clients to poll no faster than every 64 s and to back off on a RATE
Kiss-o'-Death. The default interval is 64 s, a random jitter spreads load,
and a KoD RATE doubles the interval for that server.
"""

from __future__ import annotations

import csv
import os
import random
import threading
import time
from typing import Callable, Dict, Iterable, Optional

from .sntp import KissOfDeath, NTPError, NTPResult, query

FIELDS = ("unix_time", "offset", "delay", "server", "address", "stratum", "root_delay", "root_dispersion")
MIN_PUBLIC_INTERVAL = 64.0


def result_row(r: NTPResult) -> dict:
    # Timestamp the sample at the midpoint of the exchange.
    return {
        "unix_time": f"{(r.t1 + r.t4) / 2:.6f}",
        "offset": f"{r.offset:.9e}",
        "delay": f"{r.delay:.9e}",
        "server": r.server,
        "address": r.address,
        "stratum": r.stratum,
        "root_delay": f"{r.root_delay:.6e}",
        "root_dispersion": f"{r.root_dispersion:.6e}",
    }


class Monitor:
    """Poll one or more servers in a background thread."""

    def __init__(
        self,
        servers: Iterable[str],
        interval: float = 64.0,
        out_path: Optional[str] = None,
        on_sample: Optional[Callable[[NTPResult], None]] = None,
        on_error: Optional[Callable[[str, Exception], None]] = None,
        count: Optional[int] = None,
        version: int = 4,
        nts: bool = False,
    ):
        self.version = int(version)
        self.nts = bool(nts)
        self._sessions: Dict[str, object] = {}
        self.servers = list(servers)
        if not self.servers:
            raise ValueError("at least one server is required")
        self.interval = float(interval)
        self.out_path = out_path
        self.on_sample = on_sample
        self.on_error = on_error
        self.count = count
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._backoff: Dict[str, float] = {s: 1.0 for s in self.servers}
        self.samples = 0

    def start(self) -> "Monitor":
        self._thread = threading.Thread(target=self.run, name="ntpstats-monitor", daemon=True)
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
        writer = fh = None
        if self.out_path:
            new = not os.path.exists(self.out_path) or os.path.getsize(self.out_path) == 0
            fh = open(self.out_path, "a", newline="", encoding="utf-8")
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                writer.writeheader()
        try:
            rounds = 0
            next_due = {s: time.monotonic() + random.uniform(0, 1.0) for s in self.servers}
            while not self._stop.is_set():
                now = time.monotonic()
                for server in self.servers:
                    if now < next_due[server]:
                        continue
                    try:
                        r = self._query(server)
                    except KissOfDeath as exc:
                        if exc.code == "RATE":
                            self._backoff[server] = min(self._backoff[server] * 2, 64)
                        self._error(server, exc)
                    except (NTPError, OSError) as exc:
                        self._error(server, exc)
                    else:
                        self.samples += 1
                        if writer:
                            writer.writerow(result_row(r))
                            fh.flush()
                        if self.on_sample:
                            self.on_sample(r)
                    jitter = random.uniform(-0.05, 0.05) * self.interval
                    next_due[server] = now + self.interval * self._backoff[server] + jitter
                    if server == self.servers[-1]:
                        rounds += 1
                if self.count is not None and rounds >= self.count:
                    break
                wait = max(0.05, min(next_due.values()) - time.monotonic())
                self._stop.wait(wait)
        finally:
            if fh:
                fh.close()

    def _query(self, server: str) -> NTPResult:
        if self.nts:
            from .nts import NTSSession

            sess = self._sessions.setdefault(server, NTSSession(server))
            return sess.query()
        return query(server) if self.version == 4 else query(server, version=self.version)

    def _error(self, server: str, exc: Exception) -> None:
        if self.on_error:
            self.on_error(server, exc)
