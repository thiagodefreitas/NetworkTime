# Roadmap

**Mission:** a free, open (MIT) and dependency-light toolkit for **validating, evaluating and
studying network time**. It should be useful to engineers who deploy and certify NTP/PTP, and
to researchers who publish on clocks and time transfer, and it should interoperate with the tools
both groups already use (see the [tools landscape](docs/LANDSCAPE.md)). Items are
[GitHub issues](https://github.com/thiagodefreitas/NetworkTime/issues), labelled `industry`,
`research`, `community`, `good first issue` and `help wanted`.

*Reviewed 3 October 2026.*

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
- ✅ Code of conduct, security policy, issue forms, GHCR image. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38), first part)

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

### 2.13: Open data and integrations
- ✅ Open measurement dataset from the interop runs (monthly), versioned with each release. ([#30](https://github.com/thiagodefreitas/NetworkTime/issues/30))
- ✅ OpenTelemetry export. ([#36](https://github.com/thiagodefreitas/NetworkTime/issues/36))
- ✅ EDF cross-check against the SP 1065/Stable32 approximations; comparison with Stable32 output files waits for contributed runs. ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28))
- ✅ Roughtime compatibility with draft-08 servers (Cloudflare).

### 2.14: Platform foundations
- ✅ In-browser edition (Pyodide) on the docs site, checked against the installed package in CI. ([#31](https://github.com/thiagodefreitas/NetworkTime/issues/31))
- ✅ Plugin architecture for parsers, estimators, detectors, masks and profiles, with contract tests. ([#37](https://github.com/thiagodefreitas/NetworkTime/issues/37))
- ✅ pandas/xarray/Parquet adapters and `py.typed`. ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32))

### 2.15: Stable API and notebooks (completes [#32](https://github.com/thiagodefreitas/NetworkTime/issues/32))
- ✅ Stable API (`ntpstats.api`) with a frozen surface and a deprecation policy. ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32))
- ✅ Streaming reader for multi-GB logs. ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32), [#13](https://github.com/thiagodefreitas/NetworkTime/issues/13))
- ✅ Notebooks executed in CI, and the first gallery entry (NIST SP 1065). ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32), [#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))

### 2.16: Research bench v2, part 1 (trace-driven and PTP) ✅
- ✅ Trace replay: per-direction delays from captures and monitor logs drive the simulated path, with the capture host's clock detrended out. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- ✅ PTP models: a linuxptp-style PI servo and the `linreg` servo, sync/delay-request rates, and chains of N boundary clocks scored against the time-error budgets. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))

### 2.17: Research bench v2, part 2 (simulators, algorithms, UI) (completes [#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- ✅ OMNeT++/INET and ns-3 interop: INET oscillator settings from a noise fit, vector files in and out, ns-3 text. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- ✅ More reference algorithms (Huygens-style convex hull, ntpd-rs-style combination) and a reproducible benchmark on a replayed trace. The SPTP-style client followed in 3.1, with exchange-level PTP in the bench. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- ✅ Web UI overhaul: workspaces, command palette, audit, time error, cornered hat, bench and PTP chains in the browser.

### 3.0: API final ✅
- ✅ The stable API (`ntpstats.api`) is final for the whole 3.x series; the 3.0 changelog lists every change since 2.15, generated from the frozen surface (`docs/api_changes.py`). Nothing was deprecated, so nothing is removed: code written for 2.15 or later runs unchanged. ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32))
- ✅ Production/stable package metadata, a supported-versions policy, and a JOSS paper draft (`paper/`). ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))
- ✅ Citable releases on Zenodo, concept DOI [10.5281/zenodo.23070521](https://doi.org/10.5281/zenodo.23070521), with the interop dataset; ORCID in `CITATION.cff`. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))
- ✅ [GitHub Discussions](https://github.com/thiagodefreitas/NetworkTime/discussions) for questions, results and ideas. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))
- ✅ Published on conda-forge: recipe in `packaging/conda-forge/`, built and tested in CI, accepted through [staged-recipes#35041](https://github.com/conda-forge/staged-recipes/pull/35041) and maintained in [conda-forge/ntpstats-feedstock](https://github.com/conda-forge/ntpstats-feedstock); `conda install -c conda-forge ntpstats`. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))

### 3.1: PTP exchanges and NTP over PTP ✅
- ✅ PTP exchanges in the bench: Sync and Delay_Req at their own rates, transparent clocks, `ptp-lan`/`ptp-tc` presets, and ptp4l-style and SPTP-style client models scored like every other estimator. ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29))
- ✅ NTP over PTP (RFC 10030, chrony 4.9) in captures, with the transparent-clock corrections applied as the RFC specifies. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))

