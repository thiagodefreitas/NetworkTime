# Research data: time transfer, laboratories and Internet measurements

ntpstats reads the data behind recent time-transfer and NTP measurement studies directly:

| Format | Where it comes from | What you get |
|---|---|---|
| `cggtts` | GNSS time-transfer receivers at time laboratories (BIPM CGGTTS V2E) | REF − GNSS time per epoch; `ntpstats cv` gives UTC(A) − UTC(B) |
| `rinex-clock` | IGS clock products (`.clk`, gzip accepted) | receiver and satellite clock biases |
| `circular-t` | BIPM Circular T, section 1 | UTC − UTC(k) for about 80 laboratories |
| `ripe-atlas` | RIPE Atlas NTP measurements (API JSON) | offset and RTT per probe and server |
| `ntppool` | NTP Pool monitoring logs | offset, RTT and score per monitor |
| `interop` | the ntpstats open dataset (`data/interop/`, monthly since 2026) | NTP/NTS/NTPv5/Roughtime probes of public servers, with availability |

All are auto-detected and work with every command: `info`, `stability`, `noise`, `hat` and
`report`.

## Stability of UTC(k) from Circular T

Circular T gives UTC − UTC(k) every five days. Concatenate the issues you have into one file:

```bash
curl -O https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/cirt.44[0-9]
cat cirt.4* > cirt-all.txt
ntpstats info cirt-all.txt --all-peers                   # one series per laboratory
ntpstats stability cirt-all.txt --peer PTB -k tdev,htot  # stability of UTC(PTB)
```

The published uncertainties (uA, uB, u) are kept in each series' metadata.

## GNSS common view between two laboratories

```bash
ntpstats cv laba.cggtts labb.cggtts -o ab.csv           # REF(A) - REF(B), common view
ntpstats cv laba.cggtts labb.cggtts --mode aiv -o ab.csv # all in view
ntpstats stability ab.csv -k tdev,mdev
```

- **Common view** differences the same satellite at the same epoch, so satellite clock errors
  cancel.
- **All in view** differences the per-epoch means.
- Line checksums of each file are verified; failing lines are skipped and counted.

## GNSS timing receivers (u-blox UBX)

A raw u-blox receiver log (binary UBX frames, possibly mixed with NMEA sentences) is read directly
(format `ubx`, detected automatically). Three messages are used, with the layouts of the u-blox
interface description:

| Message | Series and columns |
|---|---|
| `UBX-NAV-CLOCK` | receiver clock bias as reported (`clkB`), with `clock_drift`, `time_accuracy` (tAcc), `freq_accuracy` (fAcc) |
| `UBX-NAV-TIMEUTC` | the UTC time of each navigation epoch (time stamps), `utc_accuracy` |
| `UBX-TIM-TP` | the quantization error `qErr` of each time pulse, at the pulse time |

Without NAV-TIMEUTC, times come from TIM-TP's GPS week with GPS − UTC = 18 s.

### Removing the PPS sawtooth

The receiver can only start its PPS on an edge of its internal clock, so each pulse is off by up
to half a clock period, drifting in a sawtooth; `qErr` predicts it. `ntpstats sawtooth` pairs each
time-interval-counter reading of the PPS with the `qErr` of that pulse and removes it:

```bash
ntpstats sawtooth examples/data/pps-tic.csv examples/data/ubx-timing.ubx -o corrected.csv
# 1800 PPS samples paired with qErr, sign +1 (data (smaller sample-to-sample variance))
#    TDEV  τ=1s 2.51 ns -> 1.16 ns  τ=10s 592 ps -> 378 ps  ...
```

u-blox does not state the sign with which `qErr` applies; ntpstats tries both and keeps the one that
removes the sawtooth (the smaller sample-to-sample variance), and reports it. Fix it with
`--sign +1` or `--sign -1` once it is known for a receiver and counter. The [sawtooth
notebook](notebooks.md) walks through the example.

## Clock products (IGS)

```bash
ntpstats stability IGS0OPSFIN_20250190000_01D_05M_CLK.CLK.gz --peer PTBB -k oadev,hdev
```

## NTP servers seen from many vantage points (RIPE Atlas)

```bash
curl "https://atlas.ripe.net/api/v2/measurements/MSM_ID/results/?format=json&start=...&stop=..." -o atlas.json
ntpstats info atlas.json --all-peers
```

In Python, `ntpstats.research.group_summary(series, by="peer")` gives the offset distribution per
server (median, 95th percentile of |offset|) across all probes, or `by="probe"` per vantage point.
Atlas logs local − server; ntpstats negates it to its usual server − local.

## NTP Pool monitors

```bash
curl "https://www.ntppool.org/scores/192.0.2.1/log?limit=2000&monitor=*" -o pool.csv
ntpstats info pool.csv --all-peers        # one series per monitor
ntpstats hat pool.csv --all-peers         # which monitor paths are noisy?
```

Please keep requests to public services modest.

## The ntpstats open interop dataset

Every week the Live interop workflow probes public NTP, NTS, NTS-pool, NTPv5 and Roughtime
servers; the first run of each month is recorded in
[`data/interop/`](https://github.com/thiagodefreitas/NetworkTime/tree/master/data/interop). The
dataset is versioned with every release (Zenodo), and its schema is in the directory's README.

```bash
ntpstats dataset data/interop --test nts      # availability and offsets of NTS servers over time
ntpstats stability data/interop --peer time.google.com -k oadev
```

A directory given to any command is read as the concatenation of its files.

Synthetic examples of every format are in
[`examples/data/`](https://github.com/thiagodefreitas/NetworkTime/tree/master/examples/data).
