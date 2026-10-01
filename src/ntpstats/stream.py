# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Streaming reader for very large line-oriented logs.

:func:`ntpstats.load` reads the whole file into memory as text before parsing,
which for a multi-gigabyte log costs several times the file size.
:func:`iter_chunks` reads ``chunk_lines`` lines at a time and parses each
block. :func:`load_large` joins the blocks into the same series ``load`` would
return, so peak memory is the size of the arrays plus one block of text.
``load`` switches to it by itself for files larger than
:data:`STREAM_THRESHOLD` bytes in a format listed in :data:`STREAMABLE`.

Header lines at the top of the file (a CSV header, comments) are repeated in
front of every block, so column names and detection work the same in every
block. Gzip-compressed logs are read as a stream too.
"""

from __future__ import annotations

import gzip
import io
import itertools
import os
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from .series import TimeSeries

#: Formats whose lines are independent records, so a file can be cut anywhere.
STREAMABLE = (
    "loopstats", "peerstats", "rawstats", "chrony-tracking", "chrony-measurements", "chrony-statistics",
    "chrony-refclocks", "linuxptp", "csv", "gsoc2012",
)
#: ``load`` streams files above this size (bytes) when the format allows it.
STREAM_THRESHOLD = 256 * 2**20
DEFAULT_CHUNK_LINES = 500_000
_HEAD_LINES = 2000


def _open(path) -> io.TextIOBase:
    with open(path, "rb") as fh:
        gz = fh.read(2) == b"\x1f\x8b"
    if gz:
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _prefix(head: List[str]) -> List[str]:
    """Leading lines that are not data (blank, comments, a CSV header)."""
    out = []
    for ln in head[:50]:
        s = ln.strip()
        if s and (s[0].isdigit() or (s[0] in "+-." and s[1:2].isdigit())):
            break
        out.append(ln)
    return out if len(out) < len(head) else []


def streamable(path, fmt: str = "auto") -> Optional[str]:
    """The detected format if ``path`` can be streamed, else None."""
    from .parsers import detect_format
    from .pcap import is_capture

    with open(path, "rb") as fh:
        magic = fh.read(4)
    if is_capture(magic) or magic == b"PAR1":
        return None
    if fmt == "auto":
        with _open(path) as fh:
            head = [ln.rstrip("\n") for ln in itertools.islice(fh, _HEAD_LINES)]
        try:
            fmt = detect_format(head)
        except ValueError:
            return None
    return fmt if fmt in STREAMABLE else None


def iter_chunks(path, fmt: str = "auto", chunk_lines: int = DEFAULT_CHUNK_LINES, tau0: Optional[float] = None,
                name: Optional[str] = None) -> Iterator[List[TimeSeries]]:
    """Parse a large log ``chunk_lines`` lines at a time; yields the series of each block.

    Only formats in :data:`STREAMABLE` can be cut into blocks; others raise
    ``ValueError`` (use :func:`ntpstats.load`). Blocks without usable samples
    (for example only comments) are skipped.
    """
    from .parsers import _PARSERS, ParseError, _name_of, parse_csv

    if chunk_lines < 1:
        raise ValueError("chunk_lines must be positive")
    label = name or _name_of(path)
    kind = streamable(path, fmt)
    if kind is None:
        raise ValueError(f"{label}: format {fmt!r} cannot be streamed; streamable: {', '.join(STREAMABLE)}")
    with _open(path) as fh:
        lines = (ln.rstrip("\n") for ln in fh)
        first = list(itertools.islice(lines, chunk_lines))
        prefix = _prefix(first)
        block, n_before, index = first, 0, 0
        while block:
            try:
                if kind == "csv":
                    series = parse_csv(block, label, tau0=tau0)
                else:
                    series = _PARSERS[kind](block, label)
            except ParseError:
                if index == 0 and not prefix and len(block) < chunk_lines:
                    raise
                series = []
            for s in series:
                s.meta.setdefault("file", label)
                if s.meta.get("synthetic_time") and tau0:
                    s.t = s.t + n_before * float(tau0)
                    n_before += len(s)
            if series:
                yield series
            index += 1
            rest = list(itertools.islice(lines, chunk_lines))
            block = prefix + rest if rest else []


def _key(s: TimeSeries) -> Tuple[str, str]:
    return s.name, str(s.meta.get("peer", ""))


def _take(group: List[TimeSeries], get, drop) -> np.ndarray:
    """Concatenate one column across blocks, releasing it from each block as it goes."""
    out = np.concatenate([get(s) for s in group])
    for s in group:
        drop(s)
    return out


def _merge(blocks: List[List[TimeSeries]]) -> List[TimeSeries]:
    """Join the series of consecutive blocks (same name and peer) into one series each.

    The blocks are emptied column by column, so peak memory stays near one copy
    of the data.
    """
    parts: Dict[Tuple[str, str], List[TimeSeries]] = {}
    for series in blocks:
        for s in series:
            parts.setdefault(_key(s), []).append(s)
    blocks.clear()
    empty = np.empty(0)
    out = []
    for group in parts.values():
        n = sum(len(s) for s in group)
        s0 = group[0]
        meta = dict(s0.meta)
        if any("skipped_lines" in s.meta for s in group):
            meta["skipped_lines"] = sum(int(str(s.meta.get("skipped_lines", 0))) for s in group)
        if "sys_peer_fraction" in meta and n:
            meta["sys_peer_fraction"] = sum(float(str(s.meta.get("sys_peer_fraction", 0.0))) * len(s)
                                            for s in group) / n
        meta["chunks"] = len(group)
        cols = list(dict.fromkeys(k for s in group for k in s.extra))
        extra = {}
        for k in cols:
            v = _take(group, lambda s, k=k: s.extra[k] if k in s.extra else np.full(len(s), np.nan),
                      lambda s, k=k: s.extra.pop(k, None))
            if v.dtype.kind != "f" or np.isfinite(v).any():
                extra[k] = v
        x = _take(group, lambda s: s.offset, lambda s: setattr(s, "offset", empty))
        t = _take(group, lambda s: s.t, lambda s: setattr(s, "t", empty))
        merged = TimeSeries(t, x, name=s0.name, source_format=s0.source_format, extra=extra, meta=meta)
        out.append(merged if len(t) < 2 or bool(np.all(np.diff(t) > 0)) else merged.sorted())
    return out


def load_large(path, fmt: str = "auto", chunk_lines: int = DEFAULT_CHUNK_LINES, tau0: Optional[float] = None,
               name: Optional[str] = None) -> List[TimeSeries]:
    """Like :func:`ntpstats.load` for a large file, reading it ``chunk_lines`` lines at a time."""
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError("load_large reads a file path")
    from .parsers import ParseError

    out = _merge(list(iter_chunks(path, fmt, chunk_lines, tau0, name)))
    if not out:
        raise ParseError(f"{name or path}: no usable samples")
    return out
