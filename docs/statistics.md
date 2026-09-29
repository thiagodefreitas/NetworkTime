# Statistics

All estimators take **phase data** (offsets, seconds) on a uniform grid. Irregular logs are
resampled at their median interval τ₀. Grid points inside gaps longer than `--max-gap`·τ₀ are
NaN, and every term touching them is dropped, so **gaps are never bridged**.

| Kind | Name | Use |
|---|---|---|
| `adev`, `oadev` | Allan deviation (non-/overlapping) | frequency stability; OADEV preferred |
| `mdev` | modified Allan deviation | separates white and flicker PM |
| `tdev` | time deviation, τ·MDEV/√3 | telecom/PTP time stability (ITU-T G.810) |
| `hdev` | overlapping Hadamard deviation | insensitive to linear frequency drift |
| `totdev`, `mtot` | total and modified total deviation | reflection-extended; tighter at long τ |
| `theo1`, `theobr`, `theoh` | Theo1, bias-removed TheoBR, hybrid TheoH | reach τ = 0.75 × record length |
| `mtie`, `tierms` | maximum and RMS time interval error | network time-error limits |

Each estimator is tested against a literal implementation of its published formula (NIST SP 1065)
and, where one exists, against analytic power-law results.

## Confidence intervals

Intervals are χ² intervals based on the **equivalent degrees of freedom (EDF)**. For
ADEV/OADEV/MDEV/TDEV/HDEV, ntpstats computes the EDF exactly for the discrete power-law noise
model, from the estimator filter convolved with the Kasdin noise filter. This avoids the
continuous-time approximation of Greenhall & Riley (2003), which overestimates the EDF by up to
~20 % at small averaging factors for sampled offsets. Monte Carlo tests check it for every
noise type. TOTDEV uses the NIST table for FM noise.

## Noise identification

The dominant power-law noise at each τ is identified with the lag-1 autocorrelation method of
Riley & Greenhall (2004): white PM (α = 2), flicker PM (1), white FM (0), flicker FM (−1) and
random-walk FM (−2). It selects the EDF model and is shown in every table.

## Masks

`--mask FILE` checks one statistic against a limit curve: a CSV of `tau,<kind>` (e.g.
`tau,tdev`), interpolated in log-log. It uses the upper confidence bound, prints the margin per
τ and exits with code 3 on failure. No standards text is bundled; bring your own limits.

## Dynamic stability

`ntpstats dynamic` (and the UI heat-map) computes a statistic over sliding windows, which
exposes route changes, load cycles and temperature effects that a single curve averages away.