### 3.2: New daemons and protocols as sources ✅
- ✅ ntpd-rs as a live source (`ntpstats watch ntpd-rs`, `ntp-ctl` or the metrics exporter). ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- ✅ CSPTP (client-server PTP, ntpd-rs 2.0 / statime) in captures, with transparent-clock corrections. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- ✅ chrony 4.9: the parsers checked against the example lines of the 4.9 documentation; NTP over PTP since 3.1. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))

### 3.3: Quality release ✅
- ✅ UI, CLI and documentation checked end to end (every page with every example dataset on desktop, phone width and dark theme; every command on every example file) and the findings fixed; the checks run in CI.
- ✅ Gallery notebook on PTP through networks without PTP support; docs site descriptions for search; tools landscape updated. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))

### 3.4: GNSS timing receivers ✅
- ✅ u-blox UBX logs (NAV-CLOCK, NAV-TIMEUTC, TIM-TP) and PPS sawtooth correction with qErr (`ntpstats sawtooth`); the OCP Time Card's receiver is a u-blox, so its UBX output is covered. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- ✅ chrony's time-stamping sources (daemon, kernel, hardware) per measurement.
- ✅ Gallery notebook on the PPS sawtooth. ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))

### 3.5: GNSS/PPS on Linux and in the lab ✅
- ✅ gpsd PPS/TOFF, recorded and live, with qErr for the sawtooth correction. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- ✅ TAPR TICC output, all modes.

### 3.6: The 2012 thesis, finished ([#40](https://github.com/thiagodefreitas/NetworkTime/issues/40)) ✅
The undergraduate thesis in which ntpstats began ([UFCG, 2012](https://dspace.sti.ufcg.edu.br/handle/riufcg/18226))
is assessed, with its experiments re-run against truth and on the original 2012 data, in
[research/thesis-2012](research/thesis-2012/). What it left open:
- ✅ ntpd's clock discipline (reference implementation and RFC 5905 appendix constants) as a model in
  the bench, with the thesis's step and ramp experiments run against truth;
- ✅ Levine's NIST algorithms as reference estimators (LOCKCLOCK, J. Res. NIST 2020; the Kalman
  variant, PTTI 2011);
- ✅ a poll-interval advisor, `ntpstats poll` (the thesis's first objective).

### 3.7: Real logs against an independent reference (completes [#28](https://github.com/thiagodefreitas/NetworkTime/issues/28))
Everything so far is validated on test vectors, simulations and Stable32 output. What is still
missing is a long record of a real client checked against a reference it does not use.
- A validation protocol, documented and scripted: a host disciplined over the Internet (chrony or
  ntpd, logs on), a local PPS or GNSS receiver as the independent reference, and `ntpstats compare`
  on the two series: alignment on a common time base, residuals, coverage of the reported
  confidence intervals and of the audit error bound, OADEV/TDEV of the difference. Runs for weeks,
  not hours. The protocol is written so that anyone with a Raspberry Pi and a GNSS module can
  repeat it and send the result in.
- First campaign on the maintainer's own hardware, published as a dataset next to the interop
  dataset, with a notebook in the gallery and a results section in the preprint (v2).
- The weekly live interop dataset grows; `ntpstats interop` gains a trend view over runs
  (per-server offset and delay over weeks, servers that drift or disappear).
- Poll advisor (`ntpstats poll`) checked on those real logs: does the recommended interval meet
  the target error on the reference? The ntpd model gains the popcorn spike suppressor and the
  500 ppm slew limit, the two documented gaps in `ntpstats.disciplines`.
- Stable32 cross-check extended to the remaining statistics its batch mode can write (TOTDEV,
  Theo1, MTIE) and TimeLab `.tim` round trips once a sample file arrives
  ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33)).

