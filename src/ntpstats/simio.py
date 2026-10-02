# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Exchange with network simulators: OMNeT++/INET and ns-3 (#29).

Import
------
* **OMNeT++ output vectors** (``.vec``, result file format versions 2 and 3):
  every vector becomes a series. INET clocks record ``timeChanged:vector``,
  the clock's time at each change; ntpstats turns it into time error relative
  to simulation time (``TE = clock time − simulation time``) and the usual
  offset ``reference − local = −TE``. Other vectors (``pdelay``,
  ``gmRateRatio``, your own) are selected with ``vectors`` and kept as raw
  values. ``.vec`` files are auto-detected by every command.
* **ns-3** results: packet captures from ``PcapHelper`` are read like any other
  capture (NTP and PTP), and two-column text from ``FileHelper`` or
  ``GnuplotHelper`` (time, value) is read as CSV (``-f csv``).

Export
------
* :func:`write_omnetpp_vec` writes series as an OMNeT++ vector file, to be
  plotted next to simulation results in the OMNeT++ IDE or ``opp_scavetool``.
* :func:`write_columns` writes ``time value`` text for ns-3 programs and
  gnuplot.
* :func:`inet_oscillator` maps a fitted power-law noise model to INET's
  ``RandomDriftOscillator``: the drift rate does a random walk with an
  increment drawn from ``uniform(-a, a)`` ppm every ``changeInterval`` T. A
  random walk of frequency with step variance σ² per T has
  ``S_y(f) = σ²/(2π² T f²)``, so ``h₋₂ = σ²/(2π² T)`` and
  ``a = √3 · σ = √(6π² h₋₂ T)``. Only the random-walk FM part and the
  frequency offset carry over; the other noise types and the linear drift
  are reported, with what they contribute to ADEV at 1 s and 1000 s, so the
  loss is visible.
"""

from __future__ import annotations

import fnmatch
import math
import re
import shlex
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

from .series import TimeSeries

_VEC_HEAD = re.compile(r"^\s*version\s+\d+\s*$")
CLOCK_VECTORS = ("timeChanged:vector", "timeChanged")


class SimFormatError(ValueError):
    pass


def is_omnetpp_vec(lines: Sequence[str]) -> bool:
    head = [ln for ln in lines[:200] if ln.strip()]
    return bool(head) and bool(_VEC_HEAD.match(head[0])) and any(ln.startswith("vector ") for ln in head)


def detect(lines: Sequence[str]) -> float:
    return 1.0 if is_omnetpp_vec(lines) else 0.0


def _vectors(lines: Iterable[str]):
    decl: Dict[str, dict] = {}
    data: Dict[str, List[List[float]]] = {}
    run_attrs: Dict[str, str] = {}
    last = None
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        head = s.split(None, 1)[0]
        if head == "vector":
            parts = shlex.split(s)
            if len(parts) < 4:
                raise SimFormatError(f"bad vector declaration: {s[:80]}")
            vid, module, name = parts[1], parts[2], parts[3]
            cols = parts[4] if len(parts) > 4 and re.fullmatch(r"[ETV]+", parts[4]) else "ETV"
            decl[vid] = {"module": module, "name": name, "columns": cols, "attrs": {}}
            data[vid] = []
            last = vid
        elif head == "attr":
            parts = shlex.split(s)
            if len(parts) >= 3:
                (decl[last]["attrs"] if last is not None else run_attrs)[parts[1]] = parts[2]
        elif head in ("version", "run", "param", "itervar", "config", "file"):
            continue
        elif head in decl:
            vals = s.split()
            try:
                data[head].append([float(v) for v in vals[1:]])
            except ValueError:
                continue
    return decl, data, run_attrs


def read_omnetpp_vec(lines: Sequence[str], name: str = "omnetpp", vectors: Optional[str] = None,
                     modules: Optional[str] = None) -> List[TimeSeries]:
    """Series from an OMNeT++ ``.vec`` file.

    By default every clock vector (``timeChanged``) becomes the time error of
    that clock relative to simulation time. ``vectors`` (a glob on the vector
    name, e.g. ``"pdelay*"``) and ``modules`` (a glob on the module path)
    select other vectors, kept as raw values in the ``offset`` column.
    """
    decl, data, run_attrs = _vectors(lines)
    if not decl:
        raise SimFormatError("no vectors in the file")
    try:  # files written by ntpstats keep the POSIX time of simulation time 0
        epoch = float(run_attrs.get("epoch_unix", 0.0))
    except ValueError:
        epoch = 0.0
    out = []
    for vid, d in decl.items():
        if modules and not fnmatch.fnmatch(d["module"], modules):
            continue
        is_clock = d["name"] in CLOCK_VECTORS
        if vectors is None and not is_clock:
            continue
        if vectors is not None and not fnmatch.fnmatch(d["name"], vectors):
            continue
        rows = data[vid]
        if not rows:
            continue
        cols = d["columns"]
        a = np.array([r[:len(cols)] for r in rows if len(r) >= len(cols)], dtype=float)
        if a.size == 0 or "T" not in cols or "V" not in cols:
            continue
        t, v = a[:, cols.index("T")], a[:, cols.index("V")]
        t_abs = t + epoch
        meta = {"peer": d["module"], "vector": d["name"], "unit": d["attrs"].get("unit"), "simulator": "omnetpp",
                "time_base": "simulation time (s)"}
        if is_clock and vectors is None:
            te = v - t
            meta["quantity"] = "time error of the clock relative to simulation time (offset = -TE)"
            s = TimeSeries(t_abs, -te, name=f"{name} [{d['module']}]", source_format="omnetpp-vec", meta=meta)
        else:
            meta["quantity"] = f"raw values of {d['name']}"
            s = TimeSeries(t_abs, v, name=f"{name} [{d['module']} {d['name']}]", source_format="omnetpp-vec",
                           meta=meta)
        out.append(s.sorted())
    if not out:
        names = sorted({f"{d['module']} {d['name']}" for d in decl.values()})
        hint = "; select one with vectors='name-glob'" if vectors is None else ""
        raise SimFormatError(f"no matching vectors{hint}. Vectors in the file: {', '.join(names[:12])}"
                             + (" ..." if len(names) > 12 else ""))
    return out


def _regroup(series: List[TimeSeries]) -> List[TimeSeries]:
    """Series written by :func:`write_omnetpp_vec`: each module's ``offset``/``timeError`` vector with the
    module's other vectors (same times) as extra columns again."""
    mains = [s for s in series if s.meta.get("vector") in ("offset:vector", "timeError:vector")]
    if not mains:
        return series
    out = []
    for m in mains:
        extra = {str(o.meta["vector"]).split(":")[0]: o.offset for o in series
                 if o is not m and o.meta.get("peer") == m.meta["peer"] and o.t.shape == m.t.shape
                 and np.array_equal(o.t, m.t)}
        off = -m.offset if m.meta["vector"] == "timeError:vector" else m.offset
        meta = dict(m.meta, quantity="offset (reference - local) written by ntpstats")
        out.append(TimeSeries(m.t, off, name=m.name.replace(f" {m.meta['vector']}", ""), source_format="omnetpp-vec",
                              extra=extra, meta=meta))
    return out


