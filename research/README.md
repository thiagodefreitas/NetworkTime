# Research

Papers about ntpstats, with their LaTeX source, the scripts that produce every number and figure,
and the built PDF. They are snapshots: a paper describes the release it names and is not updated with
every version.

| Folder | Paper | Release |
|---|---|---|
| [`preprint-2026/`](preprint-2026/) | *ntpstats: an open toolkit for validating, evaluating and studying network time synchronisation* ([PDF](preprint-2026/ntpstats-preprint-2026.pdf)) | 3.5.0 |
| [`thesis-2012/`](thesis-2012/) | The 2012 undergraduate thesis (UFCG) that started the project, assessed and its experiments re-run ([thesis](https://dspace.sti.ufcg.edu.br/handle/riufcg/18226)) | 3.5.0 |

The short software paper for the Journal of Open Source Software is in [`paper/`](../paper/).

## Rebuilding a paper

```bash
cd research/preprint-2026
pip install ntpstats==3.5.0 matplotlib
make data        # rerun the experiments (about ten minutes) and regenerate data/ and tables/
make             # pdflatex + bibtex -> ntpstats-preprint-2026.pdf
```

`python experiments.py --figures` redraws the figures from `data/` without rerunning the
simulations. The simulations are seeded, so `make data` reproduces the published numbers.
