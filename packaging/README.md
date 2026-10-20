# Packaging ntpstats

Where ntpstats is published, and notes for anyone packaging it for a distribution.

| Channel | How it is published | Install |
|---|---|---|
| PyPI | release workflow, trusted publishing | `pip install ntpstats` |
| conda-forge | [ntpstats-feedstock](https://github.com/conda-forge/ntpstats-feedstock); the conda-forge bot opens a version-bump pull request for each PyPI release ([conda-forge/](conda-forge/)) | `conda install -c conda-forge ntpstats` |
| Container | release workflow, `ghcr.io/thiagodefreitas/ntpstats:X.Y.Z` and `:latest` | `docker run --rm ghcr.io/thiagodefreitas/ntpstats --help` |
| Zenodo | every GitHub release is archived with the interop dataset | DOI [10.5281/zenodo.23070521](https://doi.org/10.5281/zenodo.23070521) |

## Notes for distribution packagers (Debian, Fedora, Homebrew and others)

The package is meant to be easy to package. What you need to know:

- **Pure Python, architecture independent.** No compiled code. Builds with any PEP 517 front end
  from the sdist on PyPI (`python -m build` or `pip wheel`); the build backend is setuptools 77 or
  later (`pyproject.toml`).
- **One runtime dependency:** NumPy 1.22 or later. Python 3.9 or later.
- **Optional extras** (only for the features that need them):
  - `plot`: matplotlib (figures);
  - `nts`: pyOpenSSL and cryptography (NTS client, Roughtime signatures);
  - `data`: pandas, pyarrow, xarray (data-frame and Parquet adapters);
  - `toml`: tomli on Python older than 3.11 (scenario files, import profiles).
  A distribution package can depend on NumPy only and recommend or suggest the others.
- **Entry points:** the `ntpstats` command (`ntpstats.cli:main`) and a pytest plugin
  (`pytest11` entry point `ntpstats = ntpstats.testing`) that provides time-error and stability
  assertions. If your distribution splits pytest plugins, the plugin is harmless when pytest is
  absent; it is loaded only by pytest.
- **Package data:** the web interface in `ntpstats/web/static/` and one bundled third-party
  library, uPlot 1.6.32 (MIT, `ntpstats/web/vendor/`, licence file included). Distributions that
  unbundle JavaScript can replace it with their own uPlot of the same major version.
- **Licence:** MIT for the package (`LICENSE`, `NOTICE`). The 2012 prototype under `legacy/` is GPL
  and is not in the sdist or the wheel; it is kept in the repository for history only.
- **Tests:** about 600, run offline in about a minute with `pytest` from the unpacked sdist or a
  checkout, after installing the `test` extra. The sdist carries the test data and example files
  they read (`MANIFEST.in`) from the release after 3.7.0; CI runs the suite from the built sdist on every push.
  Tests that need an optional extra are skipped when it is missing. None needs network access.
- **Reproducibility:** the version is single-sourced in `ntpstats/__init__.py`; no build-time
  network access or code generation.

If you package ntpstats for a distribution, please open an issue or a Discussion so it can be
listed here.