### 3.8: Operators: fleets, alerts and instruments
The operator audience has the exporter and dashboard; the next layer is many hosts and the
instruments people already own.
- Fleet view: many logs or exporters at once, one table ranking hosts by offset, jitter, bound
  and mask verdict, in the CLI and the web UI; the Prometheus exporter emits alert rules for the
  same thresholds ([#36](https://github.com/thiagodefreitas/NetworkTime/issues/36)).
- Remaining sources of [#21](https://github.com/thiagodefreitas/NetworkTime/issues/21): OCP Time
  Card sysfs and `phc2sys` logs, Meta `fbclock` and AWS ClockBound as live samplers (the bound
  formats are already read), `pmc` watch for several ports.
- Instrument exports ([#35](https://github.com/thiagodefreitas/NetworkTime/issues/35)): a
  column-mapping wizard in the UI and CLI (`--columns`) that turns any CSV or TSV into a series,
  saved as a profile; built-in profiles for Calnex, VIAVI, Keysight and Microchip as sample
  files arrive. Sample files are the blocker, not code.

### 3.9: Research bench, part 3: closed loops
3.6 put clock disciplines in the bench with a fixed poll interval. The next step is the full
loop as the daemons run it.
- Poll-interval adaptation: ntpd's poll adjust (RFC 5905 section 13, `poll_update()`) and chrony's
  `minpoll`/`maxpoll` with its own criterion, so a scenario reports the intervals the daemon
  would have chosen as well as the error.
- A chrony discipline model from its documented algorithm (regression over the last samples,
  with its outlier and skew handling), next to ntpd, LOCKCLOCK and the PTP servos; the bench
  then covers every discipline in common use.
- Closed-loop scenarios: the discipline's corrections feed back into the simulated local clock,
  so transients (steps, frequency jumps, route changes) are measured as the user sees them, not
  on an open-loop record.
- Preprint v2 with the real-data campaign of 3.7 and the closed-loop results, and the RFC 5905
  erratum (appendix A.5.5.6 `PLL`/`AVG` constants) filed and tracked.

### 4.0: only when forced
The 3.x API is final and nothing is scheduled to break it. A 4.0 happens only for a floor
change (dropping Python 3.9 and numpy 1.x once the supported-versions policy allows), and it
will carry no other removals. Until then every feature ships in a 3.x minor release.

### Continuous: community and citability
conda-forge bumps on each release (bot pull requests on the feedstock), the preprint on
ResearchGate and Zenodo, JOSS submission about April 2027 (the paper follows the current JOSS
structure; development must span the required period and evidence of use be gathered),
contributor on-ramp, distribution packages (Debian, Fedora, Homebrew),
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
| 2.13 | Open interop dataset ([#30](https://github.com/thiagodefreitas/NetworkTime/issues/30)); OpenTelemetry export ([#36](https://github.com/thiagodefreitas/NetworkTime/issues/36)); EDF cross-check ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28)); Roughtime draft-08 |
| 2.14 | In-browser edition ([#31](https://github.com/thiagodefreitas/NetworkTime/issues/31)); plugins ([#37](https://github.com/thiagodefreitas/NetworkTime/issues/37)); pandas/xarray/Parquet ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32)) |
| 2.15 | Stable API and deprecation policy, streaming reader for large logs, notebooks in CI and the NIST SP 1065 gallery entry ([#32](https://github.com/thiagodefreitas/NetworkTime/issues/32), [#38](https://github.com/thiagodefreitas/NetworkTime/issues/38)) |
| 2.16 | Delay traces and trace replay in the bench; PTP servos and boundary-clock chains against TE budgets ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29), part 1) |
| 2.17 | OMNeT++/INET and ns-3 interop; Huygens-style and ntpd-rs-style estimators; reproducible trace benchmark; web UI overhaul ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29)) |
| 3.0 | Stable API final for 3.x (no breaking changes), production/stable metadata and support policy, JOSS paper draft, documentation refresh |
| 3.1 | PTP exchanges, transparent clocks and ptp4l/SPTP-style clients in the bench ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29)); NTP over PTP (RFC 10030) in captures ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21)) |
| 3.2 | ntpd-rs live source, CSPTP in captures, chrony 4.9 documentation checks ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21)) |
| 3.3 | Quality release: UI at phone width and with degenerate data, clean CLI errors, dTE_H at slow sampling, gallery notebook, docs for search ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38)) |
| 3.4 | u-blox UBX receiver logs and PPS sawtooth correction ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21)); chrony time-stamping sources; sawtooth notebook ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38)) |
| 3.5 | gpsd PPS/TOFF (recorded and live), TAPR TICC ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21)) |
| 3.6.1 | Exact χ² quantile for confidence intervals; Stable32 cross-check with its output files in the test suite ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28)) |
| 3.6 | Clock disciplines in the bench (ntpd, RFC 5905 appendix, Levine's LOCKCLOCK and Kalman variant); `ntpstats poll`; the 2012 thesis revisited ([#40](https://github.com/thiagodefreitas/NetworkTime/issues/40)) |
