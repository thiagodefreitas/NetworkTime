# Validation

## What the test suite checks

Around 340 tests run in CI on Python 3.9, 3.11 and 3.13, together with ruff and mypy. None of
them need network access.

- **Estimators**: literal implementations of the NIST SP 1065 sums (ADEV, OADEV, MDEV, TDEV,
  HDEV, TOTDEV, MTOT, Theo1, MTIE, TIErms); analytic log-log slopes for the five power-law noise
  types; and a frozen table of values from an independent implementation (`allantools` 2024.06,
  stored in `tests/data`, not a dependency).
- **Published reference values (NIST SP 1065)**: the NBS Monograph 140 nine-point data (table 30)
  and the 1000-point test suite (table 31) are regenerated in `tests/test_reference_nist.py`. The
  values agree to the 7 printed digits:

  | Statistic | NBS 9-point (m = 1, 2) | 1000-point (m = 1, 10, 100) |
  |---|---|---|
  | ADEV, OADEV, MDEV, TDEV | ✓ | ✓ |
  | HDEV (overlapping) | ✓ | ✓ |
  | TOTDEV | ✓ | ✓ |
  | MTOT, TTOT (bias-corrected) | ✓ | ✓ |
  | HTOT (bias-corrected) | within 0.3 % | within 0.3 % |

  The published MTOT values include Stable32's noise-type bias correction (white FM: variance
  ÷ 0.73). ntpstats applies the same correction by default; `bias_correction=False` or
  `--raw-totals` gives the raw SP 1065 eq. (27) value. On simulated noise, the raw MTOT/MVAR ratio
  measured here is 0.99, 0.85, 0.77, 0.72 and 0.68 for white PM to random-walk FM, which matches
  the factors used (0.94, 0.83, 0.73, 0.70, 0.69).
