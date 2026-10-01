# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Optional pandas / xarray / Parquet adapters (#32). Skipped when the libraries are not installed."""

import numpy as np
import pytest

from ntpstats.series import TimeSeries
from ntpstats.stability import compute, dynamic

T = 1_790_000_000.123456789 + 16.0 * np.arange(500)


def series():
    rng = np.random.default_rng(1)
    return TimeSeries(T, np.cumsum(rng.normal(0, 1e-7, T.size)), name="host", source_format="chrony-tracking",
                      extra={"delay": np.full(T.size, 2e-3)}, meta={"peer": "192.0.2.1", "arr": np.arange(2)})


def test_pandas_round_trip():
    pd = pytest.importorskip("pandas")
    s = series()
    df = s.to_pandas()
    assert isinstance(df.index, pd.DatetimeIndex) and str(df.index.tz) == "UTC"
    assert list(df.columns) == ["offset", "delay"] and df.attrs["meta"]["peer"] == "192.0.2.1"
    back = TimeSeries.from_pandas(df)
    assert np.allclose(back.t, s.t, atol=1e-6, rtol=0) and np.array_equal(back.offset, s.offset)
    assert back.name == "host" and back.source_format == "chrony-tracking" and "delay" in back.extra
    # a plain DataFrame with a numeric time column and the opposite sign convention
    plain = pd.DataFrame({"epoch": s.t, "err": -s.offset, "label": "x"})
    b2 = TimeSeries.from_pandas(plain, offset="err", time="epoch", negate=True, name="p")
    assert np.array_equal(b2.offset, s.offset) and "label" not in b2.extra


def test_stability_dataframe_and_dynamic_xarray():
    pytest.importorskip("pandas")
    s = series()
    r = compute(s.offset, 16.0, "oadev")
    df = r.to_dataframe()
    assert list(df.columns) == ["tau", "dev", "lo", "hi", "edf", "alpha", "noise", "n"]
    assert np.allclose(df["dev"], r.dev) and df.attrs["kind"] == "oadev" and df["noise"].notna().all()
    xr = pytest.importorskip("xarray")
    d = dynamic(s, "oadev", window=2000, step=500)
    da = d.to_xarray()
    assert isinstance(da, xr.DataArray) and da.dims == ("time", "tau") and da.shape == d.dev.shape


def test_parquet_round_trip_and_auto_detection(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    from ntpstats.cli import main
    from ntpstats.parsers import load

    s = series()
    p = tmp_path / "x.parquet"
    s.to_parquet(str(p))
    (back,) = load(str(p))
    assert np.array_equal(back.t, s.t) and np.array_equal(back.offset, s.offset)  # float64 exact
    assert back.name == "host" and back.meta["peer"] == "192.0.2.1" and np.array_equal(back.extra["delay"], s.extra["delay"])
    csv = tmp_path / "y.csv"
    csv.write_text("unix_time,offset\n" + "".join(f"{float(a)!r},{float(b)!r}\n" for a, b in zip(s.t, s.offset)))
    out = tmp_path / "y.parquet"
    assert main(["convert", str(csv), "--to", "parquet", "-o", str(out)]) == 0
    assert main(["info", str(out)]) == 0
    assert "500" in capsys.readouterr().out


def test_missing_library_gives_a_clear_message(monkeypatch):
    import builtins

    from ntpstats import adapters

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("pandas"):
            raise ImportError("no pandas")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    monkeypatch.setattr("importlib.import_module", lambda n: fake(n))
    with pytest.raises(ImportError, match="pip install pandas"):
        adapters.to_pandas(series())
