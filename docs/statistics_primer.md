# Statistics Primer

This page introduces the time series and stability statistics computed by ntpstats.

- **ADEV** (Allan Deviation)
- **MDEV** (Modified Allan Deviation)
- **TDEV** (Time Deviation)
- **HDEV** (Hadamard Deviation)
- **MTIE** (Maximum Time Interval Error)

ntpstats correctly computes these deviations with confidence intervals and proper lag-1 ACF noise identification, as well as handling gaps in unevenly sampled datasets.
