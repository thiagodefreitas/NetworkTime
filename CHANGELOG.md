# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/):

- **MAJOR**: incompatible changes to the Python API, CLI options or file formats written;
- **MINOR**: new statistics, formats, commands or UI features (backwards compatible);
- **PATCH**: bug fixes and documentation.

A release happens automatically when a new version reaches `master`: the *Release* workflow
tests the code, tags `vX.Y.Z` and publishes a GitHub Release with the notes below.

## [Unreleased]

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

[Unreleased]: https://github.com/thiagodefreitas/NetworkTime/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/thiagodefreitas/NetworkTime/releases/tag/v2.0.0
