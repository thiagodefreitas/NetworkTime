# Getting started

## Install

```bash
pip install ntpstats                 # core + web UI (numpy only)
pip install "ntpstats[plot]"         # + matplotlib figures
pip install "ntpstats[nts]"          # + NTS client (pyOpenSSL, cryptography)
conda install -c conda-forge ntpstats  # conda-forge (also pixi, mamba)
# development
git clone https://github.com/thiagodefreitas/NetworkTime && cd NetworkTime
pip install -e ".[test,plot,nts,docs]" && pytest
```

Python 3.9 or newer.

## The web UI

```bash
ntpstats ui /var/log/chrony/measurements.log /var/log/ntpstats/peerstats
```

This opens `http://127.0.0.1:8123`: a local page served by the Python standard library with a
bundled chart library (uPlot, about 50 kB). It makes no external requests, needs no build step and
works offline. The left rail has five workspaces:

| Workspace | Pages |
|---|---|
| **Analyze** | overview, offset (Kalman/RTS/min-delay overlays), stability with confidence intervals, masks, noise model and dynamic view, distribution, network (wedge, FPP, one-way delays), spectrum, holdover, events |
| **Compare** | every dataset side by side, a dataset against a reference (PPS, GNSS, a better server), the N-cornered hat |
| **Comply** | time error (TE/TEL, MTIE/TDEV of dTE_L), UTC audit with a verdict and an evidence report |
| **Lab** | simulator presets, the estimator bench (presets or the delays of a loaded dataset), PTP boundary-clock chains against a budget |
| **Live** | SNTP/NTPv5 queries and monitoring, local chrony, ntpd, ptp4l |

Drop files anywhere. The dataset list shows a sparkline of each dataset; tick datasets to overlay
them, double-click a name to rename it. Drag on a time chart to zoom, then *Analyse zoomed range*.
**Ctrl K** opens a command palette for pages, datasets and actions, and every page has its own
address (`#/comply/audit`), so links and the back button work.

| Key | Action |
|---|---|
| `Ctrl K` | command palette |
| `1` … `5` | workspaces |
| `[` `]` | previous / next page |
| `J` `K` | next / previous dataset |
| `/` | filter datasets |
| `O`, `D`, `T`, `?` | open files, datasets panel, theme, shortcuts |

![Audit with verdict and error bound](img/ui-audit.png)

## First analyses

```bash
ntpstats info /var/log/ntpstats/loopstats.20260928          # summary statistics
ntpstats stability /var/log/chrony/tracking.log -k oadev,mdev,tdev --ci 0.95
ntpstats network /var/log/ntpstats/peerstats --peer 192.0.2.10
ntpstats report peerstats --all-peers -o report.html          # offline HTML report
ntpstats query time.cloudflare.com --nts                      # authenticated measurement
ntpstats simulate --preset internet --benchmark               # estimators vs ground truth
```

Sample data for every format is in
[`examples/data`](https://github.com/thiagodefreitas/NetworkTime/tree/master/examples/data).
`python examples/make_example_logs.py` regenerates it.

## Docker

```bash
docker build -t ntpstats .
docker run --rm -p 8123:8123 -v "$PWD:/data" ntpstats ui /data/peerstats --host 0.0.0.0 --no-browser
```

!!! warning
    The UI has no authentication. Only expose it (`--host 0.0.0.0`) on trusted networks.
