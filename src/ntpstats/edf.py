# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Equivalent degrees of freedom (EDF) for stability variance estimates.

Every estimator in :mod:`ntpstats.stability` (ADEV, OADEV, MDEV, TDEV, HDEV)
is the mean of squares of a linear filter applied to the phase samples::

    z_i = sum_k c_k x_{i*stride + k},        var_hat = mean(z_i^2) / norm

For Gaussian power-law noise the phase is itself a linear filter of white
noise, ``x = h_alpha * w`` (Kasdin & Walter 1992, the same model used to
generate test data), so ``z = (c * h_alpha) * w`` and its autocovariance
``rho(k)`` follows exactly from the combined impulse response. Then::

    EDF = 2 E[var_hat]^2 / Var[var_hat] = M^2 rho(0)^2 / sum_{|k|<M} (M - |k|) rho(k*stride)^2

This is the discrete-time counterpart of the algorithm of Greenhall & Riley
("Uncertainty of stability variances based on finite differences", PTTI
2003). Their continuous-time model assumes the phase is averaged over each
sample interval, which over-estimates the EDF for instantaneous samples at
small averaging factors (for example by 17 % for white FM at m = 1). The
discrete computation is exact for sampled clock offsets and is verified by
Monte Carlo in ``tests/test_edf.py``.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

#: power-law exponents supported (S_y(f) ~ f^alpha)
ALPHAS = (2, 1, 0, -1, -2)
_MAX_TAPS = 1 << 16


def _phase_filter(alpha: int, n: int) -> np.ndarray:
    """First ``n`` Kasdin coefficients of the phase-noise filter for ``alpha``."""
    d = (2 - alpha) / 2.0
    if d == 0:
        return np.ones(1)
    k = np.arange(1, n)
    return np.concatenate(([1.0], np.cumprod((d + k - 1) / k)))


def _estimator_filter(kind: str, m: int):
    """Phase filter ``c`` and stride of each estimator's terms."""
    if kind in ("adev", "oadev"):
        c = np.zeros(2 * m + 1)
        c[[0, m, 2 * m]] = (1.0, -2.0, 1.0)
    elif kind in ("mdev", "tdev"):
        base = np.zeros(2 * m + 1)
        base[[0, m, 2 * m]] = (1.0, -2.0, 1.0)
        c = np.convolve(base, np.ones(m))
    elif kind == "hdev":
        c = np.zeros(3 * m + 1)
        c[[0, m, 2 * m, 3 * m]] = (1.0, -3.0, 3.0, -1.0)
    else:
        raise ValueError(f"no EDF model for {kind}")
    stride = m if kind == "adev" else 1
    return c, stride


@lru_cache(maxsize=512)
def _autocov(kind: str, alpha: int, m: int, max_lag: int) -> np.ndarray:
    c, stride = _estimator_filter(kind, m)
    if alpha in (2, 0, -2):
        # Integer orders: the differencing annihilates the polynomial growth of
        # h, so the combined response has finite support.
        taps = c.size + 2
    else:
        taps = int(min(_MAX_TAPS, max(8 * c.size, 4096)))
    # Keep only the part of the convolution where the truncated h contributes
    # fully; the tail would be an artefact of truncating h.
    g = np.convolve(c, _phase_filter(alpha, taps))
    g = g[: c.size + 1] if alpha in (2, 0, -2) else g[:taps]
    size = 1 << int(np.ceil(np.log2(2 * g.size)))
    G = np.fft.rfft(g, size)
    ac = np.fft.irfft(G * np.conj(G), size)[: g.size]
    lags = np.arange(0, max_lag + 1) * stride
    out = np.zeros(max_lag + 1)
    ok = lags < ac.size
    out[ok] = ac[lags[ok]]
    return out


def edf(kind: str, alpha: float, m: int, terms: int) -> float:
    """EDF of the ``kind`` estimate at averaging factor ``m`` built from
    ``terms`` squared filter outputs, for power-law noise ``alpha``."""
    a = int(np.clip(np.round(alpha), -2, 2)) if np.isfinite(alpha) else 0
    M = int(terms)
    if M < 1:
        return float("nan")
    c_len = _estimator_filter(kind, int(m))[0].size
    stride = int(m) if kind == "adev" else 1
    # Correlation vanishes (or is negligible) beyond the filter length.
    if a in (2, 0, -2):
        max_lag = min(M - 1, int(np.ceil(c_len / stride)) + 1)
    else:  # fractional noise: correlations decay slowly, use every available lag
        max_lag = min(M - 1, _MAX_TAPS // stride)
    rho = _autocov(kind, a, int(m), max_lag)
    k = np.arange(1, max_lag + 1)
    denom = rho[0] ** 2 * M + 2.0 * np.sum((M - k) * rho[1:] ** 2)
    if denom <= 0:
        return float("nan")
    return float(M * M * rho[0] ** 2 / denom)
