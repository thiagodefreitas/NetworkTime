# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Live samples from hardware clocks and clock-error-bound services.

* **PHC** (any PTP hardware clock, ``/dev/ptpN``): the system clock against
  the PHC with the kernel's ``PTP_SYS_OFFSET_EXTENDED`` ioctl
  (``include/uapi/linux/ptp_clock.h``), as linuxptp's phc2sys reads it
  (``sysoff.c``): of n readings [system, PHC, system] the one with the
  shortest system window is kept, and the PHC is compared with the window's
  midpoint. A PHC usually runs on TAI; the whole seconds between it and the
  system clock (TAI - UTC) are removed and reported as ``whole_seconds``
  unless ``tai_utc`` is given. Offset = PHC - system (reference - local).
  Reading ``/dev/ptpN`` needs read permission on the device.
* **OCP Time Card** (``/sys/class/timecard/ocpN``, Linux ``ptp_ocp``
  driver, ``Documentation/ABI/testing/sysfs-timecard``): the PHC above,
  through the card's ``ptp`` link, plus ``gnss_sync`` (1 when it reads
  ``SYNC``, 0 when ``LOST @ ...``), ``clock_source``, ``utc_tai_offset``
  and the firmware's ``clock_status_offset`` and ``clock_status_drift``
  (in the firmware's own units, kept as they are).
* **AWS ClockBound**: ``clockbound_now()`` of the ClockBound client library
  (``libclockbound``, ``clock-bound-ffi/include/clockbound.h``), called in
  process. The sample is the window's centre minus the system clock read
  around the call, the half-width as ``bound`` and the clock status.
* **Meta fbclock**: ``ptpcheck fbclock --utc`` (facebook/time), whose text
  output is ``Earliest``/``Latest`` in ns. The command runs as a
  subprocess, so the system clock is read before and after it and the
  window's centre is compared with the midpoint; ``read_window`` is that
  interval, which bounds the error of the comparison.

The samples of the two bound services also record ``earliest`` and
``latest``, so their watch log is a bounds file that ``ntpstats bounds``
checks against a reference.
"""

from __future__ import annotations

import ctypes
import os
import re
import struct
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .sources import SourceError, _run

PTP_MAX_SAMPLES = 25
_PTP_CLK_MAGIC = ord("=")
_EXT_HEADER = struct.Struct("=Ii2I")  # n_samples, clockid, rsv[2]
_CLOCK_TIME = struct.Struct("=qII")  # sec, nsec, reserved
_EXT_SIZE = _EXT_HEADER.size + PTP_MAX_SAMPLES * 3 * _CLOCK_TIME.size  # 1216 bytes


def _iowr(nr: int, size: int) -> int:
    """``_IOWR(PTP_CLK_MAGIC, nr, size)`` with the generic Linux encoding (x86, arm, riscv)."""
    return (3 << 30) | (size << 16) | (_PTP_CLK_MAGIC << 8) | nr


PTP_SYS_OFFSET_EXTENDED = _iowr(9, _EXT_SIZE)


def sys_offset_request(n_samples: int = 9) -> bytearray:
    """The ``ptp_sys_offset_extended`` request: n samples against CLOCK_REALTIME."""
    if not 1 <= n_samples <= PTP_MAX_SAMPLES:
        raise ValueError(f"n_samples must be 1..{PTP_MAX_SAMPLES}")
    buf = bytearray(_EXT_SIZE)
    _EXT_HEADER.pack_into(buf, 0, n_samples, 0, 0, 0)
    return buf


def parse_sys_offset(buf: bytes) -> Tuple[int, int, int]:
    """``(system_ns, phc_minus_system_ns, window_ns)`` from a filled
    ``ptp_sys_offset_extended``: the reading with the shortest system window
    (linuxptp ``sysoff_estimate``)."""
    n = _EXT_HEADER.unpack_from(buf, 0)[0]
    if not 1 <= n <= PTP_MAX_SAMPLES:
        raise SourceError(f"PTP_SYS_OFFSET_EXTENDED returned {n} samples")
    best = None
    for i in range(n):
        t1, tp, t2 = (s * 1_000_000_000 + ns for s, ns, _ in
                      (_CLOCK_TIME.unpack_from(buf, _EXT_HEADER.size + (3 * i + k) * _CLOCK_TIME.size)
                       for k in range(3)))
        window, mid = t2 - t1, (t1 + t2) // 2
        if best is None or window < best[2]:
            best = (mid, tp - mid, window)
    assert best is not None
    return best


def read_phc(device: str = "/dev/ptp0", n_samples: int = 9) -> Tuple[int, int, int]:
    """Read a PHC against the system clock (see :func:`parse_sys_offset`)."""
    import fcntl

    buf = sys_offset_request(n_samples)
    try:
        fd = os.open(device, os.O_RDONLY)
    except OSError as exc:
        raise SourceError(f"cannot open {device}: {exc.strerror}") from exc
    try:
        fcntl.ioctl(fd, PTP_SYS_OFFSET_EXTENDED, buf, True)
    except OSError as exc:
        raise SourceError(f"PTP_SYS_OFFSET_EXTENDED on {device}: {exc.strerror}") from exc
    finally:
        os.close(fd)
    return parse_sys_offset(bytes(buf))


def phc_sample(sys_ns: int, phc_minus_sys_ns: int, window_ns: int, tai_utc: Optional[int] = None) -> Dict[str, object]:
    """A watch sample from one PHC reading; removes TAI - UTC (given, or the whole seconds)."""
    whole = int(tai_utc) if tai_utc is not None else round(phc_minus_sys_ns / 1e9)
    return {"time": sys_ns / 1e9, "offset": (phc_minus_sys_ns - whole * 1_000_000_000) / 1e9,
            "whole_seconds": float(whole), "read_window": window_ns / 1e9}


def sample_phc(cmd: Sequence[str] = ("/dev/ptp0",)) -> Dict[str, object]:
    """``cmd`` is ``[device]`` or ``[device, tai_utc_seconds]``."""
    device = cmd[0] if cmd else "/dev/ptp0"
    tai_utc = int(cmd[1]) if len(cmd) > 1 else None
    d = phc_sample(*read_phc(device), tai_utc=tai_utc)
    d["device"] = device
    return d


# --------------------------------------------------------------- Time Card
def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _int(v: Optional[str]) -> float:
    try:
        return float(int(v, 0)) if v is not None else float("nan")
    except ValueError:
        return float("nan")


def timecard_status(path: str = "/sys/class/timecard/ocp0") -> Dict[str, object]:
    """The status attributes of an OCP Time Card (``ptp_ocp`` sysfs)."""
    if not os.path.isdir(path):
        raise SourceError(f"{path} not found (is the ptp_ocp driver loaded?)")
    sync = _read(os.path.join(path, "gnss_sync"))
    ptp = os.path.join(path, "ptp")
    device = "/dev/" + os.path.basename(os.path.realpath(ptp)) if os.path.exists(ptp) else None
    return {
        "gnss_sync": float("nan") if sync is None else 1.0 if sync.startswith("SYNC") else 0.0,
        "gnss_lost": sync[len("LOST @"):].strip() if sync and sync.startswith("LOST") else "",
        "clock_source": _read(os.path.join(path, "clock_source")) or "",
        "utc_tai_offset": _int(_read(os.path.join(path, "utc_tai_offset"))),
        "fw_offset": _int(_read(os.path.join(path, "clock_status_offset"))),
        "fw_drift": _int(_read(os.path.join(path, "clock_status_drift"))),
        "serial": _read(os.path.join(path, "serialnum")) or "",
        "device": device,
    }


def sample_timecard(cmd: Sequence[str] = ("/sys/class/timecard/ocp0",)) -> Dict[str, object]:
    """``cmd`` is ``[sysfs directory]``; the PHC comes from its ``ptp`` link."""
    st = timecard_status(cmd[0] if cmd else "/sys/class/timecard/ocp0")
    if not st["device"]:
        raise SourceError("the Time Card has no ptp link")
    tai = float(st["utc_tai_offset"])  # type: ignore[arg-type]
    d = phc_sample(*read_phc(str(st["device"])), tai_utc=int(tai) if tai == tai and tai else None)
    d.update(st)
    return d


# -------------------------------------------------------------- ClockBound
CLOCKBOUND_STATUS = ("unknown", "synchronized", "free_running", "disrupted")


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


class _CbNow(ctypes.Structure):
    _fields_ = [("earliest", _Timespec), ("latest", _Timespec), ("clock_status", ctypes.c_int)]


class _CbErr(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_int), ("errno", ctypes.c_int), ("detail", ctypes.c_char * 128)]


_CB: Dict[str, object] = {}


def _clockbound(lib: Optional[str] = None):
    if "ctx" not in _CB:
        import ctypes.util

        name = lib or os.environ.get("NTPSTATS_LIBCLOCKBOUND") or ctypes.util.find_library("clockbound")
        if not name:
            raise SourceError("libclockbound not found: build clock-bound-ffi (github.com/aws/clock-bound) "
                              "or set NTPSTATS_LIBCLOCKBOUND to its path")
        try:
            so = ctypes.CDLL(name)
        except OSError as exc:
            raise SourceError(f"cannot load {name}: {exc}") from exc
        so.clockbound_open.restype = ctypes.c_void_p
        so.clockbound_open.argtypes = [ctypes.POINTER(_CbErr)]
        so.clockbound_now.restype = ctypes.c_void_p
        so.clockbound_now.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CbNow), ctypes.POINTER(_CbErr)]
        err = _CbErr()
        ctx = so.clockbound_open(ctypes.byref(err))
        if not ctx:
            raise SourceError(f"clockbound_open failed: {err.detail.decode(errors='replace') or err.kind}")
        _CB.update(lib=so, ctx=ctx)
    return _CB["lib"], _CB["ctx"]


def _dec(ns: int) -> str:
    return f"{'-' if ns < 0 else ''}{abs(ns) // 1_000_000_000}.{abs(ns) % 1_000_000_000:09d}"


def clockbound_sample(before_ns: int, after_ns: int, earliest_ns: int, latest_ns: int, status: int) -> Dict[str, object]:
    """A watch sample from one ``clockbound_now()`` result and the system clock read around it."""
    mid = (before_ns + after_ns) // 2
    return {"time": mid / 1e9, "offset": ((earliest_ns + latest_ns) // 2 - mid) / 1e9,
            "bound": (latest_ns - earliest_ns) / 2e9, "read_window": (after_ns - before_ns) / 1e9,
            "earliest": _dec(earliest_ns), "latest": _dec(latest_ns),  # exact ns, as text
            "status": CLOCKBOUND_STATUS[status] if 0 <= status < len(CLOCKBOUND_STATUS) else str(status),
            "synchronized": 1.0 if status == 1 else 0.0}


def sample_clockbound(cmd: Sequence[str] = ()) -> Dict[str, object]:
    """``cmd`` may name the library file (default: found on the library path)."""
    so, ctx = _clockbound(cmd[0] if cmd else None)
    res, err = _CbNow(), _CbErr()
    t0 = time.time_ns()
    bad = so.clockbound_now(ctx, ctypes.byref(res), ctypes.byref(err))
    t1 = time.time_ns()
    if bad:
        raise SourceError(f"clockbound_now failed: {err.detail.decode(errors='replace') or err.kind}")
    ns = (lambda ts: ts.tv_sec * 1_000_000_000 + ts.tv_nsec)  # noqa: E731
    return clockbound_sample(t0, t1, ns(res.earliest), ns(res.latest), res.clock_status)


# ------------------------------------------------------------------ fbclock
_FB = re.compile(r"Earliest:\s*(-?\d+).*?Latest:\s*(-?\d+)", re.S)


def parse_fbclock(text: str) -> Tuple[int, int]:
    """``(earliest_ns, latest_ns)`` from ``ptpcheck fbclock`` text output."""
    m = _FB.search(text)
    if not m:
        raise SourceError(f"unexpected ptpcheck fbclock output: {text[:80]!r}")
    return int(m.group(1)), int(m.group(2))


def sample_fbclock(cmd: Sequence[str] = ("ptpcheck",)) -> Dict[str, object]:
    t0 = time.time_ns()
    out = _run([*(cmd or ("ptpcheck",)), "fbclock", "--utc"])
    t1 = time.time_ns()
    e, la = parse_fbclock(out)
    d = clockbound_sample(t0, t1, e, la, 1)
    d.pop("status")
    d.pop("synchronized")
    return d


# ----------------------------------------------------------- ptp4l ports
_PORT_ID = re.compile(r"portIdentity\s+(\S+)")
_PORT_STATE = re.compile(r"portState\s+(\S+)")
_RECEIVER_STATES = {"SLAVE", "TIME_RECEIVER", "UNCALIBRATED"}


def parse_port_states(text: str) -> List[Tuple[int, str]]:
    """``[(port number, state)]`` from ``pmc`` PORT_DATA_SET responses (one per port)."""
    out = []
    for block in text.split("PORT_DATA_SET")[1:]:
        pid, st = _PORT_ID.search(block), _PORT_STATE.search(block)
        if pid and st:
            try:
                out.append((int(pid.group(1).rsplit("-", 1)[1]), st.group(1)))
            except (IndexError, ValueError):
                continue
    return out


def port_summary(ports: List[Tuple[int, str]]) -> Dict[str, object]:
    recv = [p for p, s in ports if s in _RECEIVER_STATES]
    if not ports:
        return {"ports": float("nan"), "port_states": "", "slave_port": float("nan"), "faulty_ports": float("nan")}
    return {"ports": float(len(ports)), "port_states": " ".join(f"{p}:{s}" for p, s in ports),
            "slave_port": float(recv[0]) if recv else float("nan"),
            "faulty_ports": float(sum(s == "FAULTY" for _, s in ports))}
