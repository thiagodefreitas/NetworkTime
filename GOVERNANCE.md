# Governance

ntpstats is a small project with one maintainer. This note says how decisions are made today and
how that is meant to change as more people contribute.

## Roles

- **Maintainer:** [@thiagodefreitas](https://github.com/thiagodefreitas), who started the project in
  2012 and leads it. The maintainer reviews and merges contributions, cuts releases, and decides
  when a discussion does not reach agreement.
- **Contributors:** anyone who opens an issue, shares a sample log or a validation result, improves
  the documentation, or sends a pull request. Data contributions count as much as code.

## How decisions are made

- **Day-to-day changes** (fixes, parsers, docs, tests) are decided in the pull request that makes
  them.
- **Larger changes** (a new module, a change to how a statistic is computed, anything that touches
  the stable API) start as an issue or a Discussion, so the reasoning is public before the code is
  written. Numerical changes need a reference: a published table, a cited paper, or a comparison
  with an independent implementation ([validation](docs/validation.md)).
- **The stable API** follows the [deprecation policy](CONTRIBUTING.md): a stable name changes only
  after a full minor release with a deprecation warning, and the 3.x series has no breaking changes.
- **The roadmap** ([ROADMAP.md](ROADMAP.md)) records the priorities and how they are set; anyone can
  propose changes to it in an issue.

## Releases

Releases follow semantic versioning and are made from `master` by the release workflow: a tag, a
GitHub release with the changelog section, the PyPI upload, the container image, the Zenodo
archive and, through its bot, the conda-forge package.

## Becoming a maintainer

A contributor who has made several substantial, reviewed contributions and knows the validation
standards of the project can be invited as a co-maintainer, with merge rights. As soon as there are
two or more maintainers, larger changes need the agreement of a second maintainer, and this note will
be updated to say how disagreements are settled.

## Conduct and security

Everyone in the project's spaces follows the [code of conduct](CODE_OF_CONDUCT.md). Security
problems are reported privately as described in [SECURITY.md](SECURITY.md).
