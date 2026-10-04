# Stable32 reference outputs

`*.tau` files are `SIGMA.TAU` stability files written by **Stable32 1.62** (W. J. Riley; the free
IEEE UFFC distribution, `162Stable32.exe` from <https://github.com/IEEE-UFFC/stable32>) on the
phase files next to them, with τ₀ = 1 s and Stable32's default 68 % confidence intervals.
`tests/test_stable32.py` compares them with ntpstats on the same inputs.

| File | Origin |
|---|---|
| `TST_SUIT.DAT` | the 1000-point NIST SP 1065 test suite as shipped with Stable32, loaded here as phase data (white PM) |
| `PHASE.DAT` | the 1001-point sample phase file shipped with Stable32 (white FM) |
| `SIMA.DAT` | `ntpstats.noisefit.simulate({0: 1e-22, -2: 1e-28}, 4096, 1.0, seed=11)`: white and random-walk FM |
| `SIMB.DAT` | `ntpstats.noisefit.simulate({2: 1e-24, -1: 1e-23}, 4096, 1.0, seed=12)`: white PM and flicker FM |

Suffixes: `_a` overlapping Allan, `_m` modified Allan, `_t` time, `_h` Hadamard deviation.
Columns: τ, number of analysis points, σ, interval minimum, interval maximum, equivalent degrees
of freedom. Stable32 prints four significant digits.

## How they were produced

Stable32 is a 32-bit Windows program with a batch mode (`-X` commands, version 1.59 and later).
It runs headless under Wine (`wine32`, Wine 9.0) in a virtual display; the installer unpacks with
`innoextract` without being run. In `STABLE32.INI` set `ShowWelcome=0` and `ShowFileOpened=0`,
then for each file and variance:

```bash
export WINEARCH=win32 WINEPREFIX=$PWD/prefix WINEDEBUG=-all
xvfb-run -a sh -c 'wine Stable32.exe -p PHASE.DAT -t 1 -o skip -xra &
                   until [ -s SIGMA.TAU ]; do sleep 2; done; wineserver -k'
mv SIGMA.TAU PHASE_a.tau       # -xra, -xrm, -xrt, -xrh
```

Stable32 is © W. J. Riley / IEEE UFFC-S and is not redistributed here; only its output on these
inputs is, together with the inputs. `TST_SUIT.DAT` and `PHASE.DAT` are the data files it ships
with (the former is the published NIST SP 1065 test suite).
