# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Streaming reader: same series as load(), bounded memory, gzip, synthetic time."""

import gzip
import os
import tracemalloc

import numpy as np
import pytest

from ntpstats import load, stream
from ntpstats.parsers import ParseError

DATA = os.path.join(os.path.dirname(__file__), "..", "examples", "data")
FILES = ["chrony-measurements.log", "chrony-refclocks.log", "chrony-tracking.log", "clockbound-reference.csv",
         "estimators-2012.log", "linuxptp.log", "loopstats.2012", "peerstats.example", "rawstats.example"]


def _by_key(series):
    return {(s.name, str(s.meta.get("peer", ""))): s for s in series}


def _same(a, b):
    ka, kb = _by_key(a), _by_key(b)
    assert ka.keys() == kb.keys()
    for k in ka:
        assert np.array_equal(ka[k].t, kb[k].t)
        assert np.array_equal(ka[k].offset, kb[k].offset)
        assert ka[k].extra.keys() == kb[k].extra.keys()
        for c in ka[k].extra:
            np.testing.assert_array_equal(ka[k].extra[c], kb[k].extra[c])
        assert ka[k].source_format == kb[k].source_format


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("chunk", [3, 7, 10**6])
def test_chunks_give_the_same_series_as_load(name, chunk):
    path = os.path.join(DATA, name)
    _same(load(path), stream.load_large(path, chunk_lines=chunk))


def test_peerstats_meta_is_merged():
    path = os.path.join(DATA, "peerstats.example")
    a, b = _by_key(load(path)), _by_key(stream.load_large(path, chunk_lines=5))
    for k in a:
        assert b[k].meta["sys_peer_fraction"] == pytest.approx(a[k].meta["sys_peer_fraction"])
        assert b[k].meta["chunks"] > 1


def test_csv_header_repeated_and_synthetic_time(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("offset,delay\n" + "".join(f"{i * 1e-6},{1e-3 + i * 1e-7}\n" for i in range(50)))
    a = load(str(p), tau0=2.0)
    b = stream.load_large(str(p), chunk_lines=8, tau0=2.0)
    _same(a, b)
    assert b[0].t[-1] == 98.0


def test_gzip_is_streamed(tmp_path):
    src = os.path.join(DATA, "loopstats.2012")
    gz = tmp_path / "loopstats.gz"
    with open(src, "rb") as fi, gzip.open(gz, "wb") as fo:
        fo.write(fi.read())
    _same(load(src), stream.load_large(str(gz), chunk_lines=4, name="loopstats.2012"))


def test_not_streamable_formats_are_refused():
    with pytest.raises(ValueError, match="cannot be streamed"):
        list(stream.iter_chunks(os.path.join(DATA, "ptp-capture.pcapng")))
    with pytest.raises(ValueError, match="cannot be streamed"):
        list(stream.iter_chunks(os.path.join(DATA, "w32tm-stripchart.txt")))


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.log"
    p.write_text("# nothing\n")
    with pytest.raises((ParseError, ValueError)):
        stream.load_large(str(p), fmt="loopstats")


def test_load_switches_to_streaming_for_large_files(monkeypatch):
    monkeypatch.setattr(stream, "STREAM_THRESHOLD", 0)
    monkeypatch.setattr(stream, "DEFAULT_CHUNK_LINES", 5)
    s = load(os.path.join(DATA, "chrony-tracking.log"))
    assert s[0].meta.get("chunks", 0) >= 1


def _loopstats(path, n):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(f"60000 {i % 86400}.000 {1e-6 * np.sin(i / 50):.9f} 1.234 0.000010 0.001 6\n")


def test_peak_memory_is_bounded(tmp_path):
    p = str(tmp_path / "big.loopstats")
    _loopstats(p, 60_000)

    def peak(fn):
        tracemalloc.start()
        fn()
        _, top = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return top

    full = peak(lambda: load(p, fmt="loopstats"))
    chunked = peak(lambda: stream.load_large(p, fmt="loopstats", chunk_lines=5_000))
    assert chunked < full / 3
