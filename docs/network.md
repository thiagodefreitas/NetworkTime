# Network metrics and estimators

## Network metrics

For a single exchange, the offset error is bounded by half the queueing delay, so samples near
the **delay floor** are the most trustworthy.

- `delay_stats`: floor, median and p95 delay, fraction of packets near the floor, offset
  spread overall and for floor packets, and an **asymmetry indicator**.
- **Wedge** plot: offset against queueing delay, with the ±q/2 bound.
- **Floor packet percentage** (ITU-T G.8260 style): percentage of packets within a cluster width
  of the floor, per window.

Offsets are linearly detrended before these statistics, because a frequency offset would
otherwise dominate them.

## Estimators

| Name | Algorithm |
|---|---|
| `raw` | the measurements |
| `kalman`, `kalman-dw` | two-state Kalman filter; `-dw` weights samples by queueing delay |
| `rts-dw` | Rauch–Tung–Striebel smoother (offline optimum of the model) |
| `mindelay` | NTP clock filter: minimum delay of the last 8 samples (RFC 5905 §10) |
| `regression` | chrony-style weighted regression, window sized by a runs test |
| `feedforward` | RADclock-style: rate from low-RTT packets over a long baseline |
| `rfc5905` | multi-server: clock filter + intersection, cluster and combine (RFC 5905 §11) |
| `median` | multi-server median of clock-filter outputs |

Add your own by subclassing `ntpstats.estimators.Estimator` and calling `register()`, or
publish it through the `ntpstats.estimators` entry-point group
(see `examples/04_custom_estimator.py`).

## Research bench

```bash
ntpstats bench internet falseticker examples/scenarios/*.toml --seeds 1-10 --html bench.html
```

Scenarios are presets (`lan`, `internet`, `congested`, `route-change`, `falseticker`) or
TOML/JSON files. They describe the clock (frequency offset, drift, white/flicker/random-walk
noise, temperature cycle), per-server forward and backward paths with events (route change,
congestion, outage), and falsetickers or stepping servers. Metrics are computed on
estimate − truth after a 30-minute warm-up: RMS, bias, p95, max, MTIE over 1 h, and runtime.

Findings the bench makes visible:

- Delay-aware estimators cut WAN errors by 10–30× compared with raw measurements.
- A one-way route change biases every estimator by half the step: asymmetry cannot be observed.
- RFC 5905 selection rejects falsetickers only when their error exceeds the root distance.
