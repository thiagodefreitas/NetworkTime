# Contributing

Issues and pull requests are welcome. See [ROADMAP.md](ROADMAP.md) for planned work.

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
  `SPDX-License-Identifier: MIT` / `Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>`.

## Versioning and releases

The project follows [Semantic Versioning](https://semver.org/) and keeps a
[CHANGELOG](CHANGELOG.md). Releases are made from tags:

1. Move the `[Unreleased]` notes into a new `## [X.Y.Z] - YYYY-MM-DD` section.
2. Bump `__version__` in `src/ntpstats/__init__.py` and `version:` in `CITATION.cff`
   (`tests/test_version.py` checks that the three agree), and merge to `master`.
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
