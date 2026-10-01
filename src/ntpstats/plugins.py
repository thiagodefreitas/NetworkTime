# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Plugins: add parsers, estimators, detectors, masks and import profiles from other packages.

A plugin is an installed Python package that declares entry points::

    [project.entry-points."ntpstats.parsers"]
    toycsv = "ntpstats_toy_csv:PARSER"        # a ParserPlugin

    [project.entry-points."ntpstats.estimators"]
    myfilter = "my_pkg:MyEstimator"           # see ntpstats.estimators

    [project.entry-points."ntpstats.detectors"]
    glitch = "my_pkg:DETECTOR"                # a DetectorPlugin

    [project.entry-points."ntpstats.masks"]
    my-tdev = "my_pkg:MASK"                   # mask text, a Mask, or a callable returning one

    [project.entry-points."ntpstats.profiles"]
    my-counter = "my_pkg:PROFILE"             # a profile dict (same keys as TOML profiles)

Plugins appear in ``ntpstats plugins``, in ``-f/--format``, in the web UI's
format list and in ``ntpstats events``. A plugin that fails to load is listed
with its error and otherwise ignored: a broken plugin never breaks the tool.
``pytest --pyargs ntpstats.testing.plugin_contract`` checks installed plugins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .series import TimeSeries

GROUPS = {
    "parsers": "ntpstats.parsers",
    "estimators": "ntpstats.estimators",
    "detectors": "ntpstats.detectors",
    "masks": "ntpstats.masks",
    "profiles": "ntpstats.profiles",
}


@dataclass
class ParserPlugin:
    """A log format.

    ``parse(lines, name)`` returns a list of :class:`TimeSeries` (offset =
    reference - local, seconds; time = POSIX seconds). ``detect(lines)``
    returns a confidence in [0, 1] that the first lines are this format; at
    0.9 or above the plugin wins over the built-in detection, from 0.5 it is
    used before falling back to generic CSV. ``example`` is a short sample
    the contract tests parse.
    """

    name: str
    parse: Callable[[Sequence[str], str], List[TimeSeries]]
    detect: Optional[Callable[[Sequence[str]], float]] = None
    description: str = ""
    example: str = ""
    source: str = "built-in"


@dataclass
class DetectorPlugin:
    """An event detector: ``detect(series)`` returns :class:`ntpstats.events.Event` objects."""

    name: str
    detect: Callable[[TimeSeries], list]
    description: str = ""
    example: Optional[Callable[[], TimeSeries]] = None
    source: str = "built-in"


@dataclass
class Discovery:
    items: Dict[str, Any] = field(default_factory=dict)
    sources: Dict[str, str] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)


_CACHE: Dict[str, Discovery] = {}
_BUILTIN_PARSERS: Dict[str, ParserPlugin] = {}


def register_parser(p: ParserPlugin) -> ParserPlugin:
    """Register a parser in-process (how the built-in research formats are registered)."""
    _BUILTIN_PARSERS[p.name] = p
    return p


def _entry_points(group: str):
    try:
        from importlib.metadata import entry_points

        eps: Any = entry_points()
        return list(eps.select(group=group) if hasattr(eps, "select") else eps.get(group, []))
    except Exception:  # pragma: no cover
        return []


def _dist(ep) -> str:
    d = getattr(ep, "dist", None)
    return f"{d.metadata['Name']} {d.version}" if d is not None else ep.value


