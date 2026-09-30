# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Drop-in functions with allantools-style signatures, computed by ntpstats.

Code written for `allantools <https://github.com/aewallin/allantools>`_ can
switch with one import::

    # import allantools as at
    from ntpstats.compat import allantools as at
    taus, devs, errs, ns = at.oadev(phase, rate=1.0, data_type="phase", taus="octave")

Every function takes ``(data, rate=1.0, data_type="phase", taus=None)`` and
returns ``(taus_used, devs, errs, ns)`` as allantools does:

* ``data_type="freq"`` data are integrated to phase (``x[0] = 0``);
* ``taus`` is ``"octave"`` (the default), ``"decade"``, ``"all"`` or an
  array of averaging times in seconds (rounded to multiples of ``1/rate``);
* ``errs`` is ``dev / sqrt(ns)``, and points with ``ns < 2`` are dropped.

Deliberate differences:

* ``mtotdev``/``ttotdev`` return the raw NIST SP 1065 eq. (27) value, like
  allantools; :func:`ntpstats.stability.compute` bias-corrects by default.
* ``theo1`` returns taus of ``0.75 * m / rate`` (the effective tau).
* ``htotdev`` is not implemented yet.

For confidence intervals, noise identification and gap handling use
:func:`ntpstats.stability.compute` directly.
"""

from __future__ import annotations

from typing import Tuple, Union

import numpy as np

from .. import stability as _st

Result = Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def frequency2phase(freqdata, rate: float) -> np.ndarray:
    """Integrate fractional frequency to phase (seconds), with ``x[0] = 0``."""
    y = np.asarray(freqdata, dtype=float)
    return np.concatenate(([0.0], np.cumsum(y) / float(rate)))


def phase2frequency(phase, rate: float) -> np.ndarray:
    """Fractional frequency from phase (seconds)."""
    return np.diff(np.asarray(phase, dtype=float)) * float(rate)


def _phase(data, rate: float, data_type: str) -> np.ndarray:
    if data_type == "phase":
        return np.asarray(data, dtype=float)
    if data_type == "freq":
        return frequency2phase(data, rate)
    raise ValueError("data_type must be 'phase' or 'freq'")


def _ms(taus: Union[None, str, np.ndarray, list], rate: float):
    if taus is None:
        return "octave"
    if isinstance(taus, str):
        if taus not in ("octave", "decade", "all"):
            raise ValueError("taus must be 'octave', 'decade', 'all' or an array of seconds")
        return taus
    m = np.unique(np.round(np.asarray(taus, dtype=float) * float(rate)).astype(int))
    return m[m >= 1]


def _run(kind: str, data, rate: float, data_type: str, taus, **kw) -> Result:
    x = _phase(data, rate, data_type)
    r = _st.compute(x, 1.0 / float(rate), kind, _ms(taus, rate), ci=None, **kw)
    return r.taus, r.dev, r.err, r.n


def adev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Allan deviation (non-overlapping)."""
    return _run("adev", data, rate, data_type, taus)


def oadev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Overlapping Allan deviation."""
    return _run("oadev", data, rate, data_type, taus)


def mdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Modified Allan deviation."""
    return _run("mdev", data, rate, data_type, taus)


def tdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Time deviation."""
    return _run("tdev", data, rate, data_type, taus)


def ohdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Overlapping Hadamard deviation."""
    return _run("hdev", data, rate, data_type, taus)


def hdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Hadamard deviation (non-overlapping, from phase decimated by m)."""
    x = _phase(data, rate, data_type)
    ms = _st.tau_multipliers(x.size, _ms(taus, rate), max_m=(x.size - 1) // 3)
    tau0 = 1.0 / float(rate)
    out_t, out_d, out_e, out_n = [], [], [], []
    for m in ms:
        xs = x[:: int(m)]
        d = xs[3:] - 3 * xs[2:-1] + 3 * xs[1:-2] - xs[:-3]
        d = d[np.isfinite(d)]
        if d.size < 2:
            continue
        dev = np.sqrt(np.mean(d * d) / (6.0 * (m * tau0) ** 2))
        out_t.append(m * tau0)
        out_d.append(dev)
        out_e.append(dev / np.sqrt(d.size))
        out_n.append(d.size)
    return np.array(out_t), np.array(out_d), np.array(out_e), np.array(out_n, dtype=float)


def totdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Total deviation."""
    return _run("totdev", data, rate, data_type, taus)


def mtotdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Modified total deviation (raw, without bias correction, as allantools)."""
    return _run("mtot", data, rate, data_type, taus, bias_correction=False)


def ttotdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Time total deviation (raw, without bias correction, as allantools)."""
    return _run("ttot", data, rate, data_type, taus, bias_correction=False)


def theo1(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Theo1 deviation; returned taus are the effective 0.75 * m / rate."""
    return _run("theo1", data, rate, data_type, taus)


def mtie(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Maximum time interval error."""
    return _run("mtie", data, rate, data_type, taus)


def tierms(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """RMS time interval error."""
    return _run("tierms", data, rate, data_type, taus)


def htotdev(data, rate=1.0, data_type="phase", taus=None) -> Result:
    """Hadamard total deviation: not implemented yet (see issue #33)."""
    raise NotImplementedError("htotdev is not implemented in ntpstats yet")


__all__ = ["adev", "oadev", "mdev", "tdev", "hdev", "ohdev", "totdev", "mtotdev", "ttotdev", "theo1", "mtie",
           "tierms", "htotdev", "frequency2phase", "phase2frequency"]
