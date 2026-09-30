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
| `totdev`, `mtot`, `ttot` | total, modified total and time total deviation | reflection-extended; tighter at long τ; MTOT/TTOT bias-corrected per noise type as in Stable32 (`--raw-mtot` to disable) |
| `htot` | Hadamard total deviation | drift-insensitive like HDEV, tighter at long τ; bias-corrected per noise type (SP 1065 tables within 0.3 %) |
| `theo1`, `theobr`, `theoh` | Theo1, bias-removed TheoBR, hybrid TheoH | reach τ = 0.75 × record length |
| `mtie`, `tierms` | maximum and RMS time interval error | network time-error limits |

Each estimator is tested against a literal implementation of its published formula (NIST SP 1065)
and, where one exists, against analytic power-law results.

## Long records: MTOT and the Theo family

MTOT and Theo1 cost O(N·m) per τ, and TheoBR's bias ratio averages about N/6 Theo1 values. They
are computed with vectorised block operations, and when one τ would exceed a work limit
(`stability.MAX_WORK` element operations) ntpstats averages every *k*-th subsequence, with *k*
never larger than *m*. Adjacent subsequences share all but one sample, so this changes the
estimate by well under 1 % in the tests. The TheoBR ratio uses 64 evenly spaced terms instead
of all of them. A million-sample log takes a few seconds per statistic.

What was sampled is reported in the result: `meta["stride"]` per τ (1 = every subsequence) and
`meta["theobr_ratio_terms"]` (used, total). `compute(..., max_work=0)` or `ntpstats stability
--exact` always computes the full definitions.

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

## Noise model, spectra, hat and holdover

Fitting the power-law coefficients h_α, spectra, the N-cornered hat and holdover prediction are
described in [Metrology](metrology.md).
