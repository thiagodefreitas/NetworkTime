# ntpstats — NetworkTime analysis toolkit

**Validate, evaluate and study network time synchronisation.** `ntpstats` reads the logs written by
today's NTP implementations (**ntpd 4.2.8, NTPsec, chrony**), measures servers directly with a
privacy-preserving SNTP client, and computes the clock-offset, network-delay and
frequency-stability statistics used in timing research and in telecom standards (ADEV, MDEV,
TDEV, Hadamard, MTIE, floor packet percentage) with confidence intervals and noise
identification. A built-in simulator with **ground truth** turns it into a test bench for
synchronisation algorithms.

📖 **Documentation:** [thiagodefreitas.github.io/NetworkTime](https://thiagodefreitas.github.io/NetworkTime/)
· [Wiki](https://github.com/thiagodefreitas/NetworkTime/wiki) · `pip install ntpstats`

It started as a Google Summer of Code 2012 project for the NTP Project (kept unchanged in
[`legacy/`](legacy/)); version 2 is a complete rewrite. See
[docs/STATE_OF_THE_ART.md](docs/STATE_OF_THE_ART.md) for what changed in NTP since 2012 and what
was wrong with the original code, [docs/INTEROP.md](docs/INTEROP.md) for live results against
public NTP/NTS servers, [CHANGELOG.md](CHANGELOG.md) for releases and
[ROADMAP.md](ROADMAP.md) for where it is going.

![Offset view with RTS smoother and ground truth](docs/img/ui-offset-light.png)

| | |
|---|---|
| ![Stability with confidence bands and slope guides](docs/img/ui-stability.png) | ![Network wedge, delay floor and FPP](docs/img/ui-network.png) |
| ![Comparing two peers](docs/img/ui-stability-compare.png) | ![Dark mode](docs/img/ui-offset-dark.png) |

## Highlights

- **Every common source, auto-detected**:
  - ntpd/NTPsec `loopstats`, `peerstats` (per peer, `sys.peer` picked automatically) and
    `rawstats` (offset/delay recomputed from the four on-wire timestamps);
  - chrony `tracking.log`, `measurements.log`, `statistics.log` and `refclocks.log`
    (GNSS/PPS reference clocks);
  - **PTP**: linuxptp `ptp4l`, `phc2sys`, `ts2phc` output from stdout, syslog or journald
    (monotonic stamps are mapped to UTC when the journal prefix is present);
  - **packet captures** (pcap/pcapng, including nanosecond and hardware timestamps): NTP
    exchanges are matched and measured from the capture host's clock;
  - generic CSV and the 2012 `estimators.log`.

  Every sign convention is normalised to *reference − local*, following each implementation's
  documentation (table below).
- **Stability analysis done right**: non-overlapping and overlapping ADEV, MDEV, TDEV,
  overlapping Hadamard, total and modified total deviation (TOTDEV, MTOT), Theo1, TheoBR, TheoH,
  MTIE (O(N log N)) and TIErms, each with
  - χ² confidence intervals from the **exact** equivalent degrees of freedom of the discrete
    power-law model (Monte Carlo verified),
  - per-τ power-law noise identification (lag-1 autocorrelation method),
  - correct τ₀ from the data and **gap handling that never invents data** (irregular logs are
    put on a grid; terms that would span a gap are dropped, not interpolated),
  - **dynamic** (sliding-window) views to expose non-stationarity,
  - **limit-mask** checks against user-supplied CSV masks (`tau,tdev`, `tau,mtie`, … e.g.
    network TDEV/MTIE limits), with margins and PASS/FAIL,
  - **compare** a source against a reference (PPS, GNSS or a better server) to get the error's
    bias, RMS, TDEV and MTIE.
- **Network metrics**: delay floor and queueing distribution, Mills' offset-vs-delay *wedge*,
  asymmetry indicator, floor packet percentage (ITU-T G.8260-style), NTP clock-filter
  (minimum delay) selection.
- **Estimators**: two-state Kalman filter with irregular sampling, noise parameters fitted
  from the data's ADEV, innovation gating, delay-aware measurement weighting and an
  RTS smoother.
- **Research bench**: simulated clocks and networks with ground truth, and pluggable
  estimators scored by `ntpstats bench`:
  - simulator: power-law oscillator noise (white/flicker PM, white/flicker/random-walk FM),
    frequency offset, drift, temperature wander, asymmetric queueing paths, route changes,
    congestion and outages, and multi-server scenarios with falsetickers;
  - reference algorithms: Kalman/RTS, NTP clock filter, chrony-style regression,
    RADclock-style feed-forward, and RFC 5905 select/cluster/combine;
  - bring your own estimator via a small API or a package entry point; scenarios can be
    presets or TOML files;
  - reproducible reports as tables, CSV/JSON or self-contained HTML.
- **Reports**: `ntpstats report` writes a single offline HTML file with charts, CI tables,
  network analysis, parameters and input hashes (also a *Report* button in the UI).
- **Measurement clients** (they never set the clock):
  - NTPv4 SNTP with a random transmit timestamp (data minimisation), origin check,
    Kiss-o'-Death and 2036 era handling;
  - **NTS** (RFC 8915): NTS-KE over TLS 1.3 with certificate and host-name checks, AES-SIV
    authenticated exchanges and cookie renewal (optional extra `ntpstats[nts]`);
  - experimental **NTPv5** (draft-ietf-ntp-ntpv5-09): v5 header with cookies, timescale and
    era, plus the NTPv4→v5 upgrade probe;
  - a polite `monitor` (RATE back-off, jitter), and `watch`, which samples the local
    **chrony** (`chronyc -c tracking`) or **ntpd/NTPsec** (`ntpq -c rv`) without log files.
- **Lightweight UI**: `ntpstats ui` starts a local web app. It runs on the Python standard
  library HTTP server with one static page and [uPlot](https://github.com/leeoniya/uPlot) (≈50 kB,
  bundled, MIT), so there is no Qt, Electron, Node or CDN, and it works offline. Light and dark
  themes, drag-and-drop, overlay comparison, zoom-to-analyse, PNG/CSV export and a live
  monitor.
- **Small footprint**: the only runtime dependency is **numpy**. matplotlib is optional
  (static/publication figures).

## Install

```bash
pip install ntpstats                # core + UI (numpy only)
pip install "ntpstats[plot]"        # + matplotlib figures
pip install "ntpstats[nts]"         # + NTS client (pyOpenSSL, cryptography)
pip install git+https://github.com/thiagodefreitas/NetworkTime.git   # latest master
# from a checkout, for development:
pip install -e ".[test,plot,nts,docs]" && pytest
```

Python ≥ 3.9.

## Quick start

```bash
# Web UI (opens your browser at http://127.0.0.1:8123)
ntpstats ui /var/log/chrony/measurements.log /var/log/ntpstats/peerstats

# Summary statistics
ntpstats info /var/log/ntpstats/loopstats.20260928

# Stability table with 95 % confidence intervals and noise identification
ntpstats stability /var/log/chrony/tracking.log -k oadev,mdev,tdev,mtie --ci 0.95

# Check TDEV against a limit mask (CSV "tau,tdev"); exit code 3 on failure
ntpstats stability ptp.log -k tdev,mtie --mask my-tdev-mask.csv

# Validate a client against a reference (e.g. chrony vs a PPS refclock or GNSS host)
ntpstats compare /var/log/chrony/tracking.log /var/log/chrony/refclocks.log --ref-peer PPS0

# Sliding-window stability matrix (time x tau) as CSV
ntpstats dynamic peerstats --peer 192.0.2.10 -k mdev

# Network behaviour of one peer
ntpstats network /var/log/ntpstats/peerstats --peer 192.0.2.10

# Filters (Kalman / RTS smoother / min-delay) -> CSV
ntpstats filter peerstats --peer 192.0.2.10 -m rts -o smoothed.csv

# Publication figure (needs matplotlib)
ntpstats plot peerstats --all-peers -k oadev,tdev --detrend linear -o report.pdf

# Measure a server yourself (never sets the clock)
ntpstats query time.cloudflare.com -c 4
ntpstats monitor pool.ntp.org ptbtime1.ptb.de -i 64 -o mylog.csv

# Test bench: simulate NTP exchanges and score the built-in estimators
ntpstats simulate --preset internet --benchmark
```

```
Scenario 'internet': 1350 exchanges, poll 64 s, seed 1
   estimator                               rms       bias  p95 |err|  max |err|
   raw measurements                    1.65 ms    -659 µs    3.61 ms    14.1 ms
   Kalman                               617 µs    -569 µs     945 µs    1.84 ms
   Kalman + delay weighting             183 µs    -139 µs     355 µs    1.31 ms
   RTS smoother + delay weighting       210 µs    -202 µs     293 µs     315 µs
   min-delay filter (8)                 112 µs     761 ns     248 µs     752 µs
```

More measurement commands:

```bash
ntpstats query time.cloudflare.com --nts            # NTS-authenticated (pip install 'ntpstats[nts]')
ntpstats query ntpd-rs.example.net --ntpv5          # experimental NTPv5 draft-09
ntpstats query pool.ntp.org --probe-v5              # does the server offer NTPv5?
ntpstats watch chrony -i 16 -o chrony-live.csv      # local daemon, no log files needed
ntpstats info capture.pcapng                        # NTP exchanges from a packet capture
ntpstats stability /var/log/ptp4l.log -k tdev,mtie  # PTP servo offsets
```

### Benchmarking synchronisation algorithms

```bash
ntpstats bench --list                                        # estimators and preset scenarios
ntpstats bench internet falseticker examples/scenarios/*.toml --seeds 1-10 \
        --html bench.html --csv bench.csv                    # full comparison
python examples/04_custom_estimator.py                       # plug in your own algorithm
```

![Benchmark report](docs/img/benchmark-report.png)

Example reports: [benchmark](docs/examples/benchmark-report.html),
[peerstats analysis](docs/examples/peerstats-report.html) (download and open in a browser).

Some findings the bench makes visible:
- On a congested WAN, the delay-aware estimators (regression, feed-forward, min-delay,
  delay-weighted Kalman) cut the error 10–30× compared with the raw measurements.
- An asymmetric route change (`route-change` preset) biases *every* estimator by half the
  one-way step, and no amount of filtering can see it.
- RFC 5905 selection rejects falsetickers only when their error exceeds the root distance
  (≈ delay/2). Smaller ones are indistinguishable from path asymmetry by design.

Common options: `--format` (override detection), `--peer`, `--all-peers`,
`--start/--end` (POSIX seconds or ISO 8601 UTC), `--outliers K` (drop > K·MAD after
detrending), `--json`/`--csv` output.

### Sign conventions

| Source | Logged as | ntpstats |
|---|---|---|
| ntpd/NTPsec loopstats, peerstats, rawstats, `ntpq rv` | reference − local | kept |
| chrony `measurements.log` (θ), `refclocks.log` (cooked), `chronyc tracking` "System time" | reference − local ("positive = local slow") | kept |
| chrony `tracking.log`, `statistics.log`, `chronyc sourcestats` | local − reference ("positive = local fast") | negated |
| linuxptp `master offset` / `offset` (ns) | local − reference | negated, converted to s |
| pcap captures | computed from server T2/T3 and capture times | reference − capture host |

### Enabling the logs

- **chrony** (`/etc/chrony/chrony.conf` or `/etc/chrony.conf`): `log tracking measurements statistics refclocks`
  and `logdir /var/log/chrony`.
- **linuxptp**: run `ptp4l`/`phc2sys` with `-m` (stdout) or collect
  `journalctl -u ptp4l -o short-iso-precise`, which gives UTC time stamps.
- **captures**: `tcpdump -i eth0 -j adapter_unsynced --time-stamp-precision=nano -w ntp.pcap udp port 123`.
- **ntpd / NTPsec** (`ntp.conf`): `statsdir /var/log/ntpstats/`, `statistics loopstats peerstats rawstats`,
  `filegen peerstats file peerstats type day enable` (same for the others).

### Docker

```bash
docker build -t ntpstats .
docker run --rm -p 8123:8123 -v "$PWD:/data" ntpstats ui /data/peerstats --host 0.0.0.0 --no-browser
docker run --rm ntpstats query --nts time.cloudflare.com
```

### Performance

On a modest shared CPU: parsing takes about 1 s per million loopstats lines (2.4 s for
peerstats) using numpy's C tokenizer, and a full stability analysis (OADEV/MDEV/TDEV/HDEV with
exact-EDF confidence intervals) of **1 million samples** takes about 1.2 s. The UI only receives
decimated data (min/max per bucket), so it stays responsive with large files.

## Python API

```python
from ntpstats import load_one
from ntpstats.stability import series_stability
from ntpstats.analysis import summary, compare
from ntpstats.simulate import Scenario, simulate_ntp
from ntpstats.filters import kalman_series

s = load_one("/var/log/chrony/measurements.log", peer="192.0.2.10")
print(summary(s)["range_90"])
for r in series_stability(s, kinds=("oadev", "tdev"), ci=0.95):
    print(r.kind, r.taus, r.dev, r.lo, r.hi, r.alpha)

meas, truth = simulate_ntp(Scenario(duration=86400, seed=1))
print(compare(kalman_series(meas, smooth=True), truth))
```

More in [`examples/`](examples/): `01_quickstart.py`, `02_benchmark_filters.py` (a template for
evaluating your own algorithm), `03_report_figure.py`, and `make_example_logs.py`, which
regenerates the sample logs in `examples/data/` in each native format.

## Validation

`pytest` runs about 170 tests (plus `ruff` lint and coverage in CI), and none of them need network access:

- every estimator is checked against a literal implementation of the NIST SP 1065 sums, against
  the analytic log-log slopes of the five power-law noise types, and against a frozen table of
  values from an independent implementation (no third-party stability library is needed);
- the confidence-interval coverage is checked by Monte Carlo;
- noise identification is checked for α = +2 … −2;
- parsers are checked on the line layouts from the ntpd and chrony documentation, and by
  cross-checking that the same simulated peer reads identically from peerstats, rawstats and
  chrony logs;
- the SNTP, NTPv5 and NTS clients are checked against local test servers (offset, delay, KoD,
  spoofed replies, timeouts, 2036 rollover, TAI timescale, forged NTS responses, certificate
  mismatch);
- the pcap/pcapng readers are checked on synthesised captures (VLAN tags, nanosecond
  resolution, NTPv4 and v5 matching), and the linuxptp parser on the exact `pr_info` formats from
  the linuxptp source;
- the web API is checked, including its CSRF, Host-header and path-traversal protections.

CI runs on Python 3.9, 3.11 and 3.13.

## Security notes

The UI binds to `127.0.0.1`, rejects foreign `Host` headers (DNS rebinding), requires a custom
header on all state-changing requests (CSRF) and sends a strict Content-Security-Policy. It has no
authentication, so do not expose it with `--host 0.0.0.0` on untrusted networks. The SNTP client
is for measurement only: it does not authenticate time (for NTS use chrony or NTPsec and analyse
their logs).

## Project layout

```
src/ntpstats/     parsers, pcap, stability, edf, masks, analysis, network, filters, simulate,
                  estimators, bench, report, sntp (v4/v5), nts, sources (chronyc/ntpq),
                  monitor, cli, plotting
src/ntpstats/web  stdlib HTTP server + static UI (uPlot vendored)
tests/            pytest suite (+ frozen reference data)
examples/         scripts and sample logs
docs/             state of the art, live interop results, example reports, screenshots
legacy/           the original 2012 GSoC code, untouched
```

## License and citation

MIT License. © 2012–2026 **Thiago de Freitas** <thiagodefreitas@gmail.com>. Free for commercial
and non-commercial use; please keep the copyright notice and credit the author (see
[NOTICE](NOTICE)). If you use it in research, please cite it via [CITATION.cff](CITATION.cff).
The bundled uPlot is MIT-licensed © Leon Sorokin. The code under `legacy/` keeps its original
2012 license.
