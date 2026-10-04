# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/):

- **MAJOR**: incompatible changes to the Python API, CLI options or file formats written;
- **MINOR**: new statistics, formats, commands or UI features (backwards compatible);
- **PATCH**: bug fixes and documentation.

Releases are made from `vX.Y.Z` tags (see CONTRIBUTING.md). The *Release* workflow checks the
tag against the package version, tests, publishes a GitHub Release with the notes below and
uploads to PyPI.

## [Unreleased]

### Changed
- The χ² quantile behind every confidence interval is now exact (regularized incomplete gamma with
  Newton refinement, numpy and the standard library only) instead of the Wilson–Hilferty
  approximation, which was off by 0.2 % at 5 degrees of freedom and by about half at 2 for the
  2.5 % tail. Intervals with EDF above 20 are unchanged to four digits.

### Validation
- **Stable32 cross-check** ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28)): Stable32
  1.62 run in batch mode under Wine on four phase files for OADEV, MDEV, TDEV and HDEV; its
  `SIGMA.TAU` files are in `tests/data/stable32/` and `tests/test_stable32.py` checks that point
  estimates and analysis-point counts agree on every row and intervals wherever the EDF does. The
  two documented differences (Greenhall's averaged-phase EDF at small τ for FM noise; Stable32's
  B1-ratio noise identification below about 30 averaged points) are described in
  [Validation](https://thiagodefreitas.github.io/NetworkTime/validation/#stable32-cross-check).

## [3.6.0] - 2026-10-04

The 2012 thesis, finished ([#40](https://github.com/thiagodefreitas/NetworkTime/issues/40)). No breaking changes.

### Added
- **Clock disciplines in the bench** (`ntpstats.disciplines`), steered in closed loop like the PTP
  servos: `ntpd` (ntpd 4.2.8's clock filter, state machine and hybrid PLL/FLL, from
  `ntp_loopfilter.c`), `ntpd-rfc` (the same with the RFC 5905 appendix's constants), `lockclock`
  (J. Levine's NIST frequency-lock loop, J. Res. NIST 2020) and `levine-kalman` (with Levine's scalar
  Kalman time estimate, PTTI 2011). The appendix's PLL gain of 65536 gives a phase time constant of
  about 48 days at poll 6; implementations follow ntpd's 16 ([Trace replay & PTP](https://thiagodefreitas.github.io/NetworkTime/research-bench/)).
- **`ntpstats poll`** and `poll_advice()`: the predicted error just before the next poll for each
  candidate interval (the log decimated to it, then the holdover model), and the longest interval
  that meets `--target` (exit code 3 if none) ([Metrology](https://thiagodefreitas.github.io/NetworkTime/metrology/#poll-interval)).
- `research/thesis-2012`: the 2012 thesis assessed and its experiments re-run, now with the ntpd
  model's step and ramp responses and the poll-interval advice for the 2012 clock.

### Stable API changes since 3.5.0
- Added: `ntpd_discipline`, `lockclock`, `poll_advice`, `PollAdvice`. Nothing removed or changed.

## [3.5.0] - 2026-10-03

GNSS/PPS timing on Linux hosts and in the lab. No breaking changes.

### Added
- **gpsd** (format `gpsd`, `gpspipe -w` logs): PPS and TOFF series per device, GNSS time minus the
  system clock's time stamp, with `precision` and the receiver's `qErr` (gpsd_json(5)).
  `ntpstats watch gpsd` samples a running gpsd (`host:port`), also from the web UI's *Live*
  workspace. `ntpstats sawtooth` uses the `qErr` of a gpsd PPS log when no UBX log is given. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- **TAPR TICC** (format `ticc`): Timestamp, Period, 3-Corner-Hat and Time Interval output; per-channel
  phase against the nominal period, `chA - chB` of paired events, `WRAP` seconds unwrapped, seconds and
  fractions kept apart so picoseconds survive (format from the TICC firmware and manual).

### Stable API changes since 3.4.0
- None. Code written against the stable API of an earlier release keeps working.

## [3.4.0] - 2026-10-03

GNSS timing receivers and time-stamping sources. No breaking changes.

### Added
- **u-blox UBX receiver logs** (format `ubx`, detected automatically, also mixed with NMEA and in the
  web UI): `UBX-NAV-CLOCK` becomes a receiver-clock series (bias as reported, with drift, time and
  frequency accuracy), `UBX-NAV-TIMEUTC` time-stamps it, and `UBX-TIM-TP` gives the time-pulse
  quantization error `qErr`. Layouts from the u-blox interface description. ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21))
- **`ntpstats sawtooth`** and `ntpstats.ubx.apply_qerr`: remove the PPS quantization sawtooth from a
  time-interval-counter measurement with the receiver's `qErr`. The sign with which `qErr` applies
  (not stated by u-blox) is chosen from the data and reported, or given with `--sign`; TDEV before
  and after is printed.
- **chrony time-stamping sources**: `measurements.log` series carry `interleaved`, `tx_timestamp` and
  `rx_timestamp` (daemon, kernel or hardware) and a summary in `meta["timestamping"]`, also shown on
  the web UI's network page.
- Gallery notebook *Removing the GNSS PPS sawtooth with u-blox qErr*, with a synthetic receiver log
  and counter log (`examples/data/ubx-timing.ubx`, `pps-tic.csv`). ([#38](https://github.com/thiagodefreitas/NetworkTime/issues/38))

### Changed
- Times below a femtosecond are printed as 0 (they are numerical noise).

### Stable API changes since 3.3.0
- None. Code written against the stable API of an earlier release keeps working.

## [3.3.0] - 2026-10-03

A quality release: the web UI, the command line and the documentation were checked end to end
(every page with every example dataset, on desktop, at phone width and in the dark theme; every
command on every example file), and what that found is fixed. No breaking changes.

### Added
- Gallery notebook *PTP through networks without PTP support*: ptp4l-style and SPTP-style clients,
  delay filters and a Huygens-style estimator on the same PTP exchanges with ground truth, how much
  transparent-clock coverage is enough, a narrower servo, and RFC 10030 corrections on a capture.
- Command palette: choose the input format for the next files (type "format"), and simulate the PTP
  presets.
- Docs site: a description for every main page and a clearer site description, so that searches
  for NTP/PTP stability, time-error or capture analysis can find it; the tools landscape lists
  ntpxyz, chrony_ntp_logconv, PTP-DAL and timeTools.

### Changed
- Command line: a missing file, unreadable input or impossible request prints one line
  (`ntpstats: error: …`) and exits with status 2 instead of a Python traceback;
  `NTPSTATS_DEBUG=1` shows the traceback.
- Time error: when the sampling is too slow for the filter bandwidth, dTE_H is reported as not
  available (it was numerical noise), and a limit on it is reported as not checked.
- Web UI: the reference picker lists datasets that overlap the active one first and marks the
  others; the network page explains when a dataset has no round-trip delay instead of failing a
  request.

### Fixed
- Web UI: log-scale charts hung (and raised a script error) on deviations that are zero to
  numerical precision, e.g. a noise-free ramp; such values are now gaps, with a note.
- Web UI at phone width: the header, page tabs, comparison table, events table, reference
  picker, chart legends and the audit rules no longer push the page sideways; the dTE_H card no
  longer shows a raw number.
- Web UI: charts of a page left mid-render no longer stay marked as loading.
- Loading a directory skips broken links and other non-regular files.
- Stability slopes no longer warn on a zero deviation.

### Stable API changes since 3.2.0
- None. Code written against the stable API of an earlier release keeps working.

## [3.2.0] - 2026-10-03

New daemons and protocols as sources ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21)). No breaking changes.

### Added
- **ntpd-rs as a live source**: `ntpstats watch ntpd-rs` samples `ntp-ctl -f prometheus status`,
  or the metrics exporter's URL (`--command-override http://127.0.0.1:9975/metrics`). Each sample
  is the inverse-variance mean of the per-source offsets ntpd-rs 1.x exports, with the number of
  sources, the best source's uncertainty and delay, and the system root delay, dispersion and
  stratum. The 2.0 pre-releases no longer export per-source offsets; `watch` says so. Also in the
  web UI's *Live* workspace.
- **CSPTP in captures**: client-server PTP (sdoId 0x300, as in ntpd-rs 2.0 and statime) is read
  from pcap/pcapng files as one series per client/server pair. Every exchange gives all four
  timestamps; transparent-clock corrections are removed in both directions; the PTP-timescale
  offset is inferred; the CSPTP status TLV gives the grandmaster and steps removed. These messages
  are no longer mistaken for master/slave flows.
- `ntpstats.sources.parse_prometheus_text`, a reader for the Prometheus/OpenMetrics text format.
- Tests built from the example lines of the chrony 4.9 documentation (`measurements`, `tracking`,
  `statistics`): columns and signs match the parsers.

### Changed
- Docs: the `prom` page notes that ntpd-rs offset metrics are those of the 1.x series.

### Stable API changes since 3.1.0
- None. Code written against the stable API of an earlier release keeps working.

## [3.1.0] - 2026-10-03

PTP exchanges in the research bench, and NTP over PTP in captures. No breaking changes.

### Added
- **PTP exchanges in the bench** (completes [#29](https://github.com/thiagodefreitas/NetworkTime/issues/29)):
  a scenario with `protocol = "ptp"` simulates the E2E delay mechanism, with a Sync every `poll`
  seconds and a Delay_Req every `delay_interval` seconds, each with its own one-way delay and
  timestamp noise. `transparent` is the fraction of queueing delay that transparent clocks correct.
  The series carries the one-way `ms`/`sm` measurements and the slave's offset, so every estimator
  runs on it. New presets `ptp-lan` (switches without PTP support) and `ptp-tc` (transparent
  clocks), also on the *Simulate* page of the web UI.
- Two PTP client models as estimators: `ptp4l` (moving-median path delay, the linuxptp PI servo or
  linreg, in closed loop) and `sptp` (SPTP-style: complete exchanges, path-delay outlier discard,
  PI servo). `ntpstats simulate --preset ptp-lan --benchmark` scores them with the others.
- **NTP over PTP** (RFC 10030, chrony 4.9): NTP messages in the NTP TLV of PTP event messages are
  read from pcap/pcapng files as NTP exchanges. The transparent-clock corrections (PTP correction
  field of the response, Network Correction extension field for the request) are applied as the
  RFC specifies, and refused when it forbids them. Uncorrected values and both corrections are
  kept as columns. Example: `examples/data/ntp-over-ptp.pcap`.

### Fixed
- `ntpstats trace` on captures shorter than about one detrend window (15 minutes by default):
  the clock's offset is now removed with at least four windows when there are enough exchanges,
  so its drift no longer appears as delay variation.
- Web UI overview: the *Events* card listed "none detected" under a non-zero count.
- `ntpstats simulate --benchmark` on PTP presets does not score the first 300 s, while the servos
  lock.

### Stable API changes since 3.0.0
- **Changed**: `PathModel`: new method `floor`; `Scenario`: new optional fields `protocol`,
  `delay_interval`, `transparent`.
- **Removed**: nothing. Code written against the stable API of an earlier release keeps working.

## [3.0.0] - 2026-10-02

The stable API is final. **No breaking changes**: code written for 2.15 or later runs unchanged.

### Changed
- `ntpstats.api` is final for the whole 3.x series. Stable names are only added or deprecated
  within 3.x, and a deprecated name keeps working, with a warning, until the next major
  release. The command line and the files ntpstats writes follow the same rule
  (*Stable API* docs page, CONTRIBUTING).
- Package metadata: "Production/Stable", supported Python versions (3.9 to 3.13), typed, and
  links to the documentation and changelog. Security fixes go to the latest 3.x minor release
  (SECURITY.md).

### Stable API changes since 2.15.0
Generated with `python docs/api_changes.py v2.15.0`.

- **Added**: `ChainResult` (class, from `ntpstats.ptpsim`); `ChainScenario` (class, from `ntpstats.ptpsim`); `DelayTrace` (class, from `ntpstats.trace`); `LinRegServo` (class, from `ntpstats.ptpsim`); `Link` (class, from `ntpstats.ptpsim`); `PIServo` (class, from `ntpstats.ptpsim`); `TracePath` (class, from `ntpstats.trace`); `inet_oscillator` (function, from `ntpstats.simio`); `load_trace` (function, from `ntpstats.trace`); `read_omnetpp_vec` (function, from `ntpstats.simio`); `simulate_chain` (function, from `ntpstats.ptpsim`); `trace_from_series` (function, from `ntpstats.trace`); `write_omnetpp_vec` (function, from `ntpstats.simio`).
- **Changed**: `Scenario`: new init `trace=`; new fields `trace`; `ServerSpec`: new init `trace=`; new fields `trace`.
- **Removed**: nothing. Code written against the stable API of an earlier release keeps working.

### Added
- `docs/api_changes.py`: lists the stable-API changes between a tag and the working tree, from
  the frozen surface, for release notes.
- A draft software paper for the Journal of Open Source Software (`paper/`), and a workflow that
  builds its PDF (#38).

### Documentation
- New docs home page organised by task; the README introduction, the tools landscape, the
  roadmap ("After 3.0") and the wiki describe the toolkit as it is now.

## [2.17.0] - 2026-10-02

Research bench v2, part 2: completes #29.

### Added
- **Reference algorithms**:
  - `hull`: Huygens-style. The max-margin line through the offset bounds θm ± δ/2 of a sliding
    window, causal.
  - `kalman-combine`: multi-server, ntpd-rs-style. Per-source Kalman filters, interval
    intersection, inverse-variance mean.

  With symmetric floors `hull` is the most accurate single-server estimator on the presets.
  `kalman-combine` rejects falsetickers and stepping servers.
- **A reproducible benchmark on a replayed trace**: `examples/scenarios/replay-chrony.toml` scores
  every estimator on the delays of a real log under a simulated clock
  (`docs/examples/trace-benchmark.html`). CI runs it.
- **Stable API**: delay traces, PTP chains and the simulator formats join `ntpstats.api`
  (`load_trace`, `TracePath`, `ChainScenario`, `simulate_chain`, `read_omnetpp_vec`,
  `inet_oscillator` and the rest).
- **Web UI overhaul**, still plain JavaScript with uPlot, no build step, offline.
  - Five workspaces: *Analyze*, *Compare* (side by side, against a reference, N-cornered hat),
    *Comply* (time error with TE/TEL and MTIE/TDEV charts; UTC audit with a verdict and an evidence
    report), *Lab* (simulator, estimator bench, PTP boundary-clock chains) and *Live*.
  - A command palette (Ctrl K), keyboard shortcuts, a link for every page (`#/comply/audit`), and
    dataset sparklines, filter and rename.
  - Expandable charts, one-way delays on the Network page, and stale answers are never drawn.
  - New API endpoints: `audit`, `trace`, `compare`, `hat`, `estimators`, `bench`, `chain`, and the
    `audit.html` export.
  - A Playwright test drives every page in CI.
- **Simulator interop** (#29): OMNeT++ `.vec` result files are read like logs (INET clock
  `timeChanged` vectors become time error against simulation time; other vectors on request) and
  written (`convert --to omnetpp-vec`). ns-3 `time value` text is written with `convert --to ns3`.
  `ntpstats noise --inet` writes INET `RandomDriftOscillator` settings that reproduce the fitted
  random-walk FM, and lists what INET's oscillator cannot represent.

## [2.16.0] - 2026-10-02

Research bench v2, part 1 (#29). The new modules are provisional (not yet in `ntpstats.api`) until
2.17 adds the simulator exchange formats.

### Added
- **Delay traces** (`ntpstats.trace`, `ntpstats trace`): per-direction one-way delays extracted
  from any two-way exchanges.
  - Inputs: NTP and PTP captures, chrony `measurements.log`, ntpd `peerstats`/`rawstats`, and
    simulator output.
  - The clock offset between the two ends is removed (`--detrend floor|linear|none`).
  - The asymmetry is an explicit assumption (`--asymmetry`), since two-way timestamps cannot
    measure it.
  - `ntpstats trace` reports floors, PDV percentiles, loss and the correlation of the two
    directions; `--csv` exports the trace.
- **Trace replay in the bench**: `ntpstats bench trace:FILE`, or a `[trace]` table in a scenario
  file.
  - Modes: `replay` plays the trace in order; `bootstrap` draws random blocks, keeping the
    short-term correlation and both directions together.
  - `scale` multiplies the queueing.
  - Checked by a round trip: delays extracted from a simulated network and replayed give the
    same estimator scores as the model they came from.
- **PTP servos and boundary-clock chains** (`ntpstats.ptpsim`, `ntpstats chain`): a grandmaster
  and N boundary clocks, simulated with ground truth.
  - Each node has its own oscillator, the E2E delay mechanism with a moving-median filter, and
    linuxptp's PI servo (with its default gains) or an adaptive linear-regression servo.
  - Links have asymmetry, timestamp noise, and modelled or replayed PDV.
  - Time-error metrics are given per node and per hop: max|TE|, |cTE|, dTE_L MTIE, dTE_H.
  - Each hop is checked against the commonly quoted G.8273.2 T-BC class limits (A/B/C) or your
    own limits, and the end of the chain against a budget (default 1.1 µs); exit code 3 on
    failure.
  - `--kp`/`--ki` tune the servo. The warm-up follows the servo's lock time, and the command
    warns when a run is too short to lock.
- New notebook: a PTP chain against a time-error budget. With linuxptp's default gains, dynamic
  time error grows much faster than the number of hops (gain peaking): about 50 ns at 10 hops,
  about 600 ns at 20. A narrower loop keeps 20 hops near 25 ns. The bench notebook now also
  replays a real log.

### Fixed
- Noise identification no longer divides by zero on perfectly alternating or noise-free data (lag-1
  autocorrelation of −1, the white-PM limit).
- Commands piped into `head` and similar tools stop quietly instead of printing a
  `BrokenPipeError` traceback.

## [2.15.0] - 2026-10-01

### Added
- **Stable API** (#32): `from ntpstats import api as nt` gives the public surface in one namespace
  (loading, stability, analysis, metrology, time error and assurance, estimators, simulator,
  bench, reports, plugin types).
  - Covered by a deprecation policy: one full minor release of `NtpstatsDeprecationWarning`
    before a stable name or parameter changes. The warning is a `FutureWarning`, so it is shown
    in scripts and notebooks.
  - Helpers for contributors in `ntpstats.deprecation`: `deprecated`, `renamed_parameter`,
    `moved`.
  - The surface is frozen in `tests/data/api_surface.json`; CI fails on incompatible changes.
  - Documented on the new *Stable API* page; the policy is in CONTRIBUTING.
- **Large files** (#32, continues #13): `load_large` and `iter_chunks` read line-oriented logs in
  blocks, gzip included, and give the same series as `load`.
  - In a 300 000-line test, peak memory was about 2.4 times lower and reading twice as fast.
  - `load` switches to block reading by itself for text logs above 256 MB.
  - Supported formats: ntpd/NTPsec stats, chrony logs, linuxptp, CSV and the 2012 log.
- **Notebooks and reproduction gallery** (#32, #38): four notebooks, executed in CI on every change:
  - a chrony log to stability with intervals and a noise model;
  - benchmarking your own estimator;
  - compliance evidence (PTP time error, a UTC bound, a mask, an HTML report);
  - a reproduction of the NIST SP 1065 test suites.

  A docs page explains how to contribute a gallery entry.

With these, #32 is complete. Its last step, a 3.0 changelog that lists every change to the stable
API, is part of the 3.0 release checklist (CONTRIBUTING). The research bench v2 (#29) is planned
for 2.16 and 2.17.

## [2.14.0] - 2026-10-01

### Added
- **In-browser edition** (#31): the web UI runs entirely in the browser on the docs site, with
  Pyodide (WebAssembly). Files never leave the machine. `docs/build_app.py` builds it from the
  package wheel; a CI job checks with Playwright and Chromium that the page gives the same numbers
  as the installed package. Live probes stay in the installed tool.
- **Plugins** (#37): other packages add parsers, estimators, event detectors, masks and import
  profiles through entry points (`ntpstats.parsers`, `.estimators`, `.detectors`, `.masks`,
  `.profiles`).
  - `ntpstats plugins` lists everything, with where it comes from and load errors.
  - A plugin that fails to load is reported and never breaks the tool.
  - Contract tests for plugin authors: `pytest --pyargs ntpstats.testing.plugin_contract`.
  - Worked example in `examples/plugins/ntpstats-toy-csv`, installed and checked in CI.
  - The built-in research formats are registered through the same API.
- **Dataframes and Parquet** (part of #32): `TimeSeries.to_pandas()` / `from_pandas()`,
  `StabilityResult.to_dataframe()`, `DynamicResult.to_xarray()`, and Parquet files that keep
  float64 precision and the metadata (`convert --to parquet`; Parquet input is auto-detected).
  Optional extra `ntpstats[data]`; the package ships a `py.typed` marker.

### Changed
- The web server's `/api` routing is a plain `dispatch()` function, shared by the HTTP server and
  the browser edition. The UI's format list comes from `/api/info`, so plugin formats appear.

## [2.13.0] - 2026-10-01

### Added
- **Open interop dataset** (#30): the first Live interop run of each month writes one JSON record per probe
  (NTP, interleaved, NTS, NTS pool, NTPv5, Roughtime) to `data/interop/YYYY/YYYY-MM-DD.jsonl`,
  committed with `[skip ci]`. The dataset ships with each release, so it is archived on Zenodo.
  - Schema: `data/interop/README.md`.
  - New `interop` input format: one series per test and server, with availability.
  - `ntpstats dataset`: summary per server.
  - A directory given to any command is read as the concatenation of its files.
- **OpenTelemetry export** (#36): `monitor`/`watch --otlp [URL]` push the metrics as OTLP/HTTP
  JSON, standard library only; the standard `OTEL_*` environment variables are honoured. The
  payload is checked against the official OpenTelemetry protobuf definitions.
- **Cross-validation** (#28): the exact EDF is compared with the SP 1065 table 5 approximations
  used by Stable32: within 3 % for white PM/FM, 7 % for flicker/random-walk FM, 16 % for flicker
  PM.

### Fixed
- Roughtime: the client also offers draft-08 (0x80000008), and falls back to Google-Roughtime
  (the pre-IETF protocol: unframed, 64-byte nonces, microseconds) when a server does not answer
  the IETF request. Cloudflare's server did not answer in the 2.11 live interop run; the protocol
  that answered is reported and recorded in the dataset.

## [2.12.0] - 2026-10-01

### Added
- **Power-law noise model** (#25): `ntpstats noise` and `ntpstats.noisefit` fit h₂…h₋₂ and,
  optionally, a linear drift to OADEV/MDEV/HDEV curves and the spectrum.
  - The expected estimator values are exact for the discrete Kasdin–Walter model.
  - Model selection uses BIC.
  - Intervals come from a parametric bootstrap. Monte Carlo coverage is ≥ 90 % per coefficient
    except at the edge of detection.
  - Corner τ values are reported. `--scenario` writes a simulator clock (`[clock.h_alpha]`), and
    `simulate --scenario` runs it.
  - The UI can overlay the fitted model on the Stability chart.
- **Spectra** (#25): `ntpstats spectrum` and `ntpstats.spectrum` compute S_x(f) and S_y(f) with
  Welch or sine multitaper, per gap-free stretch, log-binned with degrees of freedom. L(f) in
  dBc/Hz for a carrier. New Spectrum tab in the UI.
- **N-cornered hat** (#27): `ntpstats hat` and `ntpstats.hat` estimate each source's stability
  from pairwise differences: Groslambert covariance, three-cornered hat and N-cornered hat by
  least squares, with intervals. Negative variances are flagged. Sources are aligned from
  separate logs.
- **Holdover prediction** (#26): `ntpstats holdover` and `ntpstats.holdover` predict TIE(t)
  with an envelope and the time to violate limits. The 95 % envelope holds 95 % ± 3 % with a known
    noise model, and 94–100 % with a fitted one.
  - The variance is computed exactly for the fitted noise, including the error of the fitted
    frequency and drift.
  - The uncertainty of the noise model is mixed into the envelope.
  - `--backtest` checks calibration on the log itself; `--min-holdover` exits with code 3 when
    the limit is not held long enough.
  - Phase can also be integrated from a frequency column (chrony).
  - New Holdover tab in the UI.
- **Research data** (#34): new formats `cggtts` (V2E, line checksums), `rinex-clock` (IGS
  `.clk`), `circular-t` (BIPM, UTC − UTC(k)), `ripe-atlas` (NTP results) and `ntppool`
  (monitor logs). `ntpstats cv` computes GNSS common-view and all-in-view time transfer, and
  `research.group_summary` gives per-server or per-probe distributions. Gzipped inputs are read
  directly.
- **HTOT** (#33): Hadamard total deviation (`-k htot`), bias-corrected per noise type, matching
  the NIST SP 1065 tables within 0.3 %. `compat.allantools.htotdev` returns the raw value.
- Docs: [Metrology](docs/metrology.md) and [Research data](docs/research-data.md) pages;
  synthetic examples of every new format in `examples/data/`.

## [2.11.0] - 2026-09-30

### Added
- **Roughtime** (#24): `ntpstats roughtime` and `ntpstats.roughtime` (draft-ietf-ntp-roughtime-19).
  It verifies the delegation and response signatures, MINT/MAXT, and the Merkle proof. It chains
  nonces over two rounds, runs the causal-ordering check, and writes and verifies malfeasance
  reports. It gives an authenticated interval for the local clock's error (`--check-local`),
  bundles the ecosystem server list and reads the draft's server-list JSON. It is compatible with
  older-draft servers (nonce leaf, microsecond timestamps).
- **NTS pools** (#24): NTS-KE NTP Server Deny records (draft-ietf-ntp-nts-keyexchange-pool-01),
  `nts.pool_sessions()` and `ntpstats query --nts --pool N` give independent servers from one pool.
- **RFC 9769 interleaved mode** (#24): `ntpstats query --interleaved` and
  `sntp.query_interleaved()` use the server's precise transmit timestamp. Captures recognise
  interleaved exchanges, recompute them with the precise timestamp and add an `interleaved`
  column.
- Live interop: NTS pool, Roughtime (chained, with the causal check) and interleaved-mode
  sections. The NTPv5 client stays on draft-09, the current draft.
- Docs: a [Protocols](docs/protocols.md) page.

## [2.10.0] - 2026-09-30

### Added
- **UTC traceability audit** (#22): `ntpstats audit FILE --limit 100us`. It computes a per-sample
  bound (|offset| + path + upstream + reference), stating the rule applied to each term (log
  columns or user allowances). Windows (1 h) are judged pass/fail/insufficient; gaps count as
  unmonitored, never as compliant. Output is text, JSON or a self-contained HTML report with the
  tool version and SHA-256 hashes of the inputs, and the exit code is 3 on failure.
- **Change detection** (#23): `ntpstats events` and `ntpstats.events`. It finds phase steps and
  spikes (MAD against a rolling slope), frequency changes (binary segmentation, standardised
  CUSUM), delay-floor (route) changes with an asymmetry hint, and leap smears. Phase and frequency
  events are marked path changed/unchanged. The UI lists events under the Offset chart.
- **GitHub Action** (#36): `uses: thiagodefreitas/NetworkTime@v2.10.0` runs stability, time
  error, audit, bounds or events checks, writes a job summary and fails on exit code 3.
  Arguments go through the environment, never through the shell. CI exercises it on the
  examples.
- **pytest assertions** (#36): `ntpstats.testing` (`assert_max_te`, `assert_time_error_within`,
  `assert_stability_within`, `assert_audit_passes`, `assert_bounds_valid`, `assert_no_events`)
  and a `timing_log` fixture registered as a pytest plugin.
- "Audit, events & CI checks" docs page.

### Fixed
- `format_seconds(0)` printed "0 ps"; it now prints "0 s".

## [2.9.0] - 2026-09-30

### Added
- **Live PTP clients** (#21): `ntpstats watch ptp4l` polls linuxptp through `pmc`
  (CURRENT_DATA_SET, TIME_STATUS_NP), and `ntpstats watch ptpcheck` polls facebook/time
  `ptpcheck stats`. Both are negated into reference − local, offered in the UI's Live dialog,
  and served to Prometheus with `--metrics-port`.
- **Windows w32tm** (#21): `/stripchart /dataonly` text (with midnight rollover and the date
  taken from the header) and `/rdtsc` CSV with exact FILETIME timestamps, auto-detected.
- **Prometheus import** (#21, #36): `ntpstats prom URL QUERY` saves a range query (e.g. ntpd-rs
  `ntp_source_offset_seconds`, chrony_exporter) as JSON, and any command reads it.
- **Clock-error bound validation** (#21): `ntpstats bounds BOUNDS REFERENCE` classifies each
  ClockBound/fbclock/CSV window as inside, violated or indeterminate against a better reference
  (with its uncertainty), and reports the violation rate, worst excess and tightness. Exit code
  3 above `--max-violation-rate`. Windows are parsed as exact decimals.
- **Instrument import profiles** (#35): `-f profile:NAME|FILE.toml` describes column layouts
  (value/time columns, units, TE or offset sign, ISO/MJD/unix/elapsed time, skipped banner rows,
  extra columns). Built-ins: `te-csv`, `tic-ns`, `tic-s`, `iso-te-ns`.
- `--negate` on every command, for sources that log local − reference.
- Examples: `w32tm-stripchart.txt`, `clockbound.txt` with a reference (synthetic), and a
  "Sources, instruments & bounds" docs page.

## [2.8.0] - 2026-09-30

### Added
- **PTP from packet captures** (#19). IEEE 1588 v2/v2.1 over UDP (IPv4/IPv6, ports 319/320)
  and Ethernet (0x88F7, VLAN) is read from pcap/pcapng. It supports one- and two-step clocks,
  E2E (Delay_Req/Resp) and P2P (peer delay, one- and two-step), and correction fields. The
  TAI→UTC offset is taken from Announce or inferred. There is one series per master/slave flow
  (offset against the capture clock, path/link delay, one-way delays, corrections), and
  AUTHENTICATION TLVs (NTS4PTP) are flagged. `ntpstats.ptp.summary()` counts messages.
- **Time-error metrics** (#20): `ntpstats timeerror` and `ntpstats.timeerror`. They give
  max|TE|, cTE (record and per 1000 s window), TEL/max|TEL| (0.1 Hz first-order filter,
  restarted after gaps, settling excluded), dTE_L (peak-to-peak, MTIE, TDEV) and dTE_H
  peak-to-peak. User-supplied limits (`max_te, 30ns` …) and MTIE/TDEV masks for dTE_L are
  checked, with exit code 3 on failure. Time-interval counter input is handled with
  `--units ns --input-is-te`.
- Time-error cards in the web UI (Overview) and `ntpstats report --time-error`.
- `examples/data/ptp-capture.pcapng` (synthetic) and a "PTP captures & time error" docs page.

### Changed
- Capture timestamps are kept as **integer nanoseconds**; a float of POSIX seconds only
  resolves about 240 ns. NTP offsets from captures are now computed exactly as well.

### Fixed
- Personal email addresses removed from public files; the author is referenced by GitHub
  profile.

## [2.7.0] - 2026-09-30

### Added
- **Cross-validation against NIST SP 1065** (#28). The NBS Monograph 140 data (table 30) and
  the 1000-point test suite (table 31) are regenerated in the tests. ADEV, OADEV, MDEV, TDEV,
  HDEV, TOTDEV, MTOT and TTOT agree to the 7 printed digits.
- **TTOT** (time total deviation), and confidence intervals for MTOT/TTOT from the SP 1065
  table 8 EDF.
- **Stable32 data files** (#33): `read_stable32`/`write_stable32` in `ntpstats.interop`,
  `-f stable32-phase|stable32-freq`, and `ntpstats convert` (any supported log to a Stable32 file
  or CSV).
- **allantools-compatible API** (#33): `from ntpstats.compat import allantools as at` gives
  `adev`, `oadev`, `mdev`, `tdev`, `hdev` (non-overlapping), `ohdev`, `totdev`, `mtotdev`,
  `ttotdev`, `theo1`, `mtie` and `tierms` with allantools signatures.
- **Prometheus/OpenMetrics exporter** (#36): `ntpstats monitor|watch --metrics-port`. It serves
  offset, delay, an error bound (|offset| + delay/2 + root delay/2 + root dispersion), NTS
  status, rolling TDEV and stddev, and sample and error counters (errors by kind, e.g.
  `kod_rate`).
- **Grafana dashboard, Prometheus alert rules and a docker-compose stack** in `contrib/`, with a
  "Monitoring" docs page. Tests check that the dashboard and rules only use exported metrics.
- Docs: "Stable32, TimeLab, allantools" migration page and a tools landscape page.
- **Community on-ramp** (#38): Code of Conduct (Contributor Covenant 2.1), security policy,
  issue forms (bug, feature, sample-data contribution), a pull request template, and "ways to
  contribute" in CONTRIBUTING.
- Releases also publish a container image to `ghcr.io/thiagodefreitas/ntpstats`.

### Changed
- **MTOT is bias-corrected by default**, dividing by the factor for the noise type identified at
  each τ (white PM 0.94 … random-walk FM 0.69), as Stable32 and the SP 1065 tables do. This
  makes MTOT an unbiased estimate of MVAR. `--raw-mtot` / `bias_correction=False` give the raw
  eq. (27) value, which is what earlier versions reported.

## [2.6.0] - 2026-09-30

### Added
- `ntpstats stability --exact` and `compute(..., max_work=0)` / `series_stability(..., max_work=0)`
  to force the full MTOT/Theo definitions.

### Changed
- **MTOT, Theo1, TheoBR and TheoH are much faster** (#18). MTOT and Theo1 are vectorised
  across subsequences. TheoBR computes its bias ratio once per τ grid instead of once per τ.
  Above a work limit per τ (`stability.MAX_WORK`), subsequences are strided (stride ≤ m), and
  the TheoBR ratio averages 64 evenly spaced terms. What was sampled is reported in
  `meta["stride"]` and `meta["theobr_ratio_terms"]`, and the CLI prints a note. On 1M samples at
  octave τ each statistic takes 2–4 s instead of hours; on 4096 samples TheoBR went from 210 s
  to under 1 s. Below the limit, results match the literal definitions to 1e-12.

## [2.5.0] - 2026-09-29

### Added
- New stability statistics (#15, closes #2): **MTOT** (modified total deviation), **TheoBR**
  (bias-removed Theo1) and **TheoH** (hybrid ADEV/TheoBR), in the CLI, API and UI.
- **Documentation site** (MkDocs Material, `mkdocs build --strict` in CI) with getting started,
  CLI, formats, statistics, network and estimators, validation, and an API reference generated
  from docstrings (mkdocstrings). It is deployed to GitHub Pages from `master`.
- **GitHub wiki** generated from `docs/`, `CHANGELOG.md` and `ROADMAP.md` (`docs/sync_wiki.py`,
  *Wiki* workflow).
- **Type checking**: mypy in CI, and the package is now mypy-clean.
- Coverage XML report in CI.

### Changed
- **Releases are tag-driven** (`vX.Y.Z`), or created from *Run workflow* with a tag input. The
  tag must match `__version__` and have a CHANGELOG section. Wheels and sdists are checked with
  `twine` and published to **PyPI** through trusted publishing.
- `docs` extra: `mkdocs>=1.5,<2`, `mkdocs-material`, `mkdocstrings[python]`.

### Fixed
- Type errors found by mypy: optional defaults, NTS session key handling, and Optional values in
  report formatting.

## [2.4.0] - 2026-09-29

### Security
- Web UI: export file names are sanitised and RFC 6266-encoded, which prevents response-header
  injection through crafted upload names; non-ASCII names no longer truncate responses.
- Web UI: a negative `Content-Length` is rejected instead of blocking a worker thread.
- Web UI: `/api/mask` treats the body as mask text only and can no longer read files on the
  server.
- NTS: a Kiss-o'-Death (including NTSN) is honoured only when it echoes the request's Unique
  Identifier (RFC 8915 §5.7), so a spoofed packet cannot flush the keys.

### Fixed
- NTS: TLS failures during NTS-KE raise `NTSError`, which the CLI and monitor handle, instead of
  surfacing raw pyOpenSSL exceptions.
- Masks apply to one statistic, named in the header (`tau,tdev`, `tau,mtie`, …) or set with
  `--mask-kind` (default TDEV). They are no longer compared with estimators of other units.
- CSV export keeps full sub-second time resolution. It previously used `%.12g`, which kept
  only 2 decimals of POSIX time.
- CSV import with a header but no time column now requires `tau0` instead of using the offset
  as time.
- `ntpstats network` removes a linear trend before computing offset statistics, as the UI and
  report do (`--detrend`).
- Kalman noise fitting no longer fails on constant offsets (zero ADEV).
- Floor packet percentage no longer drops the last sample when the span is an exact multiple of
  the window.
- `ntpstats simulate` no longer mutates the shared presets.
- `--tau0` is honoured as the stability grid for multi-column files.
- `ntpstats report --ci 0` no longer crashes.
- Live monitor: a late sample from a stopped monitor can no longer land in a newer live dataset.
- `ui --host 0.0.0.0` accepts remote Host headers (it is an explicit opt-in). IPv6 bind
  addresses work.

### Performance
- Stability confidence intervals: the EDF uses FFT convolution, so 1M-sample
  OADEV/MDEV/HDEV/TDEV with CIs takes about 1.2 s (previously 28–121 s).
- Parsers use numpy's C tokenizer, with a tolerant per-line fallback: ~1 s per million loopstats
  lines, ~2.4 s peerstats and ~3 s chrony (previously ~9–10 s). Closes #13.

### Added
- `ntpstats compare ESTIMATE REFERENCE`: error statistics plus TDEV/MTIE of one source against
  a reference (e.g. NTP client vs PPS/GNSS).
- CI: ruff lint and coverage reporting; `Dockerfile` for the UI/CLI/monitor.
- Tests for every fix above (166 tests).

## [2.3.0] - 2026-09-29

### Added
- **Research bench**: pluggable estimator API (`ntpstats.estimators`, entry-point group
  `ntpstats.estimators`) and `ntpstats bench`. It runs scenarios × seeds × estimators against
  ground truth and reports RMS, bias, p95, max, MTIE(1 h) of the error and runtime, with a
  30 min warm-up excluded by default. Output is a table, CSV, JSON or a self-contained HTML
  report (#9).
- **Scenario files** in TOML/JSON (`scenario_from_dict`) and two examples in
  `examples/scenarios/` (#9).
- **Reference estimators**: chrony-style weighted regression with a runs-test window,
  RADclock-style feed-forward, RFC 5905 clock filter + selection (intersection), cluster and
  combine for multiple servers with causal frequency propagation, and a median combiner
  (#10).
- **Simulator**: flicker FM/PM, temperature-driven frequency (tempco), path events (route
  change, congestion, outage), multi-server scenarios with falsetickers and stepping servers
  (`simulate_multi`), and new presets `route-change` and `falseticker` (#11).
- **Self-contained HTML reports**: `ntpstats report FILES -o report.html` and a *Report* button
  in the UI. Offset, stability with CI bands and a noise table, network wedge, input SHA-256
  hashes and parameters are embedded, and the file works offline (#12).
- **Live interop** workflow: weekly/on-demand queries of public NTPv4 and NTS servers plus the
  NTPv5 probe from GitHub runners, with a first snapshot in `docs/INTEROP.md` (all five NTS
  servers tested authenticated successfully).
- `examples/04_custom_estimator.py`: plugging your own algorithm into the bench.

### Changed
- GitHub Actions updated to `actions/checkout@v5` and `actions/setup-python@v6` (Node 24).

## [2.2.0] - 2026-09-29

### Fixed
- **chrony `measurements.log` offsets had the wrong sign** in 2.0.0–2.1.0. chrony.conf(5)
  documents θ as "positive indicates that the local clock is slow of the remote source" (the ntpd
  convention), but the parser negated it. Example data and the cross-format test repeated the
  same assumption; they are corrected, and a regression test is now pinned to the documentation
  line.

### Added
- **PTP**: linuxptp `ptp4l`/`phc2sys`/`ts2phc` parser, covering per-sample and summary lines,
  stdout/syslog/journald, monotonic→UTC mapping, and path delay feeding the network metrics
  (#5).
- **chrony `refclocks.log`** parser (GNSS/PPS reference clocks).
- **Live local daemons**: `ntpstats watch chrony|ntpd` (`chronyc -c tracking`, `ntpq -c rv`),
  also available as a UI Live source (#6).
- **pcap/pcapng** import with stdlib-only dissection (Ethernet/VLAN, Linux cooked, raw IP,
  IPv4/IPv6). Requests and responses are matched by origin timestamp or v5 client cookie, and
  offsets are measured from the capture clock (#7).
- **NTS client** (RFC 8915) behind the optional extra `ntpstats[nts]`: NTS-KE over TLS 1.3 with
  ALPN, host-name verification, AES-SIV-CMAC-256 and cookie renewal. `query --nts`,
  `monitor --nts` (#8).
- **Experimental NTPv5 client** (draft-ietf-ntp-ntpv5-09, wire format cross-checked with
  ntpd-rs): `query --ntpv5`, `--probe-v5` upgrade negotiation, `monitor --ntpv5`, UI protocol
  selector (#8).
- Example logs: linuxptp, chrony refclocks and a pcap capture.

## [2.1.0] - 2026-09-29

### Added
- **Exact EDF** for ADEV/OADEV/MDEV/TDEV/HDEV confidence intervals (`ntpstats.edf`): computed
  from the estimator filter convolved with the discrete power-law noise model, verified by
  Monte Carlo for every noise type (#1).
- New statistics: **TOTDEV** (with NIST EDF), **Theo1** (τ up to 0.75 × record) and
  **TIErms** (#2).
- **Dynamic stability** (sliding-window ADEV/MDEV/…): `ntpstats dynamic`, `stability.dynamic()`
  and a heat-map in the UI (#3).
- **Limit masks** from user CSV (`tau,limit`, log-log interpolation): `ntpstats stability
  --mask FILE` (exit code 3 on failure, upper confidence bound used), per-τ margin in the UI
  and a PASS/FAIL chip (#4).
- UI: estimator chips are populated from the server; mask loading; dynamic view toggle.

### Changed
- Confidence intervals now use the exact discrete EDF. The Greenhall–Riley continuous-time
  approximation over-estimated the EDF by up to ~20 % at small averaging factors for
  instantaneously sampled phase data. `stability.edf_approx` is kept as a deprecated alias.

## [2.0.0] - 2026-09-29

First release of the rewrite. The 2012 Google Summer of Code prototype is kept unchanged in
`legacy/`.

### Added
- Parsers for ntpd/NTPsec `loopstats`, `peerstats`, `rawstats`; chrony `tracking.log`,
  `measurements.log`, `statistics.log`; CSV; 2012 `estimators.log`. Auto-detection and sign
  normalisation (server − local).
- Stability statistics: ADEV, OADEV, MDEV, TDEV, HDEV, MTIE with χ² confidence intervals,
  lag-1 ACF noise identification and gap-aware resampling.
- Network metrics: delay floor, offset/delay wedge, asymmetry indicator, floor packet percentage,
  min-delay clock filter.
- Kalman filter (delay-weighted, gated, irregular sampling) and RTS smoother.
- Simulator with ground truth and `ntpstats simulate --benchmark`.
- SNTP client (random transmit timestamp, origin check, KoD, 2036 era) and `ntpstats monitor`.
- Local web UI (`ntpstats ui`), CLI, optional matplotlib report figures.
- Test suite, CI, examples, documentation, MIT license.

### Fixed (relative to the 2012 prototype)
- Allan deviation τ₀ was hard-coded to 32 s (≈33× error on loopstats data); irregular sampling
  and gaps were ignored. See `docs/STATE_OF_THE_ART.md`.

[Unreleased]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/thiagodefreitas/NetworkTime/releases/tag/v2.0.0
