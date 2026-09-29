# From a 2012 student project to a 2026 research tool

*Author: Thiago de Freitas — reviewed September 2026.*

This note answers three questions: **is the 2012 approach still applicable, how is network
time measured and analysed today, and what had to change?**

## 1. Is it still applicable?

**The core idea still holds.** Analysing clock offsets with Allan-type statistics is exactly
what timing laboratories, operators and researchers still do. NTPv4 (RFC 5905, 2010) is still the
protocol on the wire, and ntpd still writes `loopstats`/`peerstats` in the same layout as in 2012.

**Almost everything around the idea changed.** The 2012 code could not be used as it was:

| Area | 2012 | 2026 |
|---|---|---|
| NTP daemons | ntpd almost everywhere | **chrony** is the default on RHEL/Fedora/SUSE and, since 25.10, on Ubuntu (with NTS on by default); **NTPsec** is maintained as a hardened ntpd fork with its own `ntpviz` plots; ntpd 4.2.8p18 (May 2024) is still the latest reference release |
| Log formats understood | ntpd `loopstats` only | ntpd/NTPsec `loopstats`, `peerstats`, `rawstats`; chrony `tracking`, `measurements`, `statistics`; CSV |
| Security | unauthenticated, or symmetric MD5 keys | **NTS** (RFC 8915, TLS 1.3 key establishment and AEAD-protected packets); MD5 MACs deprecated (RFC 8573); BCP RFC 8633; source-port randomisation (RFC 9109); client data minimisation (random transmit timestamp) |
| Protocol evolution | NTPv4 | NTPv4 plus extension fields (RFC 7822); **NTPv5** in the IETF NTP WG (draft-ietf-ntp-ntpv5-09, July 2026: client/server only, legacy modes removed, cookies instead of origin timestamps, timescale and era fields). ntpd-rs ships an experimental draft-09 implementation; chrony 4.9 does not implement NTPv5 yet but supports NTP-over-PTP (RFC 10030) |
| Accuracy frontier | ms over the Internet, sub-ms on a LAN | NTP with hardware timestamping reaches tens of ns to µs on LANs (chrony `hwtimestamp`); **PTP / IEEE 1588-2019** (and White Rabbit) for ns; cloud providers expose PTP-disciplined clocks to VMs |
| Leap seconds | smeared by some operators | CGPM 2022 decided to stop inserting leap seconds by 2035; smearing (e.g. Google) is widely deployed |
| Time horizon | — | **2036 NTP era rollover** (32-bit seconds wrap on 7 Feb 2036), which clients must handle |
| Python stack | Python 2.6/2.7, PySide 1 (Qt 4), matplotlib 1.x | Python 2 end-of-life (2020); Qt 4/PySide 1 dead; matplotlib removed `hold`, `normed`, `NavigationToolbar2QTAgg` |

## 2. How is it done nowadays?

**Operations and monitoring**
- `chronyc tracking/sourcestats/ntpdata`, `ntpq -p` / `ntpmon` (NTPsec), and Prometheus
  exporters (for example `chrony_exporter`) for dashboards.
- NTPsec `ntpviz` produces offset/jitter/frequency percentile plots from `loopstats`/`peerstats`.
  `ntpstats` covers those summaries (p1/p5/p50/p95/p99, 90 % and 98 % ranges) and adds stability
  statistics, network metrics and chrony support.

**Metrology and research**
- Frequency-stability statistics are defined in IEEE Std 1139 and NIST SP 1065 (Riley,
  *Handbook of Frequency Stability Analysis*). In practice the overlapping estimators are
  preferred, and results are reported with confidence intervals based on equivalent degrees of
  freedom and with identified noise types, not as bare curves.
- Packet-network timing (telecom, PTP and NTP) is characterised with **TDEV and MTIE**
  (ITU-T G.810) and with packet-delay-variation metrics such as the **floor packet percentage**
  (ITU-T G.8260).
