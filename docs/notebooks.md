# Notebooks and reproduction gallery

Runnable notebooks in
[`examples/notebooks`](https://github.com/thiagodefreitas/NetworkTime/tree/master/examples/notebooks).
CI executes every one of them on each change, so they always work with the current release. They
use the [stable API](api/stable.md) (`from ntpstats import api as nt`) and the sample data in
`examples/data`; change one path to run them on your own logs.

```bash
pip install "ntpstats[plot,data]" jupyterlab
git clone https://github.com/thiagodefreitas/NetworkTime && cd NetworkTime/examples/notebooks
jupyter lab
```

| Notebook | For | What it shows |
|---|---|---|
| [From a chrony log to stability and a noise model](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/notebooks/01-chrony-stability-noise.ipynb) | operators, metrologists | load → summary → ADEV/MDEV/TDEV with 95 % intervals and noise ID → power-law noise fit → a simulator clock with the same noise → pandas |
| [Benchmark your own synchronisation algorithm](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/notebooks/02-bench-custom-estimator.ipynb) | researchers | a new estimator in a few lines, scored against the reference algorithms on simulated paths with ground truth |
| [Compliance evidence](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/notebooks/03-compliance-report.ipynb) | regulated users, telecom | PTP time error from a capture against limits, a UTC error bound with its assumptions, a TDEV mask, an archivable HTML report |
| [Reproducing NIST SP 1065](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/notebooks/04-nist-sp1065-reproduction.ipynb) | everyone who needs to trust the numbers | the handbook's test suites (Tables 30 and 31) regenerated and compared with the printed values: agreement to all 7 digits |

## Contributing a gallery entry

The gallery collects examples that reproduce a published figure or number with ntpstats: from a
standard, a paper or a public dataset. These examples are what lets people trust and reuse the
tool. A good entry:

- cites its source (document, table or figure) in the first cell;
- uses only openly licensed data, either small enough to commit or downloaded from a stable URL
  (CI runs without credentials);
- compares the result with the published value and says how close it is, and why if it differs;
- runs in under a minute: `pytest --nbmake examples/notebooks/your-notebook.ipynb`.

Commit notebooks without outputs (the docs link to them on GitHub, which renders them). Ideas are
tracked in [#38](https://github.com/thiagodefreitas/NetworkTime/issues/38): an NTP Pool offset
distribution from public data, chrony against ntpd-rs on the same path, and a PTP boundary-clock
chain against a time-error budget.
