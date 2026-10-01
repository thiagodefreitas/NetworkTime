# Contributing

Issues and pull requests are welcome, from industry and research alike. See
[ROADMAP.md](ROADMAP.md) for planned work and the [Code of Conduct](CODE_OF_CONDUCT.md) for how we
work together. Report security issues privately ([SECURITY.md](SECURITY.md)).

## Ways to contribute

- **Share data.** A small, anonymised sample log or instrument export is the fastest way to get
  a format supported (use the "Share a sample log" issue form). Stable32 outputs for
  cross-checks are equally welcome.
- **Pick a starter issue.** Issues labelled
  [`good first issue`](https://github.com/thiagodefreitas/NetworkTime/labels/good%20first%20issue)
  are self-contained, often a parser or a file format.
- **Tell us your use case.** Industry (`industry`) and research (`research`) needs shape the
  roadmap; comment on the issues you care about.
- **Reproduce a published result.** Scripts or notebooks that reproduce figures from standards
  or papers with ntpstats are welcome in `examples/`.
- **Ask and show** in [Discussions](https://github.com/thiagodefreitas/NetworkTime/discussions).

## Development

```bash
pip install -e ".[test,plot,nts,docs]"
pytest -q && ruff check src tests examples docs && mypy src/ntpstats
mkdocs serve                    # docs at http://127.0.0.1:8000
ntpstats ui --no-browser        # UI at http://127.0.0.1:8123
python docs/make_screenshots.py # optional, needs `pip install playwright`
```

Guidelines:

- Keep the runtime dependency set to **numpy only**; anything else goes behind an optional
  extra.
- New statistics need tests against a literal implementation of the published formula and,
  where one exists, an analytic result.
- New parsers need a test with lines copied from the implementation's documentation or real
  logs (anonymise addresses using RFC 5737 ranges).
- The web UI is plain JavaScript with no build step. Keep it that way.
- New files carry the SPDX header:
  `SPDX-License-Identifier: MIT` / `Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)`.

## Stable API and deprecations

`ntpstats.api` lists the stable names ([docs](https://thiagodefreitas.github.io/NetworkTime/api/stable/)).
`tests/test_api.py` freezes them in `tests/data/api_surface.json`:

- **Adding** a name, an optional parameter, a field or a method is always fine. Add it to
  `ntpstats.api.__all__` and `docs/api/stable.md`, then regenerate the snapshot with
  `NTPSTATS_UPDATE_API=1 pytest tests/test_api.py`.
- **Removing or renaming** a stable name or parameter needs one full minor release of warnings
  first. Use `ntpstats.deprecation` (`@deprecated`, `@renamed_parameter`, `moved` for a module
  `__getattr__`), name the release that removes it (at least two minor releases later), and list
  it under *Deprecated* in the changelog. The removal itself goes under *Removed*.
- The test suite turns `NtpstatsDeprecationWarning` into an error, so the code base never uses
  its own deprecated names; tests that check a warning catch it with `pytest.warns`.

## Versioning and releases

The project follows [Semantic Versioning](https://semver.org/) and keeps a
[CHANGELOG](CHANGELOG.md). Releases are made from tags:

1. Move the `[Unreleased]` notes into a new `## [X.Y.Z] - YYYY-MM-DD` section.
2. Bump `__version__` in `src/ntpstats/__init__.py` and `version:` in `CITATION.cff`
   (`tests/test_version.py` checks that the three agree), and merge to `master`.
   The release also pushes the container image to `ghcr.io/thiagodefreitas/ntpstats`.
3. Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`, or run *Actions → Release →
   Run workflow* with `tag = vX.Y.Z`, which creates the tag at the selected commit.

The **Release** workflow refuses tags that do not match `__version__` or lack a CHANGELOG section.
It then runs the tests, builds and checks the sdist and wheel, publishes a GitHub Release with the
changelog notes, and uploads to **PyPI** through trusted publishing. One-time setup: create a
`pypi` environment in the repository settings, and add a (pending) trusted publisher on pypi.org
for project `ntpstats`, workflow `release.yml`, environment `pypi`.

## Documentation and wiki

- `docs/` is the single source. `mkdocs build --strict` must pass (CI checks it on every PR).
  The *Docs* workflow deploys the site to the `gh-pages` branch from `master`; in *Settings →
  Pages*, select "Deploy from a branch: gh-pages".
- The GitHub wiki is **generated** from `docs/`, `CHANGELOG.md` and `ROADMAP.md` by
  `docs/sync_wiki.py` (the *Wiki* workflow). Edit the repository files, not the wiki.
