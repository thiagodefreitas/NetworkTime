# conda-forge recipe

`recipe.yaml` packages the PyPI release of ntpstats for conda-forge (a pure-Python, `noarch`
package; numpy is the only runtime dependency, the optional extras stay optional).

## The feedstock

ntpstats is on conda-forge: the recipe was submitted through
[staged-recipes#35041](https://github.com/conda-forge/staged-recipes/pull/35041) and lives in
[conda-forge/ntpstats-feedstock](https://github.com/conda-forge/ntpstats-feedstock), maintained
by [@thiagodefreitas](https://github.com/thiagodefreitas). Install with
`conda install -c conda-forge ntpstats` (or `pixi add ntpstats`, `mamba install ntpstats`).

For every new PyPI release the conda-forge bot (`regro-cf-autotick-bot`) opens a pull request on
the feedstock with the new version and checksum; merging it publishes the package. When the bot is
late, the same two-line change (`version`, `sha256`) can be made by hand on the feedstock; this
file is the reference copy and is kept at the released version by the release process.

## Checking it

The *Conda* workflow builds and tests the recipe with rattler-build whenever this folder changes.
Locally:

```bash
rattler-build build --recipe packaging/conda-forge/recipe.yaml \
    --variant-config packaging/conda-forge/variants.yaml -c conda-forge
```

`variants.yaml` only supplies `python_min`, which conda-forge's global pinning provides there; it
is not part of the submission.

## Updating this copy

On a new release, update `version` and `sha256` (the checksum of the `.tar.gz` on PyPI):

```bash
curl -s https://pypi.org/pypi/ntpstats/X.Y.Z/json | python -c "import sys, json; \
  print([u['digests']['sha256'] for u in json.load(sys.stdin)['urls'] if u['packagetype'] == 'sdist'][0])"
```