- Synchronisation algorithms are evaluated against a reference (GNSS/PPS, a PTP grandmaster or a
  simulation with ground truth) rather than by looking at their own reported offset. The
  algorithm side includes chrony's regression-based source tracking, RADclock-style feed-forward
  clocks, and data-centre systems such as Huygens (NSDI 2018) and Sundial (OSDI 2020). What they
  share is exploiting the minimum-delay (floor) packets, which is the idea behind the network
  view and the delay-weighted Kalman filter here.

**What `ntpstats` 2 does with this**: it ingests all current log formats (including PTP and
packet captures), measures servers with NTPv4, NTS and experimental NTPv5 clients, can watch a
local chrony/ntpd directly; implements the
standard estimators with confidence intervals, noise identification and correct gap handling;
provides network-delay metrics and reference estimators; and includes a simulator with ground
truth, so an algorithm can be *validated* rather than just plotted.

## 3. What was wrong in the 2012 code (review)

The original code is preserved unchanged in [`legacy/`](https://github.com/thiagodefreitas/NetworkTime/tree/master/legacy). A review found:

1. **Wrong τ axis and wrong ADEV values.** `allanDevMills()` hard-coded the base averaging
   time to 32 s regardless of the data. loopstats are written at the poll interval (the sample
   file's median interval is 1072 s), so on the bundled data both τ and σ(τ) were off by
   **≈33.5×** (reported: τ = 32 s, σ = 8.6e-4; correct: τ = 1072 s, σ = 2.6e-5).
2. **Irregular sampling and gaps ignored.** Samples were treated as equally spaced, but the
   sample loopstats is only 51 % regular and contains a 2.5 h gap, so estimates silently mixed
   different τ values.
3. **`allanDev()` (R `allanvar` port)** averaged 2^i−1 samples but divided by 2^i, skipped
   index 0, and treated offsets (phase data) as if they were frequency data.
4. **GUI state bugs.** The `modified`/`exceeds` flags were never reset when a new file was
   loaded, so the second file's time axis was not converted. The last window indexed
   `secondsPure[range_max]` one past the end (`IndexError`). Loading was blocked unless the
   *Contents* tab was active.
5. **Estimator feedback.** `estimators.py` fed filtered offsets back into the timestamps
   (`t1 += delta + kf_off`), hard-coded a 32 s step in all four Kalman variants, shelled out to
   `sudo /home/thiago/ntdate.sh`, and polled public NIST servers every 32 s from a thread timer.
6. **Vendored ntplib 0.1.9** put the local clock in the transmit timestamp (a privacy leak) and did
   not verify the origin timestamp, handle KoD packets, or handle the 2036 era.
7. **Not runnable today**: Python 2 syntax, PySide 1 / Qt 4, and removed matplotlib APIs.

Every item above is addressed in v2, and items 1–3 and 6 are covered by regression tests.

## Sources

- NTP 4.2.8p18 release: <https://www.nwtime.org/news/ntp-4-2-8p18-released/>
- chrony NEWS / chrony.conf(5) (log formats and sign conventions): <https://chrony-project.org/>
- ntpd-rs (experimental NTPv5 draft-09): <https://github.com/pendulum-project/ntpd-rs>
- linuxptp (`ptp4l`, `phc2sys`, `ts2phc` message formats): <https://github.com/richardcochran/linuxptp>
- Ubuntu 25.10 adopts chrony with NTS: <https://www.phoronix.com/news/Ubuntu-25.10-Chrony>,
  <https://www.omgubuntu.co.uk/2025/06/ubuntu-chrony-nts-default-25-10>
- NTPv5 draft: <https://datatracker.ietf.org/doc/draft-ietf-ntp-ntpv5/>
- RFC 5905 (NTPv4), RFC 8915 (NTS), RFC 8633 (NTP BCP), RFC 8573 (MD5 deprecation), RFC 9109
  (port randomisation), RFC 7822 (extension fields): <https://www.rfc-editor.org/>
- W. J. Riley, *Handbook of Frequency Stability Analysis*, NIST SP 1065 (2008).
- W. Riley and C. Greenhall, "Power law noise identification using the lag 1 autocorrelation",
  EFTF 2004.
- ITU-T G.810 (definitions of TDEV/MTIE), G.8260 (packet timing metrics, FPP).
