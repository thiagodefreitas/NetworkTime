# Trace replay and PTP chains

The [research bench](network.md#research-bench) scores synchronisation algorithms against a
simulated clock whose true offset is known. 2.16 adds two things to it ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29)):

- **real networks**: the delays of a capture or a log, replayed under the simulated clock;
- **PTP chains**: a grandmaster and N boundary clocks with servo models, checked against a
  time-error budget.

Both are *provisional* in 2.16 (not yet part of the [stable API](api/stable.md)), as 2.17 will add
the OMNeT++/INET and ns-3 exchange formats.

## Delay traces

```bash
ntpstats trace capture.pcap                      # per-direction floors, percentiles and PDV
ntpstats trace /var/log/chrony/measurements.log --peer 192.0.2.10 --csv office.csv
ntpstats bench trace:office.csv internet --seeds 1-5   # replay next to a modelled network
```

Any two-way exchange gives the offset θm (reference − local) and the round trip δ, so the raw
one-way delays are δ/2 + θm (to the reference) and δ/2 − θm (from it). They still contain the true
offset between the two clocks, which wanders, so it is removed first (`--detrend`):

| `--detrend` | assumption |
|---|---|
| `floor` (default) | in each window (default 16 exchanges or 900 s), the exchange with the smallest round trip is symmetric; the offset is interpolated between windows |
| `linear` | a constant frequency offset between the ends (one Theil–Sen line) |
| `none` | the two ends were already synchronised (for example a PTP- or GNSS-disciplined capture host) |

The absolute asymmetry of a path cannot be measured with two-way timestamps. The trace assumes
equal floors unless `--asymmetry` gives a known difference; the queueing (PDV), loss and the
correlation between directions are kept as measured. The extraction is checked on synthetic
paths with known delays (median error below 20 µs against 1–2 ms of queueing), and a delay trace
extracted from a simulated network and replayed gives the same estimator scores as the model it
came from (`tests/test_trace.py`).

Inputs: NTP and PTP captures, chrony `measurements.log`, ntpd `peerstats` and `rawstats`, simulator
output, and the trace CSV written by `--csv` (`unix_time,offset,delay,to_ref,from_ref`).

In a scenario file:

```toml
name = "office-uplink"
poll = 64
duration = 172800
[clock]
freq_offset = 8e-6
[trace]
file = "office.csv"      # or a capture/log; relative to this file
mode = "bootstrap"       # "replay" plays it in order (looping); "bootstrap" draws random blocks
block = 3600             # bootstrap block length, s (default 64 exchanges)
scale = 1.0              # multiply the queueing part: 2.0 = "twice as loaded"
detrend = "floor"
asymmetry = 0.0
```

`replay` is the faithful choice for one run; `bootstrap` gives every seed a different but
statistically similar network (moving-block bootstrap: short-term correlation and both directions
stay together). Servers in multi-server scenarios can each have their own `trace`.

```python
from ntpstats.trace import TracePath, load_trace
from ntpstats.simulate import Scenario, simulate_ntp

trace = load_trace("capture.pcap")
print(trace.stats())
meas, truth = simulate_ntp(Scenario(poll=trace.interval, duration=trace.duration,
                                    trace=TracePath(trace, mode="replay")))
```

## PTP boundary-clock chains

```bash
ntpstats chain --hops 10 --class B                     # G.8275.1-like: 16 Sync/s, HW stamps, PI servo
ntpstats chain --hops 20 --asymmetry-spread 10ns --budget 1.1us
ntpstats chain --hops 5 --servo linreg --pdv 2us       # links through switches without PTP support
ntpstats chain --hops 3 --trace ptp-capture.pcapng     # replay captured delays on every link
```

Each boundary clock has its own oscillator (frequency offset drawn within ±2 ppm, white and
random-walk FM, powered up 1 ms off) and runs the E2E delay mechanism with a moving-median delay
filter of 10 (linuxptp's default) and one of two servos:

| servo | model |
|---|---|
| `pi` (default) | linuxptp's PI servo: frequency estimate and step on the second sample, then `kp·offset + Σ ki·offset`, with linuxptp's hardware-time-stamping gains `kp = min(0.7·Ts^-0.3, 0.7/Ts)`, `ki = min(0.3·Ts^0.4, 0.3/Ts)` |
| `linreg` | adaptive-window linear regression (after linuxptp's linreg): a line through the recent free-running phase predicts the next sync; window 4–64 samples, chosen by smallest prediction variance |

Links have a delay, an asymmetry (master→slave minus slave→master), timestamp noise (default 4 ns
rms per timestamp) and optional PDV, modelled or replayed from a trace.

The output is the time error of every node relative to the grandmaster, with the
[time-error metrics](ptp.md) after a warm-up: max|TE|, |cTE|, the MTIE of dTE_L (0.1 Hz low-pass)
up to 1000 s and dTE_H peak-to-peak. It is given for the accumulated TE at each node and for the TE
each hop adds (node *i* − node *i*−1). Each hop is checked against per-hop limits, and the end of
the chain against a budget. Exit code 3 on failure, as for `timeerror`.

- `--class A|B|C`: T-BC noise-generation limits as commonly quoted from ITU-T G.8273.2,
  Table 7-1 (max|TE| 100/70/30 ns, |cTE| 50/20/10 ns, dTE_L MTIE 40/40/10 ns, dTE_H 70/70 ns for A/B).
  Check them against the edition you certify to, or pass your own with `--limits`.
- `--budget` (default 1.1 µs): the end-to-end max|TE|, the G.8271.1 network limit for 1.5 µs
  applications.

Checked behaviour (`tests/test_ptpsim.py`):
- a constant asymmetry *a* adds exactly *a*/2 of cTE per hop;
- both servos step, then track out a frequency offset to below 1 ns;
- noise accumulates along the chain;
- PDV between boundary clocks costs accuracy.

- with linuxptp's default gains, dynamic TE grows much faster than the number of hops (gain
  peaking), and a narrower loop avoids it (`test_gain_peaking_accumulates_and_a_narrow_loop_avoids_it`).

### Servo tuning for chains

linuxptp's default PI gains suit a single slave: at 16 Sync/s the loop bandwidth is a few tenths
of a hertz, with some gain peaking. Cascaded, the peaks multiply. In the default 1 h simulation, 10
hops end at about 50 ns of max|TE| but 20 hops at about 600 ns. A narrower, well-damped loop of
about 0.05 Hz keeps 20 hops near 25 ns once locked. This is the range the G.8273.2 T-BC
requirements set for clocks meant to be chained.

```bash
ntpstats chain --hops 20 --kp 0.3 --ki 3.5e-4 --duration 1h     # kp in 1/s, ki per sample
```

Narrow loops lock slowly. By default the warm-up excluded from the metrics follows the servo: an
estimate of the chain's settling time from the loop's slowest pole, at least 300 s and at most half
the run. The command says so when the run is too short to lock.

These are models: they show how servo, rates, asymmetry and noise interact along a chain. A
particular product's servo and filters differ.

A scenario file for `--scenario`:

```toml
[chain]
hops = 8
servo = "pi"
duration = 3600
sync_rate = 16
asymmetry_spread = 5e-9
[chain.link]
timestamp_noise = 4e-9
pdv = {queue_mean = 1e-6, load = 0.3}
[chain.oscillator]
white_fm_adev1 = 1e-11
rw_fm_adev1 = 1e-13
initial_offset = 1e-3
```

The [chain notebook](notebooks.md) walks through a budget study: how the error grows with the number
of hops, how to tune the servo for a chain, and what asymmetry and PDV cost.