def discover(kind: str, refresh: bool = False) -> Discovery:
    """Load the entry points of one group (``parsers``, ``estimators``, ...); cached."""
    if kind not in GROUPS:
        raise ValueError(f"unknown plugin kind {kind!r}; choose from {', '.join(GROUPS)}")
    if kind in _CACHE and not refresh:
        return _CACHE[kind]
    d = Discovery()
    for ep in _entry_points(GROUPS[kind]):
        try:
            obj = ep.load()
            if kind in ("parsers", "detectors") and callable(obj) and not isinstance(obj, (ParserPlugin, DetectorPlugin)):
                obj = obj()
            if kind == "parsers" and not isinstance(obj, ParserPlugin):
                raise TypeError("a parsers entry point must be a ParserPlugin (or a callable returning one)")
            if kind == "detectors" and not isinstance(obj, DetectorPlugin):
                raise TypeError("a detectors entry point must be a DetectorPlugin (or a callable returning one)")
            if kind == "profiles" and not isinstance(obj, dict):
                raise TypeError("a profiles entry point must be a dict")
            if hasattr(obj, "source"):
                obj.source = _dist(ep)
            d.items[ep.name] = obj
            d.sources[ep.name] = _dist(ep)
        except Exception as exc:  # report, never fail
            d.errors[ep.name] = f"{type(exc).__name__}: {exc}"
    _CACHE[kind] = d
    return d


def parsers() -> Dict[str, ParserPlugin]:
    """Built-in parser plugins plus installed ones (installed ones cannot shadow a built-in format)."""
    from . import research  # noqa: F401  (registers the built-in research formats)
    from .parsers import FORMATS

    out = dict(_BUILTIN_PARSERS)
    for name, p in discover("parsers").items.items():
        if name not in FORMATS and name not in out:
            out[name] = p
    return out


def external_parsers() -> Dict[str, ParserPlugin]:
    return {k: v for k, v in parsers().items() if v.source != "built-in"}


def detectors() -> Dict[str, DetectorPlugin]:
    return dict(discover("detectors").items)


def mask(name: str):
    """A mask provided by a plugin, or None."""
    obj = discover("masks").items.get(name)
    if obj is None:
        return None
    from .masks import Mask, load_mask

    obj = obj() if callable(obj) and not isinstance(obj, Mask) else obj
    return obj if isinstance(obj, Mask) else load_mask(str(obj), name=name)


def profile(name: str) -> Optional[Dict[str, Any]]:
    obj = discover("profiles").items.get(name)
    return dict(obj, name=name) if obj is not None else None


def detect_plugin(lines: Sequence[str], threshold: float) -> Optional[str]:
    """Best external parser whose detector scores at least ``threshold``."""
    best, score = None, threshold
    for name, p in external_parsers().items():
        if p.detect is None:
            continue
        try:
            s = float(p.detect(lines))
        except Exception:
            continue
        if s >= score:
            best, score = name, s
    return best


def listing() -> Dict[str, List[Dict[str, str]]]:
    """Everything that can be extended, with where it comes from (for ``ntpstats plugins``)."""
    from . import estimators as est
    from .parsers import format_descriptions
    from .profiles import BUILTIN

    out: Dict[str, List[Dict[str, str]]] = {}
    ext = external_parsers()
    out["parsers"] = [{"name": f, "source": ext[f].source if f in ext else "built-in", "description": d}
                      for f, d in format_descriptions().items()]
    plug = discover("estimators")
    out["estimators"] = [{"name": n, "source": plug.sources.get(n, "built-in"),
                          "description": getattr(e, "description", "") or ""} for n, e in est.available().items()]
    out["detectors"] = [{"name": n, "source": "built-in", "description": ""} for n in
                        ("phase_step", "spike", "frequency_change", "delay_floor_change", "leap_smear")]
    out["detectors"] += [{"name": n, "source": d.source, "description": d.description} for n, d in detectors().items()]
    out["masks"] = [{"name": n, "source": discover("masks").sources[n], "description": ""}
                    for n in discover("masks").items]
    out["profiles"] = [{"name": n, "source": "built-in", "description": p.get("description", "")}
                       for n, p in BUILTIN.items()]
    out["profiles"] += [{"name": n, "source": discover("profiles").sources[n],
                         "description": p.get("description", "")} for n, p in discover("profiles").items.items()]
    errors = [{"name": f"{k}: {n}", "source": "load error", "description": e}
              for k in GROUPS for n, e in discover(k).errors.items()]
    if errors:
        out["errors"] = errors
    return out
