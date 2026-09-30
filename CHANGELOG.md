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

## [2.13.0] - 2026-10-01

### Added
- **Open interop dataset** (#30): the weekly Live interop run appends one JSON record per probe
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
