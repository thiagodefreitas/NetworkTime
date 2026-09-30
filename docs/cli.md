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
| `stability` | ADEV/OADEV/MDEV/TDEV/HDEV/TOTDEV/MTOT/TTOT/HTOT/Theo1/TheoBR/TheoH/MTIE/TIErms with CIs; `--mask FILE` (exit code 3 on failure), `--exact`, `--raw-mtot`, `--csv`, `--json` |
| `dynamic` | sliding-window stability matrix (time × τ) |
| `network` | delay floor, queueing, asymmetry indicator, floor packet percentage |
| `filter` | Kalman / RTS smoother / min-delay filter, output CSV |
| `compare A B` | error of A against reference B: bias, RMS, TDEV and MTIE of the error |
| `plot` | static report figure (matplotlib) |
| `report` | self-contained HTML report; `--time-error` adds time-error cards and a TE/TEL chart |
| `simulate` | simulate NTP exchanges with ground truth; `--benchmark` |
| `bench` | estimators × scenarios × seeds against ground truth; `--html`, `--csv`, `--list` |
| `query` | one-shot measurement: NTPv4, `--nts`, `--pool N` (NTS pool), `--interleaved` (RFC 9769), `--ntpv5`, `--probe-v5`, `-4/-6` ([Protocols](protocols.md)) |
| `roughtime` | signed coarse time from several Roughtime servers, chained nonces, causal check; `--report` writes a malfeasance report, `--verify-report`, `--check-local`; exit code 3 on malfeasance |
| `monitor` | periodic SNTP/NTS/NTPv5 measurements to CSV (polite polling); `--metrics-port` serves OpenMetrics, `--otlp` pushes to OpenTelemetry ([Monitoring](monitoring.md)) |
| `watch` | sample the local chrony (`chronyc -c tracking`), ntpd (`ntpq -c rv`), ptp4l (`pmc`) or `ptpcheck`; `--metrics-port` as for `monitor` |
| `audit` | UTC traceability evidence: per-sample error bound with stated assumptions, windows, coverage; HTML/JSON with input hashes; exit code 3 on failure ([Assurance](assurance.md)) |
| `events` | phase steps, spikes, frequency changes, delay-floor (route) changes and leap smears |
| `prom` | fetch a Prometheus range query (ntpd-rs, chrony_exporter, …) to a JSON file every command reads |
| `noise` | fit h_α (white/flicker PM, white/flicker/random-walk FM, optional drift) with bootstrap intervals and corner τ; `--scenario` writes a simulator clock ([Metrology](metrology.md)) |
| `spectrum` (`psd`) | phase or frequency PSD (Welch or sine multitaper, gap-aware, log bins), `--carrier` for L(f) |
| `hat` | individual stability of 3+ sources from their differences: Groslambert covariance, three- or N-cornered hat |
| `holdover` | predicted TIE after loss of reference, time to violate `--limit`s, `--backtest` calibration, `--min-holdover` (exit code 3) |
| `dataset` | summary of the open interop dataset (`data/interop/`): availability, median offset and delay, protocol support per server |
| `cv` | GNSS time transfer between two CGGTTS files: common view or all in view ([Research data](research-data.md)) |
| `bounds` | validate clock-error bounds (ClockBound, fbclock, CSV) against a reference; exit code 3 on violations |
| `ui` | start the local web UI |
