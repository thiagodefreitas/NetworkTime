# Tools landscape

*Reviewed 3 October 2026.* This page lists the tools that practitioners and researchers
use and cite for network-time and clock analysis. For each, it says what the tool is good at,
where ntpstats overlaps, and how the two work together. ntpstats aims to **interoperate** with
these tools, not to replace them. Corrections are welcome as issues or pull requests.

## Frequency-stability analysis (metrology)

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **Stable32** (W. Riley; free from IEEE UFFC since 2017) | The reference Windows program for stability analysis, cited throughout the literature | Data files read and written (`-f stable32-phase`, `convert --to stable32-phase`), so a dataset can be analysed in both; the NIST SP 1065 tables it is checked against are reproduced to 7 digits, and Stable32's own output files on four data sets agree to its printed digits ([Validation](validation.md#stable32-cross-check)) |
| **TimeLab** (J. Miles, KE5FX) | Acquisition and plotting for counters and phase-noise analysers; the time-nuts favourite | `.tim` import waits for sample files, as the format is not documented ([#33](https://github.com/thiagodefreitas/NetworkTime/issues/33)); HTOT and the other TimeLab statistics are available |
| **allantools** (Python, LGPL) | Library of ADEV-family statistics; used in many papers and in BIPM training | Independent implementation, checked against a frozen allantools table; `from ntpstats.compat import allantools` offers its function signatures ([migrating](migrating.md)) |
| MATLAB `allanvar`, R `allanvar` | Generic Allan variance functions | ntpstats adds EDF-based CIs, noise identification, gap handling and time-transfer inputs |

## NTP / NTS operations

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **chrony** / `chronyc` | The default client on most Linux distributions; logs tracking, measurements, statistics and refclocks | All of these logs are parsed, and chrony can be polled live |
| **ntpd-rs** | Rust NTP/NTS daemon with experimental NTPv5 and, in 2.0, CSPTP; announced as the default in Ubuntu 27.04 | NTPv5 interop tested; polled live with `ntpstats watch ntpd-rs` (1.x metrics) or read from Prometheus with `ntpstats prom`; its CSPTP exchanges are read from captures ([Sources](sources.md), [PTP](ptp.md)) |
| **NTPsec** `ntpviz` | Percentile plots from `loopstats`/`peerstats` | Same inputs; ntpstats adds stability statistics, network metrics and chrony support |
| **ntpxyz** (Python) | Plots of ntpd `loopstats`, `sysstats` and `usestats` with matplotlib | Overlapping inputs for loopstats; ntpstats adds confidence intervals, peer/network analysis and the other daemons |
| **chrony_ntp_logconv** | Converts chrony `tracking`/`statistics` logs so that `ntpviz` can plot them | Not needed with ntpstats, which reads chrony logs directly (and keeps chrony's error bounds distinct from an Allan deviation) |
| **ntpperf** (M. Lichvar) | Load and timestamp-accuracy tester for NTP servers and PTP masters | Complementary: ntpstats analyses the resulting NTP and PTP captures |
| `chrony_exporter` + Prometheus/Grafana | Operational dashboards | ntpstats exports OpenMetrics and OpenTelemetry with a Grafana dashboard ([Monitoring](monitoring.md)) and imports Prometheus range queries (`ntpstats prom`) |

## PTP and telecom

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **linuxptp** (`ptp4l`, `phc2sys`, `ts2phc`, `pmc`) | The Linux PTP stack | Logs parsed; live polling via `pmc` (`ntpstats watch ptp4l`) |
| **Meinberg PTP Track Hound** (free, closed source) | Captures and decodes PTP traffic, groups devices, monitors | Complementary: ntpstats computes offset, PDV and time-error statistics from the captures ([PTP & time error](ptp.md)) |
| **Calnex CAT**, VIAVI, Keysight, Microchip software | Vendor analysis for test equipment: TE, cTE, dTE, MTIE, TDEV, FPP with standard masks | ntpstats offers transparent, scriptable TE/cTE/dTE/MTIE/TDEV on exported data ([PTP & time error](ptp.md)); exports are read through TOML import profiles, with vendor profiles added from contributed samples ([#35](https://github.com/thiagodefreitas/NetworkTime/issues/35)) |
| **facebook/time** (ptpcheck, sptp, ptp4u, fbclock) | Meta's open-source PTP/NTP tools and TrueTime-style uncertainty | `ptpcheck stats` live polling (`ntpstats watch ptpcheck`); fbclock windows validated with `ntpstats bounds`; an SPTP-style client model is scored in the bench ([Trace replay & PTP](research-bench.md)) |
| **PTP-DAL** (Python) | Offline analysis of recorded PTP datasets: synchronisation algorithms scored with max\|TE\| and MTIE | Similar research purpose; ntpstats works from standard captures and daemon logs, simulates exchanges with ground truth and covers NTP too |
| **timeTools** (Python, GPL-3) | Time error, MTIE and TDEV, and PDV generation with ITU-T G.8263-style methods | Overlapping metrics; ntpstats (MIT) adds the input formats, limits and masks, captures and the audit report |
| **OCP TAP Time Card / Open Time Server** | Open-hardware grandmaster (GNSS + atomic oscillator) | Holdover prediction applies to its logs ([Metrology](metrology.md)); dedicated parsers wait for sample data ([#21](https://github.com/thiagodefreitas/NetworkTime/issues/21)) |
| **AWS ClockBound** | Clock-error bound daemon for EC2 | Bounds validated against a reference (`ntpstats bounds`) |
| **Windows w32tm** | The Windows time service | `w32tm /stripchart` output read directly |
| **White Rabbit** (CERN OHWR) | Sub-ns time transfer | Its phase logs can be analysed as phase data; a dedicated format can be added as a plugin ([Writing a plugin](plugins.md)) |
| Wireshark | General capture and dissection | ntpstats reads the same pcap/pcapng files and computes the timing statistics |

## GNSS and time transfer

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **CGGTTS** tools (BIPM r2cggtts, OpenTTP, rtk-rs `cggtts`) | GNSS common-view time transfer between laboratories | CGGTTS files read with checksums verified; common-view and all-in-view differencing (`ntpstats cv`) ([Research data](research-data.md)) |
| **RTKLIB**, IGS clock products, BIPM Circular T | GNSS processing; satellite/station clocks; UTC−UTC(k) | RINEX clock files and Circular T read directly ([Research data](research-data.md)) |

## Research platforms and datasets

| Tool | What it is | Relation to ntpstats |
|---|---|---|
| **OMNeT++/INET** (gPTP models), **ns-3** | Network simulators used for TSN/PTP studies | `.vec` result files read (INET clocks become time error) and written; INET oscillator settings fitted to a real clock; ns-3 text and captures ([Trace replay & PTP chains](research-bench.md)) |
| **RIPE Atlas** NTP measurements, NTP Pool monitor data | Internet-scale public measurements used in recent studies (PACMCS 2024, NDSS 2026) | Both read directly ([Research data](research-data.md)); ntpstats publishes its own monthly interop measurements as an open dataset (`data/interop/`) |

## Where ntpstats is different

- **One tool across the chain**: daemon logs, packet captures, instruments and live measurement
  (NTPv4, NTS, NTPv5) feed the same statistics, confidence intervals and reports.
- **Validation, not only plotting**: a simulator with ground truth, reference estimators and
  benchmarks, so an algorithm or a device can be *scored*.
- **Open and dependency-light**: MIT-licensed, numpy only, runs anywhere Python runs (and in the
  browser), a small web UI, and scriptable in CI with a stable Python API.
