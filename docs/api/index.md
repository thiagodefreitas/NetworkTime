# Python API

The **[stable API](stable.md)** (`from ntpstats import api as nt`) lists the names covered by the
deprecation policy, in one namespace. The module pages below document everything, including the
provisional parts.

```python
from ntpstats import load, load_one
from ntpstats.stability import series_stability
from ntpstats.analysis import summary, compare

s = load_one("/var/log/chrony/measurements.log", peer="192.0.2.10")
print(summary(s)["range_90"])
for r in series_stability(s, kinds=("oadev", "tdev"), ci=0.95):
    print(r.kind, r.taus, r.dev, r.lo, r.hi, r.alpha)
```

A [`TimeSeries`](series.md) has `t` (POSIX seconds), `offset` (seconds, reference − local),
`extra` (per-sample columns such as `delay`) and `meta`.

| Module | Contents |
|---|---|
| [`ntpstats.series`](series.md) | `TimeSeries` |
| [`ntpstats.parsers`](parsers.md) | `load`, `load_one`, per-format parsers |
| [`ntpstats.stability`](stability.md) | estimators, confidence intervals, noise ID, dynamic |
| [`ntpstats.edf`](edf.md) | equivalent degrees of freedom |
| [`ntpstats.analysis`](analysis.md) | summary, detrending, outliers, `compare` |
| [`ntpstats.network`](network.md) | delay floor, wedge, FPP, min-delay filter |
| [`ntpstats.filters`](filters.md) | Kalman filter and RTS smoother |
| [`ntpstats.estimators`](estimators.md) | estimator API and reference algorithms |
| [`ntpstats.simulate`](simulate.md) | clocks, paths, scenarios with ground truth |
| [`ntpstats.bench`](bench.md) | benchmark runner |
| [`ntpstats.sntp`](sntp.md), [`ntpstats.nts`](nts.md) | measurement clients (NTPv4, RFC 9769 interleaved, NTPv5, NTS, NTS pools) |
| [`ntpstats.roughtime`](roughtime.md) | Roughtime client, chained measurements, malfeasance reports |
| [`ntpstats.spectrum`](spectrum.md), [`ntpstats.noisefit`](noisefit.md) | PSDs, L(f); power-law noise fit h_α |
| [`ntpstats.hat`](hat.md), [`ntpstats.holdover`](holdover.md) | N-cornered hat / Groslambert covariance; holdover prediction |
| [`ntpstats.research`](research.md) | CGGTTS, RINEX clock, Circular T, RIPE Atlas, NTP Pool, the interop dataset |
| [`ntpstats.otlp`](otlp.md) | OpenTelemetry (OTLP/HTTP JSON) export |
| [`ntpstats.plugins`](plugins.md) | plugin entry points and discovery |
| [`ntpstats.adapters`](adapters.md) | pandas, xarray, Parquet/Arrow |
| [`ntpstats.api`](stable.md), `ntpstats.stream`, `ntpstats.deprecation` | stable surface, large files, deprecation helpers |
| [`ntpstats.masks`](masks.md), [`ntpstats.report`](report.md) | masks, HTML reports |
