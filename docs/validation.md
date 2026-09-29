# Validation

## What the test suite checks

Around 180 tests run in CI on Python 3.9, 3.11 and 3.13, together with ruff and mypy. None of
them need network access.

- **Estimators**: literal implementations of the NIST SP 1065 sums (ADEV, OADEV, MDEV, TDEV,
  HDEV, TOTDEV, MTOT, Theo1, MTIE, TIErms); analytic log-log slopes for the five power-law noise
  types; and a frozen table of values from an independent implementation (`allantools` 2024.06,
  stored in `tests/data`, not a dependency).
- **EDF and confidence intervals**: closed forms (white FM at m = 1: EDF = 2n/3), Monte Carlo
  EDF for every estimator and noise type, and CI coverage.
- **Noise identification**: every α from +2 to −2.
- **Parsers**: line layouts from the ntpd, chrony and linuxptp documentation and sources. The
  same simulated peer must read identically from peerstats, rawstats, chrony measurements and a
  pcap capture; this now guards the chrony sign convention corrected in 2.2.0.
- **Clients**: SNTP, NTPv5 and NTS against local test servers, including Kiss-o'-Death, spoofed
  replies, forged NTS responses, certificate mismatch, TAI timescale and the 2036 era rollover.
- **Web UI**: API, CSRF and Host-header checks, header injection, path traversal.

## Live interoperability

The [Live interop](INTEROP.md) workflow queries public NTPv4 and NTS servers every week from
GitHub-hosted runners.

## Not yet done

- Comparison with **Stable32** output on published datasets.
- Long-term real logs against an independent reference (for example a GNSS-disciplined host).

Both are tracked in the roadmap. Contributions of reference datasets are welcome.

## Validating your own setup

```bash
# chrony's view against its PPS reference clock: bias, RMS, TDEV and MTIE of the error
ntpstats compare /var/log/chrony/tracking.log /var/log/chrony/refclocks.log --ref-peer PPS0
```

To check a synchronisation algorithm rather than a deployment, simulate the scenario with
`ntpstats bench` and compare it with the reference estimators.