def parse_omnetpp(lines, name: str = "omnetpp") -> List[TimeSeries]:
    """Parser entry (``-f omnetpp-vec``): the clock vectors; else series written by ntpstats; else every vector."""
    try:
        return read_omnetpp_vec(lines, name)
    except SimFormatError as exc:
        if "no matching vectors" in str(exc):
            return _regroup(read_omnetpp_vec(lines, name, vectors="*"))
        raise


def _q(s: str) -> str:
    return s if re.fullmatch(r"[^\s\"\\]+", s) else '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_omnetpp_vec(series: Sequence[TimeSeries], run: str = "ntpstats", te: bool = False,
                      epoch: Optional[float] = None) -> str:
    """An OMNeT++ vector file (version 3, ``ETV``) with one vector per series and per extra column.

    Time is seconds from ``epoch`` (default: the first sample), as simulation
    time. ``te=True`` writes the time error (−offset) instead of the offset.
    """
    if not series:
        raise ValueError("nothing to write")
    t0 = min(float(s.t[0]) for s in series) if epoch is None else float(epoch)
    head = ["version 3", f"run {_q(run)}", "attr generator ntpstats", f"attr epoch_unix {t0!r}", ""]
    body: List[str] = []
    vid = 0
    for s in series:
        module = re.sub(r"\s+", "_", str(s.meta.get("peer") or s.name)) or "series"
        cols = {("timeError:vector" if te else "offset:vector"): (-s.offset if te else s.offset)}
        cols.update({f"{k}:vector": v for k, v in s.extra.items()})
        for vname, vals in cols.items():
            head.append(f"vector {vid} {_q(module)} {_q(vname)} ETV")
            head.append("attr unit s" if vname.split(":")[0] in ("offset", "timeError", "delay") else "attr unit -")
            ok = np.isfinite(vals)
            for k, (tt, vv) in enumerate(zip(s.t[ok] - t0, np.asarray(vals)[ok])):
                body.append(f"{vid}\t{k}\t{tt:.12g}\t{vv:.12g}")
            vid += 1
    return "\n".join(head) + "\n" + "\n".join(body) + "\n"


