# Stable API

`ntpstats.api` is the public surface you can build on: scripts, notebooks, papers and other
packages. Everything listed on this page keeps working across minor releases. If a name or a
parameter has to change, it first goes through a deprecation period (below).

```python
from ntpstats import api as nt

s = nt.load_one("measurements.log", peer="192.0.2.10")
for r in nt.series_stability(s, kinds=("oadev", "tdev"), ci=0.95):
    print(r.kind, r.taus, r.dev, r.lo, r.hi)
df = s.to_pandas()                        # optional: pip install "ntpstats[data]"
```

The objects are the same as in their home modules (`nt.TimeSeries is ntpstats.series.TimeSeries`),
so existing imports such as `from ntpstats.stability import compute` keep working. The module
pages in this reference document the details.

## What "stable" means

- A name listed here is not removed or renamed, its parameters keep their names and order, and
  optional parameters stay optional, unless at least **one full minor release** of
  `NtpstatsDeprecationWarning` came first. The warning says when the name goes away and what to use
  instead; the removal is listed under *Removed* in the [changelog](https://github.com/thiagodefreitas/NetworkTime/blob/master/CHANGELOG.md).
- New optional parameters, new names, new result fields and new methods can arrive in any minor
  release.
- Numbers can change when a bug is fixed or an estimator is made more accurate; such changes are
  listed under *Fixed* or *Changed*, with the validation that supports them.
- `NtpstatsDeprecationWarning` is a `FutureWarning`, so it is shown by default in scripts and
  notebooks. To find deprecated calls in your own tests:
  `pytest -W error::ntpstats.deprecation.NtpstatsDeprecationWarning`.

The surface is frozen in `tests/data/api_surface.json`; CI fails on any incompatible change.

**Provisional**: everything that is not on this page. The protocol clients (`ntpstats.sntp`,
`ntpstats.nts`, `ntpstats.roughtime`) follow IETF drafts that still change, and the web UI,
exporters and per-format parser functions are internal. They work and are documented, but may
change in a minor release (always noted in the changelog).

## Data and input

| Name | What it is |
|---|---|
| `TimeSeries` | offset series: `t` (POSIX s), `offset` (s, reference − local), `extra`, `meta` ([series](series.md)) |
| `load`, `load_one` | read any supported log, capture or file; auto-detected ([parsers](parsers.md)) |
| `load_large`, `iter_chunks` | read very large text logs in blocks with bounded memory (see below) |
| `detect_format`, `all_formats` | format detection; every built-in and plugin format |
| `ParseError` | raised for unreadable input |
| `load_profile` | an instrument import profile ([profiles](profiles.md)) |
| `to_pandas`, `from_pandas`, `read_parquet`, `write_parquet` | dataframes and Parquet ([adapters](adapters.md)) |

## Stability

| Name | What it is |
|---|---|
| `KINDS` | the statistics: ADEV, MDEV, TDEV, HDEV, totals, Theo, MTIE, TIErms |
| `compute`, `compute_many`, `series_stability` | deviations with confidence intervals and noise ID ([stability](stability.md)) |
| `dynamic` | sliding-window stability |
| `StabilityResult`, `DynamicResult` | results (`to_dataframe()`, `to_xarray()`) |
| `edf`, `chi2_interval`, `identify_noise` | degrees of freedom, intervals, power-law noise identification ([edf](edf.md)) |

## Analysis and network

| Name | What it is |
|---|---|
| `summary`, `compare`, `detrend`, `remove_outliers`, `format_seconds` | ([analysis](analysis.md)) |
| `delay_stats`, `wedge`, `floor_packet_percentage`, `min_delay_filter` | ([network](network.md)) |

## Metrology

| Name | What it is |
|---|---|
| `series_spectrum`, `Spectrum` | phase/frequency PSD and L(f) ([spectrum](spectrum.md)) |
| `fit_noise`, `NoiseFit` | power-law noise model h₋₂…h₂ with intervals (`ntpstats.noisefit.fit_series`, [noisefit](noisefit.md)) |
| `hat_series`, `HatResult` | N-cornered hat and Groslambert covariance ([hat](hat.md)) |
| `holdover_series`, `HoldoverResult` | holdover prediction ([holdover](holdover.md)) |

## Time error, masks and assurance

| Name | What it is |
|---|---|
| `time_error`, `TimeErrorResult`, `check_time_error` | max\|TE\|, cTE, dTE and limits (`ntpstats.timeerror.check`, [timeerror](timeerror.md)) |
| `Mask`, `load_mask`, `check_mask` | stability limit masks (`ntpstats.masks.check`, [masks](masks.md)) |
| `audit`, `AuditConfig` | UTC traceability bound and evidence ([audit](audit.md)) |
| `detect_events`, `Event` | steps, spikes, frequency and route changes (`ntpstats.events.detect`, [events](events.md)) |
| `parse_bounds`, `validate_bounds` | clock-error bound validation (`ntpstats.bounds.validate`, [bounds](bounds.md)) |

## Estimators, simulation and the bench

| Name | What it is |
|---|---|
| `Estimator`, `FunctionEstimator` | the estimator interface ([estimators](estimators.md)) |
| `register_estimator`, `get_estimator`, `available_estimators`, `run_estimator` | registry (`ntpstats.estimators.register`, `get`, `available`, `run`) |
| `kalman_series` | Kalman filter and RTS smoother ([filters](filters.md)) |
| `Scenario`, `ClockModel`, `PathModel`, `PathEvent`, `ServerSpec`, `simulate_ntp`, `simulate_multi` | simulator with ground truth ([simulate](simulate.md)) |
| `load_scenarios`, `run_bench`, `score` | benchmark runner ([bench](bench.md)) |

## Traces, PTP chains and network simulators

| Name | What it is |
|---|---|
| `load_trace`, `trace_from_series`, `DelayTrace`, `TracePath` | per-direction delays of a capture or log, and their replay in the simulator ([trace](trace.md), [Trace replay](../research-bench.md)) |
| `ChainScenario`, `Link`, `simulate_chain`, `ChainResult`, `PIServo`, `LinRegServo` | PTP grandmaster and boundary-clock chains with servo models ([ptpsim](ptpsim.md)) |
| `read_omnetpp_vec`, `write_omnetpp_vec`, `inet_oscillator` | OMNeT++/INET vector files and oscillator settings ([simio](simio.md)) |

## Reports and extension points

| Name | What it is |
|---|---|
| `dataset_report`, `bench_report` | self-contained HTML reports ([report](report.md)) |
| `ParserPlugin`, `DetectorPlugin` | plugin types ([plugins](plugins.md)) |
| `NtpstatsDeprecationWarning` | the deprecation warning |

## Large files

`load` reads text logs above 256 MB in blocks by itself. To control the block size or to process
blocks one at a time:

```python
for block in nt.iter_chunks("/var/log/ntpstats/peerstats.all", chunk_lines=1_000_000):
    for s in block:
        print(s.meta.get("peer"), len(s))

series = nt.load_large("/data/tracking.log.gz", chunk_lines=500_000)   # gzip is streamed too
```

Streaming works for line-oriented formats: ntpd/NTPsec stats files, chrony logs, linuxptp, CSV and
the 2012 log. Header lines (CSV column names) are repeated for every block, so the result is the
same as `load`. Peak memory is about the size of the arrays plus one block of text, against
several times the file size for `load`.

::: ntpstats.stream
    options:
      members: [iter_chunks, load_large, streamable, STREAMABLE, STREAM_THRESHOLD]

## Deprecation helpers

For contributors: how a stable name is changed.

::: ntpstats.deprecation
    options:
      members: [NtpstatsDeprecationWarning, deprecated, renamed_parameter, moved]
