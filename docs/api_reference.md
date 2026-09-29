# API Reference

ntpstats can be used as a library in Python scripts.

## `ntpstats.load`

```python
from ntpstats import load

datasets = load("examples/data/loopstats.2012")
for ds in datasets:
    print(ds.name, len(ds.timestamps))
```

## `ntpstats.TimeSeries`

Represents a loaded time series of offsets and delays.
