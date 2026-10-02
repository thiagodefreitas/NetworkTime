# conda-forge recipe

`recipe.yaml` packages the PyPI release of ntpstats for conda-forge (a pure-Python, `noarch`
package; numpy is the only runtime dependency, the optional extras stay optional).

## First submission

1. Fork [conda-forge/staged-recipes](https://github.com/conda-forge/staged-recipes) and copy this
   file to `recipes/ntpstats/recipe.yaml`.
2. Open a pull request. The bot lints it and builds it on Linux, macOS and Windows; when it is
   merged, conda-forge creates the `ntpstats-feedstock` repository with you as maintainer.
3. From then on the conda-forge bot opens a pull request on the feedstock for every new PyPI
   release (new version and checksum); merging it publishes the package.

Install afterwards with `conda install -c conda-forge ntpstats` (or `pixi add ntpstats`,
`mamba install ntpstats`).

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
