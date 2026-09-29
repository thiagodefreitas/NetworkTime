# Roadmap

Direction: make `ntpstats` a **general NetworkTime validation, evaluation and study tool**. It
should ingest any time-transfer log, apply the statistics used in metrology and in telecom
standards, and provide a reproducible test bench for synchronisation algorithms. Items are tracked
as [GitHub issues](https://github.com/thiagodefreitas/NetworkTime/issues).

## ✅ 2.0 (this release)
- Python 3 rewrite with numpy as the only runtime dependency.
- Parsers for ntpd/NTPsec loopstats, peerstats and rawstats; chrony tracking, measurements and
  statistics; CSV; and the 2012 logs. Signs are normalised.
- ADEV, OADEV, MDEV, TDEV, HDEV and MTIE, with χ² CIs, lag-1 ACF noise identification and gap-aware
  resampling.
- Network metrics (delay floor, wedge, asymmetry indicator, FPP) and the min-delay clock filter.
- Kalman filter (delay-weighted, gated) and RTS smoother, with a noise model fitted from ADEV.
- Simulator with ground truth and estimator benchmarks.
- Privacy-preserving SNTP client and polite monitor.
- Lightweight web UI (stdlib server + uPlot), CLI, and matplotlib report figures.
- Test suite validated without third-party stability libraries; CI on Python 3.9–3.13.

## 2.1 — Deeper statistics
- Full Greenhall–Riley EDF algorithm for every estimator (MDEV/TDEV/HDEV currently use the
  closed-form OADEV EDF as an approximation). ([#1](https://github.com/thiagodefreitas/NetworkTime/issues/1))
- Long-τ estimators: total deviation (TOTDEV, MTOT), Theo1/TheoH; time-interval error (TIE)
  and TIErms. ([#2](https://github.com/thiagodefreitas/NetworkTime/issues/2))
- Dynamic (sliding-window) ADEV to expose non-stationarity, such as path changes and temperature. ([#3](https://github.com/thiagodefreitas/NetworkTime/issues/3))
- Standards-mask overlays for TDEV/MTIE, with masks loaded from user-supplied CSV so no
  standards text is shipped (e.g. ITU-T G.8261.1/G.8262/G.8271.1). ([#4](https://github.com/thiagodefreitas/NetworkTime/issues/4))
- Frequency-data input and phase↔frequency conversion (ntpd `drift`, chrony `Freq`).

## 2.2 — More sources
- PTP: linuxptp (`ptp4l`, `phc2sys`, `ts2phc`) logs and PHC offsets. ([#5](https://github.com/thiagodefreitas/NetworkTime/issues/5))
- Live daemons: poll `chronyc -c` (tracking/sources/sourcestats) and NTPsec `ntpmon`/`ntpq`
  mode-6 variables. ([#6](https://github.com/thiagodefreitas/NetworkTime/issues/6))
- pcap/pcapng import of NTP/PTP packets, including hardware timestamps. ([#7](https://github.com/thiagodefreitas/NetworkTime/issues/7))
- An NTS (RFC 8915) measurement client, as an optional extra that needs a TLS 1.3 and
  AES-SIV implementation. ([#8](https://github.com/thiagodefreitas/NetworkTime/issues/8))
- Experimental NTPv5 (draft-ietf-ntp-ntpv5) client support, following the IETF work. ([#8](https://github.com/thiagodefreitas/NetworkTime/issues/8))
- Prometheus/OpenMetrics exporter for `ntpstats monitor`. ([#6](https://github.com/thiagodefreitas/NetworkTime/issues/6))

## 2.3 — Research bench
- Pluggable estimator API and scenario files (YAML/TOML), with reproducible benchmark reports
  (HTML) comparing algorithms across scenarios and seeds. ([#9](https://github.com/thiagodefreitas/NetworkTime/issues/9))
- Reference estimators: chrony-style regression, RADclock-style feed-forward, and RFC 5905
  clock filter plus selection/cluster/combine for multi-server scenarios. ([#10](https://github.com/thiagodefreitas/NetworkTime/issues/10))
- Richer simulation: flicker FM, temperature-driven wander, route changes and asymmetric steps,
  and server faults (falsetickers). ([#11](https://github.com/thiagodefreitas/NetworkTime/issues/11))

## UX and infrastructure
- A single-file self-contained HTML report export. ([#12](https://github.com/thiagodefreitas/NetworkTime/issues/12))
- Large-file performance: streaming parsers, >10 M samples, background computation. ([#13](https://github.com/thiagodefreitas/NetworkTime/issues/13))
- PyPI release, documentation site, container image. ([#14](https://github.com/thiagodefreitas/NetworkTime/issues/14))
- Type checking (mypy), linting (ruff), coverage in CI; cross-validation against published
  datasets and Stable32 results. ([#14](https://github.com/thiagodefreitas/NetworkTime/issues/14))
