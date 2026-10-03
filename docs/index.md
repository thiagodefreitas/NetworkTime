# ntpstats

**Validate, evaluate and study network time synchronisation.**

ntpstats reads what time systems already produce:
- logs of ntpd, NTPsec, chrony and linuxptp;
- packet captures of NTP, NTP over PTP (RFC 10030) and PTP;
- GNSS time-transfer and laboratory files;
- network-simulator results.

It computes the statistics used in timing research and telecom standards, each with a stated
uncertainty: frequency stability with confidence intervals and noise identification, time
error, and an audited error bound to UTC. It measures servers itself with NTPv4, NTS, NTPv5 and
Roughtime clients, and its simulator with ground truth is a test bench for synchronisation
algorithms. Use it as a command-line tool, a Python library with a [stable API](api/stable.md),
a local web UI, or [in your browser](browser.md).

```bash
pip install ntpstats
ntpstats ui /var/log/chrony/measurements.log      # local web UI
ntpstats stability tracking.log -k oadev,tdev --ci 0.95
```

![Audit with verdict and error bound](img/ui-audit.png)

## Start here

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | install, the web UI and its shortcuts, first analyses |
| [CLI reference](cli.md) | every command and its options |
| [In your browser](browser.md) | the web UI running locally in the page (Pyodide), no install |
| [Notebooks & gallery](notebooks.md) | runnable notebooks and reproductions of published results |

## Analyse

| Page | What it covers |
|---|---|
| [Formats](formats.md) | every supported input, sign conventions, how to enable the logs |
| [Statistics](statistics.md) | ADEV … TheoH, MTIE, EDF and confidence intervals, masks, dynamic views |
| [Network & estimators](network.md) | delay floor, wedge, FPP, filters and estimators |
| [PTP captures & time error](ptp.md) | PTP and NTP over PTP from captures, max\|TE\|, cTE, dTE, limits and masks |
| [Sources, instruments & bounds](sources.md) | live daemons, instrument profiles, clock-error bound validation |
| [Metrology](metrology.md) | power-law noise model, spectra, cornered hat, holdover |
| [Research data](research-data.md) | CGGTTS, RINEX clock, Circular T, RIPE Atlas, NTP Pool, the interop dataset |

## Operate and comply

| Page | What it covers |
|---|---|
| [Audit, events & CI checks](assurance.md) | UTC traceability audit, change detection, GitHub Action, pytest assertions |
| [Monitoring](monitoring.md) | Prometheus/OpenMetrics, OpenTelemetry, Grafana |
| [Protocols](protocols.md) | NTS, NTS pools, NTPv5, Roughtime, RFC 9769 interleaved mode |

## Research and integration

| Page | What it covers |
|---|---|
| [Trace replay & PTP chains](research-bench.md) | real network delays in the bench, PTP exchanges and transparent clocks, boundary-clock chains, OMNeT++/INET and ns-3, reference algorithms |
| [Dataframes & Parquet](dataframes.md) | pandas, xarray, Parquet/Arrow |
| [Writing a plugin](plugins.md) | add formats, estimators, detectors, masks and profiles from your own package |
| [Stable32, TimeLab, allantools](migrating.md) | moving data and code over, and checking the numbers agree |
| [Stable API](api/stable.md) and [API reference](api/index.md) | the 3.x API promise and every module |

## Trust

| Page | What it covers |
|---|---|
| [Validation](validation.md) | how correctness is established, and how to validate your own setup |
| [Live interop](INTEROP.md) | monthly results against public NTP/NTS/NTPv5/Roughtime servers |
| [State of the art](STATE_OF_THE_ART.md) and [Tools landscape](LANDSCAPE.md) | where network time is in 2026, and how ntpstats relates to other tools |

ntpstats is MIT-licensed, © 2012–2026 Thiago de Freitas. The only runtime dependency is numpy;
everything else (plots, NTS, dataframes) is an optional extra.
