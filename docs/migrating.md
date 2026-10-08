# Stable32, TimeLab and allantools

ntpstats is meant to sit next to the tools time-and-frequency people already use. This page
shows how to move data and code between them, and what to expect when you compare results.

## Stable32

Stable32 reads plain ASCII columns: values, optionally with an MJD timetag first, plus
header or comment lines, which it skips. ntpstats reads and writes the same layout.

```bash
# any supported log (chrony, ntpd, linuxptp, pcap, CSV...) -> Stable32 phase file with MJD timetags
ntpstats convert /var/log/chrony/tracking.log -o tracking.dat
# fractional-frequency file instead, values only
ntpstats convert tracking.log -o tracking-freq.dat --to stable32-freq --no-timetags

# and back: analyse a Stable32 data file
ntpstats stability data.dat -f stable32-phase -k oadev,mdev,mtot
ntpstats stability freq.dat -f stable32-freq --tau0 1 -k oadev,hdev,ttot
```

```python
from ntpstats.interop import read_stable32, write_stable32

s = read_stable32("freq.dat", data_type="freq", tau0=1.0)   # integrated to phase
write_stable32(s, "phase.dat", data_type="phase")
```

Conventions:
- Phase is in seconds, and frequency is fractional (dimensionless).
- Zero frequency values are gaps, as in Stable32.
- A phase gap is written as a missing timetag.

**Comparing numbers.** ADEV, OADEV, MDEV, TDEV, HDEV, TOTDEV, MTOT and TTOT reproduce the
NIST SP 1065 test suites (which come from Stable32) to 7 digits; see [Validation](validation.md).
TOTDEV, MTOT, TTOT and HTOT include the noise-type bias corrections of SP 1065. Stable32 1.62
applies them to TOTDEV and HTOT but writes MTOT and TTOT raw in its `SIGMA.TAU` files; use
`--raw-totals` (CLI) or `bias_correction=False` (API) to compare with those. Stable32's Théo1
run writes the bias-removed TheoBR, which ntpstats computes as `theobr`. Confidence intervals can
differ: for ADEV-family statistics ntpstats computes the EDF exactly for the discrete noise
model, where Stable32 uses published approximations.

## TimeLab

TimeLab's native `.tim` format is not publicly documented, so ntpstats does not read it yet. To
move data into TimeLab, export plain phase or frequency columns
(`ntpstats convert ... --no-timetags`). If you can share a small `.tim` file, please attach it to
[issue #33](https://github.com/thiagodefreitas/NetworkTime/issues/33).

## allantools

`ntpstats.compat.allantools` has the allantools call signatures, so existing scripts switch with
one import:

```python
# import allantools as at
from ntpstats.compat import allantools as at

taus, devs, errs, ns = at.oadev(y, rate=1.0, data_type="freq", taus="octave")
taus, devs, errs, ns = at.mdev(x, rate=10.0, taus=[0.1, 1, 10])
```

Available functions:
- `adev`, `oadev`, `mdev`, `tdev`;
- `hdev` (non-overlapping) and `ohdev`;
- `totdev`, `mtotdev`, `ttotdev`;
- `theo1`, `mtie`, `tierms`;
- `frequency2phase` and `phase2frequency`.

The values match allantools to 1e-9 on the frozen comparison table in the tests. There are
three differences:
- `totdev`, `mtotdev`, `ttotdev` and `htotdev` stay raw, as in allantools, while
  `stability.compute` bias-corrects them.
- `theo1` returns the effective τ = 0.75·m/rate.

For confidence intervals, noise identification and gap handling, use the native API:

```python
from ntpstats import stability

r = stability.compute(x, tau0=1.0, kind="oadev", taus="octave", ci=0.683)
r.taus, r.dev, r.lo, r.hi, r.edf, r.alpha
```
