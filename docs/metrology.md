# Metrology: noise model, spectra, N-cornered hat, holdover

## Power-law noise model

Most clocks are described by five coefficients of the fractional-frequency spectrum,
`S_y(f) = Σ h_α f^α`:

| α | noise | ADEV slope |
|---|---|---|
| 2 | white PM | τ⁻¹ |
| 1 | flicker PM | ≈ τ⁻¹ |
| 0 | white FM | τ^-½ |
| −1 | flicker FM | τ⁰ |
| −2 | random-walk FM | τ^½ |

The five coefficients feed the simulator, Kalman filters and holdover prediction.

```bash
ntpstats noise gnssdo.csv                       # h_α with 95 % bootstrap intervals, corner τ
ntpstats noise gnssdo.csv --drift --kinds oadev,mdev --scenario clock.toml
ntpstats simulate --scenario clock.toml         # a statistically equivalent synthetic clock
```

How it works:
- **Model.** The expected ADEV, MDEV, TDEV and HDEV are computed exactly from the discrete
  Kasdin–Walter model, the same filter algebra as the [EDF](statistics.md#confidence-intervals). For
  large m they reduce to the textbook formulas (h₀/2τ, 2 ln2 h₋₁, 2π²τh₋₂/3, …). White and
  flicker PM need no bandwidth assumption.
- **Fit.** Weighted non-negative least squares on the variances, with weights from the EDF. Every
  subset of noise types is tried, and the one with the lowest BIC is kept, so a type is reported
  only when the data need it. `--drift` also fits a linear frequency drift (D²τ²/2 in AVAR), which
  would otherwise be mistaken for random-walk FM. `--spectrum` adds the frequency spectrum to the
  fit.
- **Intervals.** Parametric bootstrap (`--bootstrap`, default 100). The fitted model is
  re-simulated and refitted, and a basic interval is taken on a log scale. It is never narrower
  than the analytic interval, with the analytic error scaled by the spread the bootstrap shows.
  Points of a stability curve are correlated, so purely analytic errors are 2–4× too small. Types
  that were not detected get an upper limit.

**Validation (Monte Carlo, 95 % intervals, 30 runs each, 4096 samples).** The first three
columns are the share of runs in which the interval contained the true h_α.

| Mixture | white PM | flicker PM | white FM | flicker FM | RW FM |
|---|---|---|---|---|---|
| white PM + white FM | 97 % | | 100 % | | |
| flicker PM + white FM + RW FM | | 97 % | 97 % | | 87 % * |
| white FM + flicker FM | | | 93 % | 93 % | |

\* Random-walk FM with its corner near the longest averaging time. A type at the edge of detection
is the hard case. It will not be reported in most runs, and its upper limit is then what matters.

The web UI's *noise model* switch (Stability tab) overlays the fitted curves and lists the
coefficients.

## Spectra

`ntpstats spectrum FILE` gives the one-sided PSD of the frequency (`--kind y`, default) or the
phase (`--kind x`). Options:
- Welch (Hann window, 50 % overlap) or sine multitaper;
- computed per gap-free stretch and log-binned, with degrees of freedom;
- `--carrier 10e6` converts the phase spectrum to single-sideband phase noise L(f) in dBc/Hz
  (IEEE 1139).

The UI's *Spectrum* tab shows the spectrum with the fitted power-law model.

## Individual stability from differences: the N-cornered hat

With three or more sources and no better reference, only differences are observable. A client
monitoring three NTP servers sees server − client for each, and the client's own noise cancels in
the differences.

```bash
ntpstats monitor a.example b.example c.example -o mon.csv   # or three separate logs
ntpstats hat a.csv b.csv c.csv                              # Groslambert covariance (default)
ntpstats hat mon.csv --all-peers --method nch               # N-cornered hat by least squares
```

- **Groslambert covariance** (default): for three sources the estimate equals the classic
  three-cornered hat, as Vernotte, Calosso & Rubiola showed (IFCS 2016). Its uncertainty model
  keeps its coverage when one source dominates.
- **Negative variances.** They occur when one source is much quieter than the others, or when
  sources share correlated noise (for example two servers behind the same upstream). They are
  shown as `*` with an upper limit instead of being hidden.

Validated on simulated sources with known noise: 95 % intervals contain the truth in ≥ 94 % of
cases.

## Holdover prediction

*If GNSS or the upstream network disappears now, how long does this clock stay within 1.1 µs?*

```bash
ntpstats holdover gnssdo.csv --limit 1.1us --limit 100us --horizon 1d
ntpstats holdover /var/log/chrony/tracking.log --source frequency --model drift --limit 1ms
ntpstats holdover gnssdo.csv --limit 1.1us --backtest 20        # calibration on the log itself
ntpstats holdover gnssdo.csv --limit 1.1us --min-holdover 4h    # exit code 3 if not met (CI, acceptance)
```

**Input.** The phase of the oscillator against a reference, for example from a TIC or a GNSSDO
compared with a better reference. With `--source frequency`, the frequency corrections a daemon
logs are integrated to phase instead.

**Model.**
- At the loss the clock runs on the frequency fitted over `--window`, or on frequency and drift
  (`--model drift`).
- The time-interval error is then a linear function of the phase samples. For the fitted
  power-law noise its variance is computed exactly, including the error of the fitted frequency
  and drift.
- The envelope mixes the variances of the bootstrap noise models, so the uncertainty of the model
  itself is included. Noise types the data could not detect are included up to their upper limit.
- A fitted drift shifts the mean TIE of a frequency-only holdover.

**Calibration (acceptance test).** With a known noise model, the 95 % envelope contains the real
TIE 95 % ± 3 % of the time over 120 simulated clocks. With a noise model fitted from 20,000 s of
data and a 20,000 s horizon (50 clocks per case):
- 94 % for white + random-walk FM;
- 99–100 % for white PM + white FM with drift, and for white + flicker FM.

It errs towards caution when long-term noise cannot be ruled out from the data. Predictions far
beyond the longest averaging time the data support are flagged. Temperature-driven wander is not
modelled yet.

The UI's *Holdover* tab shows the envelope, the limits and the time to each.

## Hadamard total deviation

`-k htot` is the Hadamard total deviation (NIST SP 1065 §5.2.14). Like HDEV it ignores linear
frequency drift, and like the total deviations it gives tighter intervals at long τ. It is
bias-corrected per noise type, as Stable32 does; the published values match the SP 1065 tables
within 0.3 %. `ntpstats.compat.allantools.htotdev` returns the raw value.