def write_columns(series: TimeSeries, column: str = "offset", epoch: Optional[float] = None) -> str:
    """``time value`` text (one sample per line, seconds), as ns-3's FileHelper and gnuplot use."""
    vals = series.offset if column == "offset" else series.extra[column]
    t0 = float(series.t[0]) if epoch is None else float(epoch)
    return "".join(f"{t - t0:.9f} {v:.12e}\n" for t, v in zip(series.t, vals) if np.isfinite(v))


# ------------------------------------------------------------------ INET oscillator
def _adev_contrib(h: Dict[int, float], tau: float, tau0: float) -> Dict[int, float]:
    from .noisefit import basis

    m = max(1, int(round(tau / tau0)))
    return {a: math.sqrt(max(v, 0.0) * basis("oadev", m, a, tau0)) for a, v in h.items() if v > 0}


def inet_oscillator(h: Dict[int, float], freq_offset: float = 0.0, drift: float = 0.0, change_interval: float = 1.0,
                    module: str = "**.clock.oscillator", tau0: float = 1.0) -> Dict[str, object]:
    """INET ``RandomDriftOscillator`` settings that reproduce random-walk FM ``h[-2]`` and a frequency offset.

    ``tau0`` is the sample interval the ``h`` were fitted at (the ADEV of what
    is lost is reported at ``tau0`` and 1000 s). Returns
    ``{"ini": text, "a_ppm": ..., "lost": [...]}``.
    """
    h = {int(a): float(v) for a, v in h.items()}
    h_rw = max(h.get(-2, 0.0), 0.0)
    sigma = math.sqrt(2 * math.pi ** 2 * h_rw * change_interval)
    a_ppm = math.sqrt(3.0) * sigma * 1e6
    lines = [f'{module}.typename = "RandomDriftOscillator"',
             f"{module}.initialDriftRate = {freq_offset * 1e6:.6g}ppm",
             f"{module}.changeInterval = {change_interval:g}s",
             f"{module}.driftRateChange = uniform({-a_ppm:.6g}ppm, {a_ppm:.6g}ppm)"]
    names = {2: "white PM", 1: "flicker PM", 0: "white FM", -1: "flicker FM", -2: "random-walk FM"}
    lost = []
    for a in (2, 1, 0, -1):
        if h.get(a, 0.0) > 0:
            c0 = _adev_contrib({a: h[a]}, tau0, tau0)[a]
            c1000 = _adev_contrib({a: h[a]}, max(1000.0, tau0), tau0)[a]
            lost.append({"noise": names[a], "h": h[a], "adev_tau0": c0, "adev_1000s": c1000})
    if drift:
        lost.append({"noise": "linear frequency drift", "drift_per_s": drift,
                     "adev_1000s": abs(drift) * 1000.0 / math.sqrt(2)})
    note = ["# ntpstats: random-walk FM h(-2) = %.3g, frequency offset %.3g" % (h_rw, freq_offset),
            "# A random walk of the drift rate with uniform(-a, a) steps every changeInterval T has",
            "# h(-2) = a^2 / (6 pi^2 T)."]
    if h_rw <= 0:
        note.append("# no random-walk FM in the fit: the drift rate stays at initialDriftRate")
    for x in lost:
        note.append(f"# not represented: {x['noise']}"
                    + (f" (ADEV contribution {x['adev_tau0']:.2g} at {tau0:g} s, {x['adev_1000s']:.2g} at "
                       f"{max(1000.0, tau0):g} s)" if "adev_tau0" in x else f" (about {x['adev_1000s']:.2g} of ADEV "
                                                                             "at 1000 s)"))
    return {"ini": "\n".join(note + lines) + "\n", "a_ppm": a_ppm, "h_rw": h_rw, "change_interval": change_interval,
            "lost": lost}


def random_drift_phase(n: int, tau0: float, a_ppm: float, change_interval: float, initial_ppm: float = 0.0,
                       rng=None) -> np.ndarray:
    """Phase (s) of INET's RandomDriftOscillator semantics, sampled every ``tau0`` (for checking the mapping)."""
    rng = np.random.default_rng(rng)
    t = np.arange(n) * tau0
    k = np.floor(t / change_interval).astype(int)
    steps = rng.uniform(-a_ppm, a_ppm, int(k.max()) + 1) * 1e-6
    steps[0] = 0.0
    y = initial_ppm * 1e-6 + np.cumsum(steps)[k]
    return np.concatenate(([0.0], np.cumsum(y[:-1] * tau0)))
