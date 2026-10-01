# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Optional adapters: pandas, xarray and Parquet/Arrow (no hard dependencies).

* :func:`to_pandas` / :func:`from_pandas`: a :class:`TimeSeries` as a
  DataFrame with a UTC ``DatetimeIndex`` (``offset`` plus the extra columns;
  name, format and metadata in ``df.attrs``).
* :func:`stability_to_dataframe`: one row per tau with the deviation, its
  interval, EDF, noise type and number of terms.
* :func:`dynamic_to_xarray`: sliding-window stability as a ``(time, tau)``
  DataArray.
* :func:`write_parquet` / :func:`read_parquet`: columnar files that keep
  float64 precision and the series metadata (Arrow schema metadata). Parquet
  files are auto-detected by every command.

Install what you need: ``pip install pandas``, ``xarray`` or ``pyarrow``
(``pip install 'ntpstats[data]'`` installs all three).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np

from .series import TimeSeries

PARQUET_MAGIC = b"PAR1"
_META_KEY = b"ntpstats"


def _need(module: str):
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(f"this needs {module}: pip install {module} (or 'ntpstats[data]')") from exc


def _jsonable(meta: Dict[str, object]) -> Dict[str, Any]:
    return json.loads(json.dumps(meta, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))


# ------------------------------------------------------------------ pandas
def to_pandas(series: TimeSeries):
    """DataFrame indexed by UTC time (ns precision) with ``offset`` and the extra columns."""
    pd = _need("pandas")
    ns = np.round(series.t * 1e9).astype("int64")
    df = pd.DataFrame({"offset": series.offset, **{k: v for k, v in series.extra.items()}},
                      index=pd.DatetimeIndex(pd.to_datetime(ns, unit="ns", utc=True), name="time"))
    df.attrs.update(name=series.name, source_format=series.source_format, meta=_jsonable(series.meta))
    return df


def from_pandas(df, offset: str = "offset", time: Optional[str] = None, name: Optional[str] = None,
                negate: bool = False) -> TimeSeries:
    """A :class:`TimeSeries` from a DataFrame.

    Time comes from a ``DatetimeIndex`` (naive times are taken as UTC) or the
    ``time`` column (datetimes, or numbers as POSIX seconds). ``offset`` is the
    column holding reference - local in seconds (``negate`` for local - reference);
    every other numeric column becomes an extra column.
    """
    pd = _need("pandas")
    col = df[time] if time is not None else df.index.to_series(index=df.index)
    if pd.api.types.is_datetime64_any_dtype(col):
        dti = pd.DatetimeIndex(pd.to_datetime(col, utc=True))
        t = ((dti - pd.Timestamp(0, tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)
    else:
        t = np.asarray(col, dtype=float)
    x = df[offset].to_numpy(dtype=float)
    extra = {c: df[c].to_numpy(dtype=float) for c in df.columns
             if c not in (offset, time) and pd.api.types.is_numeric_dtype(df[c])}
    attrs = getattr(df, "attrs", {}) or {}
    return TimeSeries(t=np.asarray(t, dtype=float), offset=-x if negate else x,
                      name=name or attrs.get("name", "") or "dataframe",
                      source_format=attrs.get("source_format", "pandas"), extra=extra,
                      meta=dict(attrs.get("meta", {}))).sorted()


def stability_to_dataframe(result):
    """One row per tau: ``tau, dev, lo, hi, edf, alpha, noise, n`` (attrs: kind, tau0, ci)."""
    pd = _need("pandas")
    from .stability import NOISE_NAMES

    nan = np.full(result.taus.shape, np.nan)
    alpha = result.alpha if result.alpha is not None else nan
    df = pd.DataFrame({
        "tau": result.taus, "dev": result.dev,
        "lo": result.lo if result.lo is not None else nan, "hi": result.hi if result.hi is not None else nan,
        "edf": result.edf if result.edf is not None else nan, "alpha": alpha,
        "noise": [NOISE_NAMES.get(int(a)) if np.isfinite(a) else None for a in alpha],
        "n": result.n.astype(int),
    })
    df.attrs.update(kind=result.kind, tau0=result.tau0, ci=result.ci)
    return df


# ------------------------------------------------------------------ xarray
def dynamic_to_xarray(dyn):
    """Sliding-window stability as an xarray ``DataArray`` with dims ``(time, tau)``."""
    xr = _need("xarray")
    pd = _need("pandas")
    times = pd.to_datetime(np.round(dyn.times * 1e9).astype("int64"), unit="ns", utc=True).tz_localize(None)
    return xr.DataArray(dyn.dev, dims=("time", "tau"), coords={"time": times, "tau": dyn.taus},
                        name=dyn.kind, attrs={"kind": dyn.kind, "tau0": dyn.tau0, "window_s": dyn.window,
                                              "step_s": dyn.step, "time_zone": "UTC"})


# ------------------------------------------------------------------ Parquet / Arrow
def to_arrow(series: TimeSeries):
    pa = _need("pyarrow")
    cols = {"unix_time": pa.array(series.t, type=pa.float64()), "offset": pa.array(series.offset, type=pa.float64())}
    cols.update({k: pa.array(v, type=pa.float64()) for k, v in series.extra.items()})
    table = pa.table(cols)
    meta = {"name": series.name, "source_format": series.source_format, "meta": _jsonable(series.meta),
            "schema": 1, "quantity": "offset = reference - local, seconds; unix_time = POSIX seconds"}
    return table.replace_schema_metadata({**(table.schema.metadata or {}), _META_KEY: json.dumps(meta).encode()})


def write_parquet(series: TimeSeries, path: str, compression: str = "zstd") -> None:
    """Write one series as Parquet (float64 columns, metadata kept)."""
    pq = _need("pyarrow.parquet")
    pq.write_table(to_arrow(series), path, compression=compression)


def from_arrow(table, name: Optional[str] = None) -> TimeSeries:
    md = (table.schema.metadata or {}).get(_META_KEY)
    info = json.loads(md) if md else {}
    cols = {c: table.column(c).to_numpy(zero_copy_only=False).astype(float) for c in table.column_names}
    time_col = next((c for c in ("unix_time", "time", "t") if c in cols), None)
    if time_col is None or "offset" not in cols:
        raise ValueError("Parquet/Arrow table needs 'unix_time' (or 'time') and 'offset' columns")
    extra = {k: v for k, v in cols.items() if k not in (time_col, "offset")}
    return TimeSeries(cols[time_col], cols["offset"], name=name or info.get("name", "") or "parquet",
                      source_format=info.get("source_format") or "parquet", extra=extra,
                      meta=dict(info.get("meta", {}))).sorted()


def read_parquet(source, name: Optional[str] = None) -> List[TimeSeries]:
    """Read a Parquet file written by :func:`write_parquet` (or any table with unix_time/offset)."""
    import io

    pq = _need("pyarrow.parquet")
    table = pq.read_table(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    return [from_arrow(table, name)]
