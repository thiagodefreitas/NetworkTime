# ntpstats-toy-csv: an example plugin

A template for ntpstats plugins: a parser for a toy CSV dialect, an event detector, a mask
and an import profile, declared as entry points in `pyproject.toml`.

```bash
pip install ./examples/plugins/ntpstats-toy-csv
ntpstats plugins                      # toycsv, toy-big-offset, toy-tdev, toy-counter
ntpstats info examples/plugins/ntpstats-toy-csv/sample.toy
ntpstats stability sample.toy -k tdev --mask toy-tdev
pytest --pyargs ntpstats.testing.plugin_contract
```

Copy this directory, rename the package, and replace the functions. See the
[Writing a plugin](https://thiagodefreitas.github.io/NetworkTime/plugins/) docs page.
