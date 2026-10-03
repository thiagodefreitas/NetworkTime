---
description: "Benchmark clock synchronisation algorithms with ground truth: trace replay of real network delays, PTP exchanges and transparent clocks, ptp4l- and SPTP-style clients, boundary-clock chains, OMNeT++/INET and ns-3 interop."
---

# Trace replay and PTP chains

The [research bench](network.md#research-bench) scores synchronisation algorithms against a
simulated clock whose true offset is known. 2.16 adds two things to it ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29)):

- **real networks**: the delays of a capture or a log, replayed under the simulated clock;
- **PTP chains**: a grandmaster and N boundary clocks with servo models, checked against a
  time-error budget.

2.17 adds the exchange with network simulators (OMNeT++/INET, ns-3), two more reference
algorithms, and a benchmark on a replayed trace that anyone can reproduce from one scenario file.

3.1 adds **PTP exchanges** to the bench: Sync and Delay_Req messages at their own rates, transparent
clocks, and two PTP client models (`ptp4l`, `sptp`) scored on the same exchanges as every other
estimator.

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
hops end at about 60 ns of max|TE| but 20 hops at about 700 ns. A narrower, well-damped loop of
about 0.05 Hz keeps 20 hops below 10 ns once locked (three seeds; see the
[2026 preprint](https://github.com/thiagodefreitas/NetworkTime/tree/master/research/preprint-2026)). This is the range the G.8273.2 T-BC
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

## More reference algorithms

| Estimator | Idea |
|---|---|
| `hull` | Huygens-style (Geng et al., NSDI 2018), for one server. Each exchange bounds the true offset to `θm ± δ/2`; over a sliding window (64 exchanges, causal) the estimate is the straight line with the largest margin between those bounds, which is what Huygens' SVM finds. It assumes equal floor delays, like every two-way method. |
| `kalman-combine` | Multi-server, in the spirit of ntpd-rs (not its code): one delay-weighted Kalman filter per source; each source contributes `offset ± (3σ + floor/2)`; Marzullo intersection keeps the truechimers; inverse-variance mean of the survivors. |

On the bundled presets `hull` is the most accurate single-server estimator whenever floors are
symmetric, often by an order of magnitude, because it uses every exchange's bound instead of only
the lowest-delay ones. With the asymmetric route change of `route-change` it is biased like
everything else: the error is in the path, and no estimator can see it. `kalman-combine` rejects
the falseticker and the stepping server of `falseticker`.

## PTP exchanges in the bench

A scenario with `protocol = "ptp"` simulates the E2E delay mechanism of IEEE 1588 instead of NTP
exchanges: a Sync every `poll` seconds, a Delay_Req every `delay_interval` seconds, each with its
own one-way delay and timestamp noise (`server_noise`, per one-way measurement). `transparent` is
the fraction of queueing delay that transparent clocks on the path put in the correction field
(0 = switches without PTP support, 1 = full on-path support).

```toml
name = "ptp-office"
protocol = "ptp"
poll = 0.125            # 8 Sync/s
delay_interval = 1      # 1 Delay_Req/s
transparent = 0.0
duration = 7200
server_noise = 8e-9     # hardware timestamps
[forward]               # master -> slave
base = 4e-6
queue_mean = 3e-6
load = 0.4
[backward]              # slave -> master
base = 4e-6
queue_mean = 6e-6
load = 0.5
```

The series has the one-way `ms` (t2 − t1) of every Sync, the `sm` (t4 − t3) of every Delay_Req,
and the offset a slave computes with the latest mean path delay, so NTP-style estimators run on
it unchanged. Two presets come with it: `ptp-lan` (1 Sync and 1 Delay_Req per second, hardware
time stamps, switches without PTP support, more queueing towards the master) and `ptp-tc` (the same
network with transparent clocks that correct 95 % of the queueing).

| Estimator | Model |
|---|---|
| `ptp4l` | A linuxptp-style slave: offset `mean_path_delay − (t2 − t1)` at every Sync, with the mean path delay the moving median of the last 10 Delay_Req exchanges (ptp4l's default `delay_filter`), fed to the PI servo with linuxptp's default gains (or `servo="linreg"`). The servo steers a clock in closed loop; its correction is the estimate. |
| `sptp` | An SPTP-style client, after Meta's Simple PTP: client-driven exchanges that give all four timestamps at once. Only complete exchanges are used; the path delay is the median of the last 32, exchanges whose path delay exceeds it by more than 3 MAD are discarded as queueing outliers, and the rest go to the PI servo. A model of the approach, not of a particular release. |

Both also run on NTP series (each exchange is then complete). They are models, written from the
published algorithms, not the daemons' code. 4 h runs, 3 seeds, the first 30 minutes excluded:

| Estimator | `ptp-lan` rms | `ptp-tc` rms |
|---|---|---|
| raw (slave offset with the latest path delay) | 2.98 µs | 149 ns |
| `ptp4l` | 2.59 µs | 129 ns |
| `sptp` | 2.27 µs | 114 ns |
| `kalman-dw` | 344 ns | 22.5 ns |
| `mindelay` | 187 ns | 11.2 ns |
| `hull` | 7.0 ns | 7.0 ns |

With linuxptp's default gains at one Sync per second the servo follows the packet delay variation:
on a network without PTP support it is barely better than the raw offsets, and transparent clocks
improve it 20 times. Estimators that use the delay of every exchange get far closer from the same
packets, which is the argument behind delay-filtering PTP clients and NTP over PTP (below).
Run it yourself:

```bash
ntpstats simulate --preset ptp-lan --benchmark
ntpstats bench ptp-lan ptp-tc --seeds 1-3 --html ptp-bench.html
```

## NTP over PTP (RFC 10030)

RFC 10030 carries NTP messages in a TLV of unicast PTP event messages, so that NICs which time-stamp
only PTP can time-stamp NTP, and transparent clocks can correct its queueing. chrony 4.9 implements
the final specification. Captures of it are read like any NTP capture; the corrections are applied
as the RFC specifies (see [PTP captures](ptp.md#ntp-over-ptp-rfc-10030)), and
`examples/data/ntp-over-ptp.pcap` is a synthetic example:

```bash
ntpstats info examples/data/ntp-over-ptp.pcap
ntpstats trace examples/data/ntp-over-ptp.pcap --csv tc.csv   # its corrected delays, for the bench
```

## A reproducible benchmark on a replayed trace

[`examples/scenarios/replay-chrony.toml`](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/scenarios/replay-chrony.toml)
replays the delays of the bundled chrony `measurements.log` under a simulated oscillator and
scores every estimator against the true offset:

```bash
ntpstats bench examples/scenarios/replay-chrony.toml --seeds 1-5 --html bench.html
```

The result is [`docs/examples/trace-benchmark.html`](https://github.com/thiagodefreitas/NetworkTime/blob/master/docs/examples/trace-benchmark.html)
(download and open it). To run the same comparison on your own network, point `file` in the
scenario at your `measurements.log`, `peerstats` or capture. CI runs the scenario on every change.

## Network simulators: OMNeT++/INET and ns-3

ntpstats reads and writes the formats these simulators use, so a study can move between a
discrete-event simulation and real measurements.

**From a real clock into INET.** Fit the oscillator's noise from a log, and write it as settings
for INET's `RandomDriftOscillator`:

```bash
ntpstats noise tracking.log --drift --inet oscillator.ini
```

INET's oscillator makes the drift rate a random walk, with an increment drawn from
`uniform(-a, a)` ppm every `changeInterval` T. A random walk of frequency with step variance σ² per
T has `S_y(f) = σ²/(2π² T f²)`, so `h₋₂ = σ²/(2π² T)` and `a = √(6π² h₋₂ T)`.
`tests/test_simio.py` simulates exactly INET's update rule with the mapped `a` and checks its
ADEV against the h₋₂ model, from 100 s to 10⁴ s, within 15 %. Only the random-walk FM and the
frequency offset carry over. The file lists what the oscillator cannot represent (white and
flicker PM and FM, linear drift), with each one's ADEV at τ₀ and 1000 s, so the loss is visible.

**From INET back into ntpstats.** INET clocks record `timeChanged:vector`, the clock time at each
change. ntpstats reads `.vec` files directly and turns each clock into its time error against
simulation time:

```ini
# omnetpp.ini (INET gPTP showcase or your own network)
include oscillator.ini
**.clock.timeChanged:vector.vector-recording = true
output-vector-precision = 17     # keep ns resolution at long simulation times
```

```bash
ntpstats info results/General-#0.vec --all-peers           # one series per clock
ntpstats timeerror results/General-#0.vec --all-peers --limits budget.txt
ntpstats stability results/General-#0.vec --peer switch1 -k tdev,mtie
```

Other vectors (`pdelay`, `gmRateRatio`, your own statistics) are available with
`ntpstats.simio.read_omnetpp_vec(lines, vectors="pdelay*")`. The other way, `ntpstats convert
LOG --to omnetpp-vec -o measured.vec` writes measurements as a vector file, to plot them next to
simulation results in the OMNeT++ IDE or with `opp_scavetool`. The parser follows the documented
result file format and is tested on files in that format. CI does not run OMNeT++ itself.

**ns-3.** Captures written by `PcapHelper` are read like any other capture (NTP and PTP), and
two-column `time value` text from `FileHelper` or `GnuplotHelper` is read with `-f csv`.
`ntpstats convert LOG --to ns3` writes `time value` text (seconds) for an ns-3 program to read, for
example to drive a delay model from a real trace (`ntpstats trace … --csv` gives one-way delays).
