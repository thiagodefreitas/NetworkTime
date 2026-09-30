# Tools landscape

*Reviewed 30 September 2026.* This page lists the tools that practitioners and researchers
use and cite for network-time and clock analysis. For each, it says what the tool is good at,
where ntpstats overlaps, and how the two work together. ntpstats aims to **interoperate** with
these tools, not to replace them. Corrections are welcome as issues or pull requests.

## Frequency-stability analysis (metrology)

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **Stable32** (W. Riley; free from IEEE UFFC since 2017) | The reference Windows program for stability analysis, cited throughout the literature | The target for cross-validation ([#28](https://github.com/thiagodefreitas/NetworkTime/issues/28)); data file import/export planned ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33)) |
| **TimeLab** (J. Miles, KE5FX) | Acquisition and plotting for counters and phase-noise analysers; the time-nuts favourite | `.tim` import/export planned ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33)) |
| **allantools** (Python, LGPL) | Library of ADEV-family statistics; used in many papers and in BIPM training | Independent implementation here, checked against a frozen allantools table; an allantools-compatible API is planned ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33)) |
| MATLAB `allanvar`, R `allanvar` | Generic Allan variance functions | ntpstats adds EDF-based CIs, noise identification, gap handling and time-transfer inputs |

## NTP / NTS operations

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **chrony** / `chronyc` | The default client on most Linux distributions; logs tracking, measurements, statistics and refclocks | All of these logs are parsed, and chrony can be polled live |
| **ntpd-rs** | Rust NTP/NTS daemon with experimental NTPv5; planned default in Ubuntu 27.04 | NTPv5 interop tested; its Prometheus metrics are read with `ntpstats prom` ([Sources](sources.md)) |
| **NTPsec** `ntpviz` | Percentile plots from `loopstats`/`peerstats` | Same inputs; ntpstats adds stability statistics, network metrics and chrony support |
| **ntpperf** (M. Lichvar) | Load and timestamp-accuracy tester for NTP servers and PTP masters | Complementary: ntpstats analyses the resulting NTP and PTP captures |
| `chrony_exporter` + Prometheus/Grafana | Operational dashboards | ntpstats exports OpenMetrics with a Grafana dashboard ([Monitoring](monitoring.md)) and imports Prometheus range queries (`ntpstats prom`) |

## PTP and telecom

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **linuxptp** (`ptp4l`, `phc2sys`, `ts2phc`, `pmc`) | The Linux PTP stack | Logs parsed; live polling via `pmc` (`ntpstats watch ptp4l`) |
| **Meinberg PTP Track Hound** (free, closed source) | Captures and decodes PTP traffic, groups devices, monitors | Complementary: ntpstats computes offset, PDV and time-error statistics from the captures ([PTP & time error](ptp.md)) |
| **Calnex CAT**, VIAVI, Keysight, Microchip software | Vendor analysis for test equipment: TE, cTE, dTE, MTIE, TDEV, FPP with standard masks | ntpstats offers transparent, scriptable TE/cTE/dTE/MTIE/TDEV on exported data ([PTP & time error](ptp.md)); instrument import profiles planned ([#35](https://github.com/thiagodefreitas/NetworkTime/issues/35)) |
| **facebook/time** (ptpcheck, sptp, ptp4u, fbclock) | Meta's open-source PTP/NTP tools and TrueTime-style uncertainty | `ptpcheck stats` live polling (`ntpstats watch ptpcheck`); fbclock windows validated with `ntpstats bounds` |
| **OCP TAP Time Card / Open Time Server** | Open-hardware grandmaster (GNSS + atomic oscillator) | Planned self-monitoring and holdover analysis; sample data welcome ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21), [#26](https://github.com/thiagodefreitas/NetworkTime/issues/26)) |
| **AWS ClockBound** | Clock-error bound daemon for EC2 | Bounds validated against a reference (`ntpstats bounds`) |
| **Windows w32tm** | The Windows time service | `w32tm /stripchart` output read directly |
| **White Rabbit** (CERN OHWR) | Sub-ns time transfer | Its phase logs can be analysed as phase data; a dedicated format could arrive as a plugin ([#37](https://github.com/thiagodefreitas/NetworkTime/issues/37)) |
| Wireshark | General capture and dissection | ntpstats reads the same pcap/pcapng files and computes the timing statistics |

## GNSS and time transfer

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **CGGTTS** tools (BIPM r2cggtts, OpenTTP, rtk-rs `cggtts`) | GNSS common-view time transfer between laboratories | CGGTTS import and common-view differencing planned ([#34](https://github.com/thiagodefreitas/NetworkTime/issues/34)) |
| **RTKLIB**, IGS clock products, BIPM Circular T | GNSS processing; satellite/station clocks; UTC−UTC(k) | RINEX clock and Circular T import planned ([#34](https://github.com/thiagodefreitas/NetworkTime/issues/34)) |

## Research platforms and datasets

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **OMNeT++/INET** (gPTP models), **ns-3** | Network simulators used for TSN/PTP studies | Planned export of realistic oscillator noise and PDV traces, and import of simulation results ([#29](https://github.com/thiagodefreitas/NetworkTime/issues/29)) |
| **RIPE Atlas** NTP measurements, NTP Pool monitor data | Internet-scale public measurements used in recent studies (PACMCS 2024, NDSS 2026) | Import planned ([#34](https://github.com/thiagodefreitas/NetworkTime/issues/34)); ntpstats' own weekly interop data to be published ([#30](https://github.com/thiagodefreitas/NetworkTime/issues/30)) |

## Where ntpstats is different

- **One tool across the chain**: daemon logs, packet captures, instruments and live measurement
  (NTPv4, NTS, NTPv5) feed the same statistics, confidence intervals and reports.
- **Validation, not only plotting**: a simulator with ground truth, reference estimators and
  benchmarks, so an algorithm or a device can be *scored*.
- **Open and dependency-light**: MIT-licensed, numpy only, runs anywhere Python runs, a small web
  UI, and scriptable in CI.
