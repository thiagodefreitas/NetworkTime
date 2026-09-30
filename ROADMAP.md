# Roadmap

**Mission:** a free, open (MIT) and dependency-light toolkit for **validating, evaluating and
studying network time**. It should be useful to engineers who deploy and certify NTP/PTP, and
to researchers who publish on clocks and time transfer, and it should interoperate with the tools
both groups already use (see the [tools landscape](docs/LANDSCAPE.md)). Items are
[GitHub issues](https://github.com/thiagodefreitas/NetworkTime/issues), labelled `industry`,
`research`, `community`, `good first issue` and `help wanted`.

*Reviewed 30 September 2026.*

## Who it is for, and what they need

| Audience | Today they use | What ntpstats should give them |
|---|---|---|
| **Operators** (NTP/NTS, cloud, enterprise) | chronyc, ntpq, Prometheus/Grafana, vendor GUIs | Statistics, masks and alerts on the dashboards they already have (#36); event detection (#23); support for the new daemons (#21) |
| **PTP / telecom / TSN engineers** | linuxptp, Wireshark, PTP Track Hound, Calnex/VIAVI/Keysight software | Free, transparent PTP capture analysis and time-error metrics (#19, #20); import of instrument exports (#35); CI checks for devices and firmware (#36) |
| **Regulated users** (finance, energy, critical infrastructure) | Vendor reports, manual evidence | A defensible UTC error bound and an archivable audit report (#22); holdover planning for GNSS outages (#26) |
| **Metrologists / time labs** | Stable32, TimeLab, allantools, CGGTTS tools | Proven agreement (#28), format and API compatibility (#33), spectra and noise fits (#25), cornered hat and covariance (#27), GNSS time transfer inputs (#34) |
| **Networking and systems researchers** | Ad-hoc scripts, OMNeT++/INET, ns-3, RIPE Atlas, NTP Pool data | Public datasets as inputs (#34), trace-driven bench and simulator interop (#29), an open longitudinal dataset (#30), citable software (#38) |

## Where the field is going

| Trend (2025–2026) | Consequence |
|---|---|
| PTP is the accuracy frontier: IEEE 1588 roll-up revision, NTS for PTP (draft -04), G.8273.2 class C/D | Analyse PTP packets and time error (#19, #20) |
| New daemons and stacks: ntpd-rs (Ubuntu 27.04 default), chrony 4.9, Meta's facebook/time, OCP Time Card | Parse what people actually run, and validate advertised uncertainty bounds (#21) |
| Regulation asks for evidence: MiFID II RTS 25, DORA, NIS2 | Error bounds and audit reports (#22) |
| GNSS jamming/spoofing is routine | Event detection and holdover prediction (#23, #26) |
| IETF: Roughtime (Experimental RFC approved), NTS pools, NTPv5, RFC 9769 | Measure the new protocols as they deploy (#24) |
| Measurement research at Internet scale (NTP Pool studies in PACMCS'24 and NDSS'26, NTS adoption surveys) | Read public datasets and publish our own (#34, #30) |
| Datacenter sync research (Huygens, Sundial, Firefly, SyncWise) and TSN simulation | Trace-driven bench, PTP servos, simulator interop (#29) |

## Done in 2.7 (quick wins)
- ✅ NIST SP 1065 test suites reproduced to 7 digits, MTOT bias correction, TTOT. ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28), first part)
- ✅ Stable32 files, `ntpstats convert`, allantools-compatible API. ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33); TimeLab `.tim` waits for sample files)
- ✅ Prometheus exporter, Grafana dashboard, alert rules, compose stack. ([#36](https://github.com/thiagodefreitas/NetworkTime/issues/36), first part)
- ✅ Code of conduct, security policy, issue forms, GHCR image. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38), first part; Discussions and Zenodo need the maintainer to switch them on)

## Releases

### 2.8: PTP and telecom
- ✅ PTP in captures: offset, per-direction delay, PDV, one-/two-step, E2E/P2P, NTS4PTP TLVs. ([#19](https://github.com/thiagodefreitas/NetworkTime/issues/19))
- ✅ Time-error metrics: max|TE|, cTE, dTE_L/H, max|TEL|, 1PPS/TIC input, limits and masks. ([#20](https://github.com/thiagodefreitas/NetworkTime/issues/20))

### 2.9: Sources and instruments
- ✅ More sources: linuxptp `pmc` and `ptpcheck` live, w32tm, Prometheus import (ntpd-rs, chrony_exporter), ClockBound/fbclock bound validation. Time Card, Timebeat and chrony 4.9 log checks wait for sample data. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- ✅ Instrument import profiles (TOML, built-ins for generic TIC/TE layouts); vendor profiles from contributed samples. ([#35](https://github.com/thiagodefreitas/NetworkTime/issues/35))

### 2.10: Trust and operations
- ✅ UTC traceability and compliance report (`ntpstats audit`). ([#22](https://github.com/thiagodefreitas/NetworkTime/issues/22))
- ✅ Anomaly and change-point detection (`ntpstats events`, UI list). ([#23](https://github.com/thiagodefreitas/NetworkTime/issues/23))
- ✅ CI integration: a GitHub Action (`uses: thiagodefreitas/NetworkTime@v2.10.0`) and pytest assertions. OpenTelemetry export remains. ([#36](https://github.com/thiagodefreitas/NetworkTime/issues/36))

### 2.11: Protocol watch
- ✅ Roughtime client and consistency checks, NTS-KE pools, the current NTPv5 draft, RFC 9769 interleaved mode, all in the weekly Live interop. ([#24](https://github.com/thiagodefreitas/NetworkTime/issues/24))

### 2.12: Metrology and research data
- ✅ Frequency domain and h_α noise fitting. ([#25](https://github.com/thiagodefreitas/NetworkTime/issues/25))
- ✅ Holdover and time-error prediction. ([#26](https://github.com/thiagodefreitas/NetworkTime/issues/26))
- ✅ Three-cornered hat and Groslambert covariance. ([#27](https://github.com/thiagodefreitas/NetworkTime/issues/27))
- Cross-validation, remaining parts: Stable32 CIs/EDF, a public long-term dataset. ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28))
- Ecosystem interop, remaining part: TimeLab `.tim` (✅ `htotdev`). ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33))
- ✅ Research data sources: RIPE Atlas, NTP Pool, CGGTTS (with common view), RINEX clock, Circular T; NTS campaign files via CSV profiles. ([#34](https://github.com/thiagodefreitas/NetworkTime/issues/34))

### 3.0: Platform
- Research bench v2: trace-driven, PTP servos and BC chains, OMNeT++/INET and ns-3 interop. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- Open measurement dataset from the weekly interop runs. ([#30](https://github.com/thiagodefreitas/NetworkTime/issues/30))
- In-browser edition (Pyodide) on the docs site. ([#31](https://github.com/thiagodefreitas/NetworkTime/issues/31))
- Stable API, pandas/xarray/Parquet, notebooks, deprecation policy. ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32))
- Plugin architecture for parsers, estimators, detectors, masks and profiles. ([#37](https://github.com/thiagodefreitas/NetworkTime/issues/37))

### Continuous: community and citability
JOSS paper, Zenodo DOIs, Discussions, contributor on-ramp, conda-forge and distribution packages,
a reproduction gallery, and outreach (FOSDEM, the IETF hackathon, ITSF, ATIS WSTS, PTTI/ION,
IFCS-EFTF, OCP TAP, time-nuts). ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))

## How priorities are set
1. **Reach per effort**: items that open a new audience with existing building blocks come
   first. For example, #19 and #20 reuse the masks, network metrics and reports.
2. **Trust**: anything that produces a number someone may act on (audit, TE pass/fail, holdover)
   ships with its definition documented and a validation test.
3. **Interoperate, don't replace**: read and write the formats of the tools people use, and
   show agreement with them.
4. **Contributor-shaped work**: formats, profiles and parsers are small and independent, and are
   labelled so newcomers can take them.

## Get involved
Comment on an issue you care about, share a sample log or instrument export (anonymised is fine),
or pick a `good first issue`. Data contributions are as valuable as code.
See [CONTRIBUTING.md](CONTRIBUTING.md).

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
| 2.7 | NIST SP 1065 validation, MTOT bias correction, TTOT; Stable32 files and allantools API; Prometheus exporter and Grafana dashboard; community on-ramp |
| 2.8 | PTP from packet captures ([#19](https://github.com/thiagodefreitas/NetworkTime/issues/19)); time-error metrics with limits and masks ([#20](https://github.com/thiagodefreitas/NetworkTime/issues/20)); ns-exact capture timestamps |
| 2.9 | ptp4l/ptpcheck live, w32tm, Prometheus import, clock-error bound validation, instrument profiles, `--negate` |
| 2.10 | UTC traceability audit ([#22](https://github.com/thiagodefreitas/NetworkTime/issues/22)); change detection ([#23](https://github.com/thiagodefreitas/NetworkTime/issues/23)); GitHub Action and pytest assertions ([#36](https://github.com/thiagodefreitas/NetworkTime/issues/36)) |
| 2.11 | Roughtime client with chained measurements and malfeasance reports; NTS pools; RFC 9769 interleaved mode (client and captures); all in the Live interop ([#24](https://github.com/thiagodefreitas/NetworkTime/issues/24)) |
| 2.12 | Power-law noise fit and spectra ([#25](https://github.com/thiagodefreitas/NetworkTime/issues/25)); holdover prediction ([#26](https://github.com/thiagodefreitas/NetworkTime/issues/26)); N-cornered hat and Groslambert covariance ([#27](https://github.com/thiagodefreitas/NetworkTime/issues/27)); CGGTTS, RINEX clock, Circular T, RIPE Atlas, NTP Pool ([#34](https://github.com/thiagodefreitas/NetworkTime/issues/34)); HTOT ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33)) |
