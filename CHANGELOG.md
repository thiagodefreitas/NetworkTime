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
