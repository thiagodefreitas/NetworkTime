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
| `pcap` | pcap/pcapng captures of NTP (v3/v4/v5) and PTP (v2/v2.1, UDP or Ethernet; see [PTP](ptp.md)) | NTP: from server T2/T3 and capture times; PTP: master vs capture clock | delay, stratum, version; PTP: path/link delay, one-way delays, correction |
| `csv` | generic `unix_time,offset[,…]`, `ntpstats monitor` output | offset column | any other columns |
| `stable32-phase` | Stable32 data file (phase in s; optional MJD timetags; not auto-detected) | chosen column (default last) | — |
| `stable32-freq` | Stable32 data file (fractional frequency; zeros are gaps; not auto-detected) | integrated to phase | — |
| `gsoc2012` | the 2012 prototype's `estimators.log` | offset | — |

`ntpstats convert` writes any of these as a Stable32 file or plain CSV (see
[Stable32, TimeLab, allantools](migrating.md)).

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
