# Roadmap

Direction: make `ntpstats` a **general NetworkTime validation, evaluation and study tool**. It
should ingest any time-transfer log, apply the statistics used in metrology and in telecom
standards, and provide a reproducible test bench for synchronisation algorithms. Items are tracked
as [GitHub issues](https://github.com/thiagodefreitas/NetworkTime/issues).

*Reviewed 30 September 2026.*

## Where the field is going, and what it means for ntpstats

| Trend (2025–2026) | Consequence for the project |
|---|---|
| PTP is the accuracy frontier: IEEE 1588 roll-up revision in comment resolution, NTS for PTP (draft-ietf-ntp-nts-for-ptp-04), G.8273.2 class C/D (max\|TE\| 30 ns / max\|TEL\| 5 ns) | Analyse PTP **packets** and **time error**, not just daemon logs (#19, #20) |
| New daemons: ntpd-rs becomes Ubuntu's default (27.04); chrony 4.9 (RFC 10030 NTP-over-PTP); Windows and cloud clock-error bounds | Parse what people actually run, and verify advertised bounds (#21) |
| Regulation asks for *evidence*: MiFID II RTS 25 (100 µs / 1 ms, traceable to UTC), DORA, NIS2 | A defensible error **bound** and an archivable report (#22) |
| GNSS jamming/spoofing is routine; resilience and holdover matter | Event detection (#23) and holdover prediction (#26) |
| IETF: Roughtime approved as Experimental RFC, NTS pools, NTPv5 drafts -08/-09, interleaved mode RFC 9769 | Measure the new protocols as they deploy (#24) |
| Metrology practice: spectra, power-law fits, cornered-hat/covariance methods, Stable32 as the reference | Complete the IEEE 1139 / SP 1065 toolbox and prove agreement (#25, #27, #28) |
| Datacenter research (Huygens, Sundial, Firefly, SyncWise) evaluates algorithms on real traces | Trace-driven bench, PTP servos, boundary-clock chains (#29) |
| Little open longitudinal data on public NTP/NTS servers | Publish the weekly interop measurements as a citable dataset (#30) |

## Next releases

### 2.7: PTP and telecom time error
- **PTP in captures**: IEEE 1588 v2/v2.1 dissection (UDP and L2, one-/two-step,
  correctionField), offset, per-direction delay and PDV per flow, and NTS4PTP TLV detection. ([#19](https://github.com/thiagodefreitas/NetworkTime/issues/19))
- **Time-error metrics**: max|TE|, cTE, dTE_L/dTE_H (0.1 Hz), max|TEL|, with scalar limits in
  masks, 1PPS/TIC input, and `ntpstats timeerror`. ([#20](https://github.com/thiagodefreitas/NetworkTime/issues/20))
- **More sources**: ntpd-rs, Windows `w32tm`, AWS ClockBound bound validation, linuxptp `pmc` live
  polling, and chrony 4.9. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))

### 2.8: Trust and assurance
- **UTC traceability and compliance report**: per-interval error bound (offset + asymmetry +
  root delay/dispersion + reference), with gaps counted as unknown, and an HTML/JSON report with an
  input manifest. `ntpstats audit`. ([#22](https://github.com/thiagodefreitas/NetworkTime/issues/22))
- **Anomaly and change-point detection**: steps, frequency jumps, route and asymmetry changes,
  falsetickers, leap smears and spoofing-like signatures, scored on the simulator. ([#23](https://github.com/thiagodefreitas/NetworkTime/issues/23))
- **Protocol watch**: Roughtime client with consistency checks, NTS-KE pools, the current NTPv5
  draft, and RFC 9769 interleaved mode, all in the weekly Live interop. ([#24](https://github.com/thiagodefreitas/NetworkTime/issues/24))

### 2.9: Metrology depth
- **Frequency domain and noise fitting**: S_x(f), S_y(f) and L(f), a joint h_α fit with CIs, and
  a fitted model as simulator input. ([#25](https://github.com/thiagodefreitas/NetworkTime/issues/25))
- **Holdover and prediction**: TIE(t) envelope and time-to-violation, calibrated on real
  and simulated outages. ([#26](https://github.com/thiagodefreitas/NetworkTime/issues/26))
- **Three-cornered hat and Groslambert covariance**: per-server stability without a better
  reference. ([#27](https://github.com/thiagodefreitas/NetworkTime/issues/27))
- **Cross-validation**: NIST SP 1065 NBS data, Stable32 and a public dataset, with an agreement
  table in the docs. ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28))

### 3.0: Research platform and reach
- **Bench v2**: trace-driven simulation from captures, PTP PI/linreg servos, boundary-clock
  chains, and more reference algorithms. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- **Open measurement dataset** from the weekly interop runs, with a trends page and a DOI. ([#30](https://github.com/thiagodefreitas/NetworkTime/issues/30))
- **In-browser edition** (Pyodide) on the docs site: analyse logs locally with nothing uploaded. ([#31](https://github.com/thiagodefreitas/NetworkTime/issues/31))
- **Stable API**: pandas/xarray adapters, Parquet/Arrow, notebooks in CI, and a deprecation
  policy. ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32))

Priorities follow value per effort. #19 and #20 unlock the PTP audience and reuse the existing
masks and network metrics. #22 and #23 serve operators and regulated users. #25–#28 give
researchers what they would otherwise need Stable32 or lab software for. Suggestions and pull
requests are welcome on any item.

## Done

| Release | Highlights |
|---|---|
| 2.0 | Python 3 rewrite (numpy only); ntpd/NTPsec and chrony parsers; ADEV…MTIE with χ² CIs; network metrics; Kalman/RTS; simulator; privacy-preserving SNTP client; lightweight web UI |
| 2.1 | Exact discrete EDF ([#1](https://github.com/thiagodefreitas/NetworkTime/issues/1)); TOTDEV, Theo1, TIE ([#2](https://github.com/thiagodefreitas/NetworkTime/issues/2)); dynamic ADEV ([#3](https://github.com/thiagodefreitas/NetworkTime/issues/3)); masks ([#4](https://github.com/thiagodefreitas/NetworkTime/issues/4)) |
| 2.2 | linuxptp ([#5](https://github.com/thiagodefreitas/NetworkTime/issues/5)); live chrony/ntpd and refclocks ([#6](https://github.com/thiagodefreitas/NetworkTime/issues/6)); pcap NTP ([#7](https://github.com/thiagodefreitas/NetworkTime/issues/7)); NTS and NTPv5 clients ([#8](https://github.com/thiagodefreitas/NetworkTime/issues/8)) |
| 2.3 | Estimator API, scenarios and benchmarks ([#9](https://github.com/thiagodefreitas/NetworkTime/issues/9)); reference estimators ([#10](https://github.com/thiagodefreitas/NetworkTime/issues/10)); richer simulator ([#11](https://github.com/thiagodefreitas/NetworkTime/issues/11)); HTML report ([#12](https://github.com/thiagodefreitas/NetworkTime/issues/12)) |
| 2.4 | Performance ([#13](https://github.com/thiagodefreitas/NetworkTime/issues/13)), lint, coverage, Docker, security review, `compare` |
| 2.5 | MTOT, TheoBR, TheoH ([#15](https://github.com/thiagodefreitas/NetworkTime/issues/15)); docs site, wiki, mypy; tag-driven releases to PyPI |
| 2.6 | Fast MTOT/Theo family on million-sample logs ([#18](https://github.com/thiagodefreitas/NetworkTime/issues/18)) |
