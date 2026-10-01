# Writing a plugin

Add support for *your* instrument, daemon or algorithm without forking ntpstats. Ship it as a
small Python package that declares entry points. Once it is installed, ntpstats finds it:

| Entry-point group | Object | Appears in |
|---|---|---|
| `ntpstats.parsers` | `ntpstats.plugins.ParserPlugin` | `-f/--format`, auto-detection, the UI's format list |
| `ntpstats.estimators` | an `ntpstats.estimators.Estimator` (class or instance) | `ntpstats bench` |
| `ntpstats.detectors` | `ntpstats.plugins.DetectorPlugin` | `ntpstats events`, the UI's event list, `audit --events` |
| `ntpstats.masks` | mask text (`tau,tdev` CSV), a `Mask`, or a callable returning one | `--mask NAME` |
| `ntpstats.profiles` | a dict with the keys of a TOML import profile | `-f profile:NAME` |

```bash
ntpstats plugins            # what is installed; exit code 1 if a plugin failed to load
ntpstats plugins --all      # including the built-ins
```

## A parser in 30 lines

```python
# my_pkg/__init__.py
import numpy as np
from ntpstats.plugins import ParserPlugin
from ntpstats.series import TimeSeries

def detect(lines):                      # confidence 0..1 from the first lines
    return 1.0 if lines and lines[0].startswith("#TOYCSV") else 0.0

def parse(lines, name):
    rows = [ln.split(";") for ln in lines[1:] if ln.strip()]
    t = np.array([int(ms) / 1000 for ms, _ in rows])
    x = np.array([-float(us) * 1e-6 for _, us in rows])   # local - reference -> reference - local
    return [TimeSeries(t, x, name=name, source_format="toycsv")]

PARSER = ParserPlugin("toycsv", parse, detect, "Toy CSV dialect", example="#TOYCSV 1\n1790000000000;12.5\n...")
```

```toml
# pyproject.toml
[project.entry-points."ntpstats.parsers"]
toycsv = "my_pkg:PARSER"
```

Rules:
- **Conventions.** Times are POSIX seconds (UTC). Offsets are reference − local, in seconds.
  Extra per-sample columns go in `extra`.
- **Detection.** `detect` scores 0.9 or more only when sure; a plugin that is sure wins over the
  built-in detection. From 0.5 it is tried before the generic CSV fallback. It must never claim
  other formats with certainty.
- **Built-in names.** A plugin cannot replace a built-in format name.
- **Failures.** A plugin that raises while loading is listed by `ntpstats plugins` with its error
  and otherwise ignored.

The built-in research formats (CGGTTS, Circular T, RIPE Atlas, …) are registered as
`ParserPlugin`s too, so the API is used in-house.

## Contract tests

```bash
pip install -e .                                  # your plugin
pytest --pyargs ntpstats.testing.plugin_contract  # ntpstats' checks for every installed plugin
NTPSTATS_PLUGIN=toycsv pytest --pyargs ntpstats.testing.plugin_contract   # only one
```

The suite checks the following:
- the example parses into sorted, finite series;
- detection recognises the example and does not claim unrelated formats;
- `load()` and auto-detection work;
- detectors return `Event`s;
- masks and profiles validate.

Add it to your plugin's CI.

## Template

[`examples/plugins/ntpstats-toy-csv`](https://github.com/thiagodefreitas/NetworkTime/tree/master/examples/plugins/ntpstats-toy-csv)
is a complete plugin with a parser, a detector, a mask and a profile. ntpstats' own CI installs
it and runs the contract suite. Copy it, rename the package and replace the functions. Then share
it, and open an issue so it can be listed here.
