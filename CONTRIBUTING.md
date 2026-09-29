# Contributing

Issues and pull requests are welcome. See [ROADMAP.md](ROADMAP.md) for planned work.

```bash
pip install -e ".[test,plot]"
pytest -q
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
