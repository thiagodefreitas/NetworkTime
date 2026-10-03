---
description: "Live and offline sources: chrony, ntpd/NTPsec, ntpd-rs, linuxptp pmc, facebook/time ptpcheck, Windows w32tm, Prometheus, and validation of AWS ClockBound and fbclock error bounds."
---

# More sources, instruments and clock-error bounds

## Live PTP clients

`ntpstats watch` samples a running PTP client, just as it samples chrony or ntpd:

```bash
ntpstats watch ptp4l -i 1 -o ptp4l.csv          # linuxptp: pmc -u -b 0 'GET CURRENT_DATA_SET' 'GET TIME_STATUS_NP'
ntpstats watch ptpcheck -i 1 -o ptpcheck.csv    # facebook/time: ptpcheck stats
ntpstats watch ptp4l --metrics-port 9124        # and serve it to Prometheus
```

Recorded columns:
- **ptp4l**: `offsetFromMaster`, then `meanPathDelay`, `master_offset`, `stepsRemoved` and
  `gmPresent`.
- **ptpcheck**: `ptp.offset_ns` and `ptp.mean_path_delay_ns`.

Both tools report local − master, so the offsets are negated into the ntpstats convention
(reference − local). The web UI's *Live* workspace offers the same sources.

## ntpd-rs

```bash
ntpstats watch ntpd-rs -i 16 -o ntpd-rs.csv                     # runs: ntp-ctl -f prometheus status
ntpstats watch ntpd-rs --command-override http://127.0.0.1:9975/metrics   # or its metrics exporter
```

ntpd-rs 1.x exports `ntp_source_offset_seconds` (source − local, the ntpstats convention),
`ntp_source_uncertainty_seconds` and `ntp_source_delay_seconds` for every source. Each sample's
offset is the inverse-variance mean over the sources, and the log keeps the number of sources,
the best source's uncertainty and delay, and the system root delay, root dispersion and stratum.
The 2.0 pre-releases (July 2026) reworked ntpd-rs internals and no longer export per-source
offsets; `watch` says so instead of logging nothing. For those, analyse a packet capture (NTP,
NTP over PTP or CSPTP, see [PTP captures](ptp.md)).

## Windows (w32tm)

```bash
w32tm /stripchart /computer:time.windows.com /dataonly /samples:1000 > w32tm.txt
ntpstats stability w32tm.txt -k tdev,mtie        # format detected automatically
```

Both the `/dataonly` text (`HH:MM:SS, d:+00.0541615s o:-00.0031265s`, or the older form without
`d:`) and the `/rdtsc` CSV (`RdtscStart,RdtscEnd,FileTime,RoundtripDelay,NtpOffset`) are read.

Microsoft documents NtpOffset as "computed as per NTP offset computations" (server − local),
which is the ntpstats convention. The text form prints only a time of day: the date comes from
the "The current time is …" line when it can be read, midnight rollovers are handled, and the
times are the Windows host's local wall clock. The `/rdtsc` form carries exact FILETIME
timestamps.

## Prometheus (ntpd-rs, chrony_exporter, …)

Anything already in Prometheus can be pulled into ntpstats: ntpd-rs 1.x metrics
(`ntp_source_offset_seconds`), `chrony_exporter`, or ntpstats' own exporter.

```bash
ntpstats prom http://prometheus:9090 'ntp_source_offset_seconds' --since 7d --step 60 -o ntpd-rs.json
ntpstats stability ntpd-rs.json --all-peers -k oadev,tdev
```

The saved `query_range` JSON is a regular input format with one series per label set. Offsets are
taken as reference − local; ntpd-rs documents `ntp_source_offset_seconds` as the "offset between
the upstream source and system time". For a metric that reports local − reference, add
`--negate` (available on every command).

## Validating clock-error bounds

AWS **ClockBound**, Meta's **fbclock** and TrueTime-style APIs report a window
`[earliest, latest]` that should contain true time. `ntpstats bounds` checks this against a
better reference for the same host, for example a PPS/PTP comparison, or NTS measurements when
the bound is much wider than their delay:

```bash
ntpstats bounds clockbound.txt reference.csv                 # exit code 3 on any violation
ntpstats bounds windows.csv ptp4l.csv --max-violation-rate 1e-4 --json
```

Accepted bound inputs:
- **ClockBound**: the example client's output lines (`… true time was somewhere within A and B
  seconds …`). ClockBound builds the window around the system clock reading.
- **CSV**: `earliest,latest` columns (POSIX seconds), plus `unix_time` (the local clock read
  together with the window; needed when the window is not centred on the system clock, as
  with PHC-based fbclock) and an optional `status`. Values are parsed as exact decimals, because
  a float cannot hold nanoseconds at today's epoch.

Each window is classed as **inside**, **violated**, or **indeterminate** (the reference's own
uncertainty, half its round-trip delay by default, is too large to tell). The report gives the
violation rate, the worst excess, the median bound and the tightness (median |error| / median
bound).

Try it on the bundled examples:
`ntpstats bounds examples/data/clockbound.txt examples/data/clockbound-reference.csv`.

## Instrument export profiles

Time-interval counters and PTP/SyncE testers export CSV files whose layout varies by vendor. A
**profile** describes a layout in a few TOML lines, so a new instrument needs no code:

```toml
# my-counter.toml
name = "my-counter"
value_column = "TI (ns)"        # header name or index
units = "ns"                    # s, ms, us, ns, ps
quantity = "te"                 # te: local - reference (DUT - REF); offset: reference - local
time_column = "Timestamp"       # optional; else tau0 spacing
time_format = "iso"             # unix | iso | mjd | elapsed
skip_rows = 2                   # instrument banner lines
delimiter = ";"
extra_columns = ["Temperature"]
```

```bash
ntpstats timeerror export.csv -f profile:my-counter.toml --limits limits.csv
ntpstats timeerror tic.txt -f profile:tic-ns                 # built-in: one ns reading per line, 1 s apart
```

Built-in profiles:
- `te-csv`: unix time and TE in seconds;
- `tic-ns` and `tic-s`: one time-interval reading per line, 1 s apart;
- `iso-te-ns`: ISO 8601 timestamp and TE in ns.

Vendor profiles are added from sample exports that users share, via the *Share a sample log*
issue form or [issue #35](https://github.com/thiagodefreitas/NetworkTime/issues/35).
