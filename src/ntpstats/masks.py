# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Limit masks for stability curves (e.g. TDEV/MTIE network limits).

Masks are *user supplied* (no standards text is bundled): a CSV/whitespace
file with two columns ``tau,limit`` (seconds, and the statistic's unit),
optionally with a header and ``#`` comments. A mask applies to one statistic:
the one named in the header's second column (``tau,tdev``, ``tau,mtie``,
``tau,oadev`` ...), else the ``kind`` argument, else TDEV. Between breakpoints the limit
is interpolated linearly in log-log coordinates, the way masks are drawn in
ITU-T recommendations. Outside the defined tau range the mask does not apply.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .stability import StabilityResult


@dataclass
class Mask:
    taus: np.ndarray
    limits: np.ndarray
    name: str = "mask"
    kind: str = "tdev"
    meta: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        order = np.argsort(self.taus)
        self.taus = np.asarray(self.taus, dtype=float)[order]
        self.limits = np.asarray(self.limits, dtype=float)[order]
        if self.taus.size < 1 or np.any(self.taus <= 0) or np.any(self.limits <= 0):
            raise ValueError("mask needs positive tau and limit values")

    def limit_at(self, tau) -> np.ndarray:
        tau = np.asarray(tau, dtype=float)
        if self.taus.size == 1:
            return np.where(np.isclose(tau, self.taus[0]), self.limits[0], np.nan)
        lt = np.interp(np.log10(tau), np.log10(self.taus), np.log10(self.limits))
        out = 10 ** lt
        out[(tau < self.taus[0] * (1 - 1e-9)) | (tau > self.taus[-1] * (1 + 1e-9))] = np.nan
        return out

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "taus": self.taus.tolist(), "limits": self.limits.tolist()}


def load_mask(source, name: Optional[str] = None, kind: Optional[str] = None) -> Mask:
    """Read a mask from a path, a file object, or mask text (a string that is
    not an existing file). ``kind`` overrides the statistic named in the header."""
    from .stability import KINDS

    if hasattr(source, "read"):
        text = source.read()
        label = name or getattr(source, "name", "mask")
    elif isinstance(source, (str, os.PathLike)) and os.path.isfile(source):
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        label = name or os.path.basename(str(source))
    else:
        text = str(source)
        label = name or "mask"
    taus: List[float] = []
    lims: List[float] = []
    header_kind = None
    for line in io.StringIO(text):
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        parts = [p for p in s.replace(",", " ").replace(";", " ").split() if p]
        try:
            t, v = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            if len(parts) >= 2 and parts[1].lower() in KINDS:
                header_kind = parts[1].lower()
            continue  # header
        taus.append(t)
        lims.append(v)
    k = (kind or header_kind or "tdev").lower()
    if k not in KINDS:
        raise ValueError(f"unknown mask kind {k!r}")
    return Mask(np.array(taus), np.array(lims), name=str(label), kind=k)


def check(result: StabilityResult, mask: Mask) -> dict:
    """Compare a stability result with a mask.

    Returns per-tau ``limit`` and ``margin`` (limit / value; > 1 passes) and
    an overall ``passed`` flag over the taus where the mask applies. The upper
    confidence bound is used when available, which is the conservative choice.
    """
    lim = mask.limit_at(result.taus)
    val = result.hi if result.hi is not None else result.dev
    with np.errstate(divide="ignore", invalid="ignore"):
        margin = lim / val
    applies = np.isfinite(lim)
    passed = bool(np.all(margin[applies] >= 1.0)) if applies.any() else None
    worst = float(np.nanmin(margin[applies])) if applies.any() else None
    return {
        "mask": mask.name,
        "limit": [None if not np.isfinite(v) else float(v) for v in lim],
        "margin": [None if not np.isfinite(v) else float(v) for v in margin],
        "passed": passed,
        "worst_margin": worst,
        "used_upper_bound": result.hi is not None,
    }
