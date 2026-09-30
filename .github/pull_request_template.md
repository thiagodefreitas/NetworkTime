## What and why

<!-- One or two sentences, and the issue it addresses (e.g. "Closes #33"). -->

## How it was checked

<!-- Tests added or updated; for statistics, the reference used (formula, published value,
     analytic result); for parsers, where the sample lines come from. -->

## Checklist

- [ ] `pytest -q`, `ruff check src tests examples docs` and `mypy src/ntpstats` pass
- [ ] New files carry the SPDX header
- [ ] User-visible changes are in `CHANGELOG.md` under `[Unreleased]`
- [ ] Docs updated if behaviour or options changed (`mkdocs build --strict` passes)
