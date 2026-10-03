---
description: "Input formats read by ntpstats: ntpd peerstats/loopstats/rawstats, chrony measurements/tracking/statistics/refclocks, linuxptp, pcap/pcapng, CSV, Stable32, RINEX clock, CGGTTS and more."
---

# Input formats

Formats are detected automatically; `-f/--format` overrides detection.

| `--format` | Source | Offset used | Extra columns |
|---|---|---|---|
| `loopstats` | ntpd/NTPsec clock discipline | offset | frequency, jitter, wander, time constant |
| `peerstats` | ntpd/NTPsec per peer (`sys.peer` chosen by default) | offset | delay, dispersion, jitter |
| `rawstats` | ntpd/NTPsec on-wire timestamps | recomputed from T1–T4 | delay |
| `chrony-tracking` | chrony `tracking.log` | offset (negated) | frequency, skew, offset sd, root delay/dispersion |
| `chrony-measurements` | chrony `measurements.log` per source | θ | delay, dispersion, root delay/dispersion |
| `chrony-statistics` | chrony `statistics.log` | estimated offset (negated) | std dev, skew |
| `chrony-refclocks` | chrony `refclocks.log` (GNSS/PPS) | cooked offset | raw error, dispersion, PPS flag |
| `linuxptp` | `ptp4l`, `phc2sys`, `ts2phc` (stdout, syslog, journald) | master/phc offset (negated, ns → s) | path delay, frequency, servo state |
| `pcap` | pcap/pcapng captures of NTP (v3/v4/v5, also over PTP per RFC 10030), PTP (v2/v2.1, UDP or Ethernet) and CSPTP (client-server PTP); see [PTP](ptp.md) | NTP: from server T2/T3 and capture times; PTP: master vs capture clock | delay, stratum, version; PTP: path/link delay, one-way delays, correction |
| `csv` | generic `unix_time,offset[,…]`, `ntpstats monitor` output | offset column | any other columns |
| `stable32-phase` | Stable32 data file (phase in s; optional MJD timetags; not auto-detected) | chosen column (default last) | — |
| `stable32-freq` | Stable32 data file (fractional frequency; zeros are gaps; not auto-detected) | integrated to phase | — |
| `w32tm` | Windows `w32tm /stripchart /dataonly` text or `/rdtsc` CSV | NtpOffset (server − local) | delay |
| `prometheus` | saved Prometheus `query_range` JSON (`ntpstats prom`), e.g. ntpd-rs, chrony_exporter | metric value (use `--negate` for local − reference metrics) | labels in `meta` |
| `bounds` | ClockBound output or `earliest,latest[,unix_time,status]` CSV | window centre − local | `bound` (half-width), `synchronized` |
| `profile:NAME` / `profile:FILE.toml` | instrument exports described by a TOML profile ([Sources](sources.md)) | value column (TE negated) | chosen columns |
| `cggtts` | CGGTTS V2E GNSS time-transfer files (BIPM); line checksums verified | REFSYS (REF − GNSS time) averaged per epoch | satellites, spread; `ntpstats cv` for two sites |
| `rinex-clock` | RINEX clock (IGS `.clk`, gzip accepted) | clock bias per receiver/satellite | sigma |
| `circular-t` | BIPM Circular T section 1 (issues may be concatenated) | UTC − UTC(k) per laboratory | uncertainties in `meta` |
| `ripe-atlas` | RIPE Atlas NTP results (API JSON) | offset (negated: Atlas logs local − server) | rtt, stratum, root delay/dispersion |
| `ntppool` | NTP Pool monitor score log CSV | offset per monitor | rtt, score, step |
| `omnetpp-vec` | OMNeT++/INET output vector files (`.vec`, versions 2 and 3) | INET clocks (`timeChanged`): clock time − simulation time, negated; files written by ntpstats: their offset | other vectors of the module; any vector with `simio.read_omnetpp_vec(vectors=...)` |
| `gsoc2012` | the 2012 prototype's `estimators.log` | offset | — |

`ntpstats convert` writes any of these as a Stable32 file or plain CSV (see
[Stable32, TimeLab, allantools](migrating.md)).

The research and laboratory formats are described with worked examples in [Research data](research-data.md).
Gzipped files (`.gz`) are read directly.

## Sign convention

Every series uses **reference − local** (the ntpd convention: positive means the local clock
is behind). Parsers normalise on import, following each implementation's documentation:

| Source | Logged as | ntpstats |
|---|---|---|
| ntpd/NTPsec logs, `ntpq rv` | reference − local | kept |
| chrony measurements (θ), refclocks (cooked), `chronyc tracking` "System time" | reference − local | kept |
| chrony tracking, statistics, `chronyc sourcestats` | local − reference | negated |
| linuxptp `master offset`/`offset` | local − reference | negated |
| pcap | computed | reference − capture host |
| RIPE Atlas | local − server | negated |
| Circular T | UTC − UTC(k) | kept (UTC is the reference) |

## Enabling the logs

- **chrony**: `log tracking measurements statistics refclocks` and `logdir /var/log/chrony`.
- **ntpd/NTPsec**: `statsdir /var/log/ntpstats/`, `statistics loopstats peerstats rawstats`,
  `filegen peerstats file peerstats type day enable` (likewise for the others).
- **linuxptp**: run with `-m`, or collect `journalctl -u ptp4l -o short-iso-precise`, which
  maps the monotonic stamps to UTC.
- **captures**: `tcpdump -i eth0 -j adapter_unsynced --time-stamp-precision=nano -w ntp.pcap udp port 123`.

## Large files

The numeric columns of loopstats, peerstats and chrony logs are parsed with numpy's C
tokenizer (about 1–3 s per million lines). Irregular files fall back to a tolerant per-line
parser that reports skipped lines in `meta["skipped_lines"]`.