- **EDF and confidence intervals**: closed forms (white FM at m = 1: EDF = 2n/3), Monte Carlo
  EDF for every estimator and noise type, and CI coverage. The exact discrete EDF is also
  compared with the approximate OADEV formulas of SP 1065 table 5 (Stable32's simple method):

  | Noise | agreement (N = 1025, m = 1…64) |
  |---|---|
  | white PM, white FM | within 3 % |
  | flicker FM, random-walk FM | within 7 % |
  | flicker PM | within 16 % (SP 1065 notes this approximation is the roughest) |
- **Noise model, hat and holdover**: Monte Carlo coverage of the h_α intervals, the N-cornered
  hat and the holdover envelope ([Metrology](metrology.md)).
- **Noise identification**: every α from +2 to −2.
- **Parsers**: line layouts from the ntpd, chrony and linuxptp documentation and sources. The
  same simulated peer must read identically from peerstats, rawstats, chrony measurements and a
  pcap capture; this now guards the chrony sign convention corrected in 2.2.0.
- **Clients**: SNTP, NTPv5 and NTS against local test servers, including Kiss-o'-Death, spoofed
  replies, forged NTS responses, certificate mismatch, TAI timescale and the 2036 era rollover.
- **Web UI**: API, CSRF and Host-header checks, header injection, path traversal.

## Stable32 cross-check

Stable32 1.62 (the free IEEE UFFC distribution) was run in its batch mode under Wine on four phase
files (the NIST 1000-point suite and the sample file it ships with, and two simulated power-law
mixtures), for OADEV, MDEV, TDEV and HDEV with its default 68 % intervals. Its `SIGMA.TAU` outputs
are in `tests/data/stable32/` and `tests/test_stable32.py` compares them with ntpstats on the same
inputs (16 runs, 160 rows):

| What | Result |
|---|---|
| point estimates | agree to Stable32's four printed digits on every row (worst 3.1×10⁻⁴); the number of analysis points is identical |
| confidence intervals | agree to four digits wherever the two programs use the same EDF |
| EDF at small τ for FM noise | differ: white FM, OADEV, m = 1: Stable32 782, ntpstats 666. Stable32 uses Greenhall's algorithm for phase averaged over each sample interval, ntpstats the exact value for instantaneous samples ([statistics](statistics.md#confidence-intervals)); the difference shrinks with m and is gone by m = 64 |
| noise identification at long τ | differ when fewer than about 30 averaged points remain: Stable32 switches to its B1 ratio method and on these records reports white FM where the data say white PM or random-walk FM. Its EDF is then ntpstats' EDF for that other noise type, to the printed digits: the same formula, a different identification |

Stable32's batch command offers only those four statistics. Its Auto1 automation script, run the
same way, computes the others; 28 more runs give TOTDEV, MTOT, TTOT, HTOT, Théo1, TIE rms and MTIE
on the same four files (`tests/test_stable32.py`, 77 tests in all):

| Statistic | Result |
|---|---|
| TIE rms, MTIE | agree to the printed digits on every row |
| TOTDEV, HTOT | Stable32 bias-corrects both for the noise type it identifies (TOTDEV by SP 1065 eq. (52), 1 − a·τ/T). Where the two programs identify the same noise type, they agree to the printed digits; on the rows where they do not (fewer than about 30 averaged points), Stable32's value is ntpstats' raw sum with the bias factor of another noise type |
| MTOT, TTOT | Stable32 1.62 writes them raw, without the SP 1065 table 11 factor its manual describes; ntpstats with `bias_correction=False` agrees to the printed digits |
| Théo1 | the Théo1 run writes the bias-removed TheoBR, not Théo1. ntpstats' `theobr` agrees to the printed digits on the 1000-point files; on the 4096-point ones the bias-removal ratio differs by 0.1–0.2 % while the Théo1 sums it scales agree at every τ |

Two changes in ntpstats came out of it. TOTDEV was not bias-corrected for flicker and random-walk
FM although SP 1065 section 5.11 says the correction "should be used to correct all reported
TOTVAR results"; it now is (a deviation larger by up to 11 % at τ = T/4 for random-walk FM), and the raw
value is `bias_correction=False`. And the TheoBR ratio, which averaged 64 of its terms to save
time, is exact for records up to about 1550 points; the subset had moved it by 0.2 % on 1000
points.

The cross-check also found that ntpstats' χ² quantile, a Wilson–Hilferty approximation until 3.6.0,
was off by 0.2 % at 5 degrees of freedom and by half at 2 degrees of freedom for the 2.5 % tail (the
95 % upper bound of the last point of a stability curve). It is exact now (within 10⁻¹⁰ of scipy's).

## Live interoperability

The [Live interop](INTEROP.md) workflow queries public NTPv4, NTS, NTS-pool, NTPv5 and Roughtime
servers every week from GitHub-hosted runners, and records one run per month in the open dataset
[`data/interop/`](https://github.com/thiagodefreitas/NetworkTime/tree/master/data/interop).

## Not yet done

- Long-term real logs against an independent reference. The protocol and the analysis are ready
  ([validation campaign](validation-campaign.md), `ntpstats validate`); the first campaign on real
  hardware is the next step.

Contributions of reference datasets and Stable32 outputs are welcome.

## Validating your own setup

```bash
# a chrony host against a noselect PPS refclock: clock error, chrony's bound, servers, estimators
ntpstats validate /var/log/chrony/refclocks.log --tracking /var/log/chrony/tracking.log \
    --measurements /var/log/chrony/measurements.log --warmup 1h
# chrony's own offset estimate against the PPS: bias, RMS, TDEV and MTIE of the difference
ntpstats compare /var/log/chrony/tracking.log /var/log/chrony/refclocks.log --ref-peer PPS0
```

The [validation campaign](validation-campaign.md) page describes the hardware, the chrony
configuration and how to read and share the result.

To check a synchronisation algorithm rather than a deployment, simulate the scenario with
`ntpstats bench` and compare it with the reference estimators.
