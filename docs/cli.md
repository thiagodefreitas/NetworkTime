# CLI reference

`ntpstats <command> --help` shows every option. Common input options (`info`, `stability`,
`dynamic`, `plot`, `network`, `filter`, `report`):

| Option | Meaning |
|---|---|
| `-f/--format` | force a format instead of auto-detection; `profile:NAME` or `profile:FILE.toml` for instrument exports |
| `--negate` | flip the offset sign (for sources that log local − reference) |
| `--peer ADDR` / `--all-peers` | pick one peer/source (substring match) or analyse all |
| `--start`, `--end` | time window (POSIX seconds or ISO 8601 UTC) |
| `--outliers K` | drop samples beyond K·MAD of the detrended median |
| `--tau0 S` | sample interval of single-column files; also the stability grid |

| Command | Purpose |
|---|---|
| `info` | summary statistics (percentiles, trend, gaps, auxiliary columns) |
| `timeerror` | max\|TE\|, cTE, dTE_L/dTE_H, max\|TEL\|, MTIE/TDEV of dTE_L; `--limits`, `--mask` (exit code 3 on failure), `--input-is-te`, `--units` ([PTP & time error](ptp.md)) |
| `convert` | write a log as a Stable32 phase/frequency file or plain CSV (`--to`, `--no-timetags`) |
| `stability` | ADEV/OADEV/MDEV/TDEV/HDEV/TOTDEV/MTOT/TTOT/Theo1/TheoBR/TheoH/MTIE/TIErms with CIs; `--mask FILE` (exit code 3 on failure), `--exact`, `--raw-mtot`, `--csv`, `--json` |
| `dynamic` | sliding-window stability matrix (time × τ) |
| `network` | delay floor, queueing, asymmetry indicator, floor packet percentage |
| `filter` | Kalman / RTS smoother / min-delay filter, output CSV |
| `compare A B` | error of A against reference B: bias, RMS, TDEV and MTIE of the error |
| `plot` | static report figure (matplotlib) |
| `report` | self-contained HTML report; `--time-error` adds time-error cards and a TE/TEL chart |
| `simulate` | simulate NTP exchanges with ground truth; `--benchmark` |
| `bench` | estimators × scenarios × seeds against ground truth; `--html`, `--csv`, `--list` |
| `query` | one-shot measurement: NTPv4, `--nts`, `--ntpv5`, `--probe-v5`, `-4/-6` |
| `monitor` | periodic SNTP/NTS/NTPv5 measurements to CSV (polite polling); `--metrics-port` serves OpenMetrics ([Monitoring](monitoring.md)) |
| `watch` | sample the local chrony (`chronyc -c tracking`), ntpd (`ntpq -c rv`), ptp4l (`pmc`) or `ptpcheck`; `--metrics-port` as for `monitor` |
| `prom` | fetch a Prometheus range query (ntpd-rs, chrony_exporter, …) to a JSON file every command reads |
| `bounds` | validate clock-error bounds (ClockBound, fbclock, CSV) against a reference; exit code 3 on violations |
| `ui` | start the local web UI |
