# Dataframes, notebooks and Parquet

ntpstats needs only numpy. Adapters for the data-science stack are optional and are loaded only
when used:

```bash
pip install "ntpstats[data]"     # pandas, pyarrow, xarray
```

```python
from ntpstats import load_one
from ntpstats.series import TimeSeries
from ntpstats.stability import compute, dynamic

s = load_one("/var/log/chrony/tracking.log")
df = s.to_pandas()                         # UTC DatetimeIndex; offset + extra columns; metadata in df.attrs
df["offset"].rolling("1h").std().plot()

s2 = TimeSeries.from_pandas(df)            # back (or any DataFrame: offset=..., time=..., negate=...)

r = compute(s.offset, 16.0, "oadev")
r.to_dataframe()                           # tau, dev, lo, hi, edf, alpha, noise, n

dynamic(s, "oadev", window=86400).to_xarray()   # (time, tau) DataArray for heat maps

s.to_parquet("tracking.parquet")           # float64 columns + metadata; every command reads it back
```

```bash
ntpstats convert big.log --to parquet -o big.parquet   # compact, exact, fast to reload
ntpstats stability big.parquet -k oadev,tdev
```

The package ships a `py.typed` marker, so type checkers see ntpstats' annotations.
