# CLI reference

`ntpstats <command> --help` shows every option. Common input options (`info`, `stability`,
`dynamic`, `plot`, `network`, `filter`, `report`):

| Option | Meaning |
|---|---|
| `-f/--format` | force a format instead of auto-detection |
| `--peer ADDR` / `--all-peers` | pick one peer/source (substring match) or analyse all |
| `--start`, `--end` | time window (POSIX seconds or ISO 8601 UTC) |
| `--outliers K` | drop samples beyond K·MAD of the detrended median |
| `--tau0 S` | sample interval of single-column files; also the stability grid |

| Command | Purpose |
|---|---|
| `info` | summary statistics (percentiles, trend, gaps, auxiliary columns) |
| `stability` | ADEV/OADEV/MDEV/TDEV/HDEV/TOTDEV/MTOT/Theo1/TheoBR/TheoH/MTIE/TIErms with CIs; `--mask FILE` (exit code 3 on failure), `--csv`, `--json` |
| `dynamic` | sliding-window stability matrix (time × τ) |
| `network` | delay floor, queueing, asymmetry indicator, floor packet percentage |
| `filter` | Kalman / RTS smoother / min-delay filter, output CSV |
| `compare A B` | error of A against reference B: bias, RMS, TDEV and MTIE of the error |
| `plot` | static report figure (matplotlib) |
| `report` | self-contained HTML report |
| `simulate` | simulate NTP exchanges with ground truth; `--benchmark` |
| `bench` | estimators × scenarios × seeds against ground truth; `--html`, `--csv`, `--list` |
| `query` | one-shot measurement: NTPv4, `--nts`, `--ntpv5`, `--probe-v5`, `-4/-6` |
| `monitor` | periodic SNTP/NTS/NTPv5 measurements to CSV (polite polling) |
| `watch` | sample the local chrony (`chronyc -c tracking`) or ntpd (`ntpq -c rv`) |
| `ui` | start the local web UI |
