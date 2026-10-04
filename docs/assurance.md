---
description: "UTC traceability audit, clock-error bound validation and CI checks (GitHub Action, pytest helpers) for time synchronisation in regulated and telecom environments (MiFID II, DORA, G.8271.1)."
---

# Assurance: audit, events and CI checks

## UTC traceability audit

Regulated users need to show how far their clocks *could* have been from UTC, not just the
offset a daemon reported. Examples are MiFID II RTS 25 (100 µs or 1 ms, traceable to UTC) and
DORA and NIS2, which rely on trustworthy timestamps. `ntpstats audit` computes a per-sample
**error bound**:

```text
bound = |offset| + path + upstream + reference
```

| Term | Taken from | Otherwise |
|---|---|---|
| path (asymmetry) | half the round-trip `delay` column (worst case: all delay in one direction) | `--asymmetry`, else 0 (declared) |
| upstream | `root_delay/2 + root_dispersion` (chrony, the ntpstats monitor); ntpd peer `dispersion` | `--upstream`, else 0 (declared) |
| reference | `--reference-uncertainty` (top of the chain, e.g. GNSS receiver or UTC(k)) | 0 (declared) |

Details:
- **Windows**: time is cut into windows (`--window 1h`).
- **Coverage**: each sample covers the time up to the next one, at most `--max-gap` median
  intervals. Anything beyond that is **unmonitored** and never counts as compliant.
- **Window verdict**: a window fails if any bound exceeds `--limit`, and is *insufficient* below
  `--min-coverage` (90 %).
- **Exit code** is 3 when any window fails or overall coverage is too low.

```bash
ntpstats audit /var/log/chrony/tracking.log --limit 100us --reference-uncertainty 100ns \
    --events --html audit-2026-09.html
ntpstats audit monitor.csv --limit 1ms --json > audit.json
```

The HTML and JSON reports state every assumption applied. They list the largest bounds, the
windows and the detected events, and carry the tool version and **SHA-256 hashes of the
inputs**, so the report can be archived and reproduced. The report describes measurements;
interpreting a regulation is up to its reader.

## Events: steps, spikes, frequency and route changes

`ntpstats events` locates the non-stationary parts of a log, so they can be explained or cut out
before computing ADEV:

| Event | Detector |
|---|---|
| `phase_step`, `spike` | sample-to-sample changes against a rolling slope, MAD-scaled (`--step-k 8`); a step stays, a spike returns |
| `frequency_change` | binary segmentation of the local frequency with a standardised CUSUM (`--freq-threshold 5`, `--min-freq-change-ppm 0.1`) |
| `delay_floor_change` | per-block minimum delay (`--floor-block 16`); reports the offset shift at the same time. About half the delay change means the new route is asymmetric in one direction |
| `leap_smear` | opposite frequency changes of about 11.6 ppm, 20–28 h apart (a smeared leap second upstream) |

When the log has delays, phase steps and frequency changes are also marked **path changed** or
**path unchanged**. An offset change *without* a path change points at the reference or the local
clock (a daemon step, an upstream GNSS problem, spoofing), not the network.

The detectors are tested against known ground truth, including a simulated route change, and
report no events on stationary noise. The web UI lists them on *Analyze → Events*; click one to zoom the offset chart to it. *Comply → Audit* runs the audit with a verdict and downloads the evidence report.

## Timing checks in CI

### GitHub Action

This repository is also a GitHub Action. It installs ntpstats, runs a check and writes a summary
table to the job page. The job fails when the check fails (exit code 3).

```yaml
- uses: thiagodefreitas/NetworkTime@v3.6.1
  with:
    command: timeerror                 # stability | timeerror | audit | bounds | events
    args: captures/bc-test.pcapng --limits limits/class-c.csv --mask limits/dte-l-mtie.csv
```

Inputs:
- `version` pins the PyPI release (default: latest).
- `install: "."` installs from the checkout.
- The `result` output is `pass` or `fail`.

Arguments are passed through the environment and word-split without shell evaluation.

### pytest

```python
from ntpstats.testing import (assert_audit_passes, assert_bounds_valid, assert_max_te,
                              assert_no_events, assert_stability_within, assert_time_error_within)

def test_grandmaster_time_error():
    assert_max_te("results/gm.pcapng", 100e-9)
    assert_time_error_within("results/gm.pcapng", {"cte": 20e-9, "dte_h_pp": 50e-9},
                             masks=["masks/dte-l-mtie.csv"])

def test_daemon_upgrade_keeps_stability(timing_log):      # fixture from the ntpstats pytest plugin
    s = timing_log("results/tracking.log")
    assert_stability_within(s, "masks/tdev.csv")
    assert_no_events(s)
```

Each helper accepts a path in any supported format, or a `TimeSeries`. On failure it raises an
`AssertionError` that names the failing values.
