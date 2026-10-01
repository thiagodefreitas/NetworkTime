# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""The stable API surface is frozen: changing it must be deliberate.

If a change to ``ntpstats.api`` is intended, regenerate the snapshot with
``NTPSTATS_UPDATE_API=1 pytest tests/test_api.py`` and describe the change in
the CHANGELOG. Removing or renaming a name or a parameter needs a deprecation
period first (``ntpstats.deprecation``); adding is always allowed.
"""

import dataclasses
import inspect
import json
import os

import pytest

from ntpstats import api

SNAPSHOT = os.path.join(os.path.dirname(__file__), "data", "api_surface.json")
DOCS = os.path.join(os.path.dirname(__file__), "..", "docs", "api", "stable.md")


def _params(fn):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    out = []
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        prefix = {"POSITIONAL_ONLY": "pos:", "KEYWORD_ONLY": "kw:", "VAR_POSITIONAL": "*",
                  "VAR_KEYWORD": "**"}.get(p.kind.name, "")
        out.append(prefix + p.name + ("=" if p.default is not inspect.Parameter.empty else ""))
    return out


def _split(p):
    """(name with kind prefix, has default)."""
    return p.rstrip("="), p.endswith("=")


def describe(obj):
    if isinstance(obj, type):
        d = {"kind": "class", "init": _params(obj)}
        if dataclasses.is_dataclass(obj):
            d["fields"] = [f.name for f in dataclasses.fields(obj)]
        d["methods"] = sorted(n for n, v in vars(obj).items()
                              if not n.startswith("_") and (callable(v) or isinstance(v, (property, classmethod,
                                                                                          staticmethod))))
        return d
    if callable(obj):
        return {"kind": "function", "params": _params(obj)}
    return {"kind": "constant", "type": type(obj).__name__}


def surface():
    return {name: dict(describe(getattr(api, name)), home=getattr(getattr(api, name), "__module__", "") or "")
            for name in sorted(api.__all__)}


def test_all_names_exist_and_are_unique():
    assert len(api.__all__) == len(set(api.__all__))
    for name in api.__all__:
        assert hasattr(api, name), name


def test_surface_matches_snapshot():
    now = surface()
    if os.environ.get("NTPSTATS_UPDATE_API"):
        with open(SNAPSHOT, "w") as fh:
            fh.write("{\n" + ",\n".join(f" {json.dumps(k)}: {json.dumps(v, sort_keys=True)}"
                                         for k, v in now.items()) + "\n}\n")
    with open(SNAPSHOT) as fh:
        frozen = json.load(fh)
    removed = sorted(set(frozen) - set(now))
    assert not removed, f"stable names removed without deprecation: {removed}"
    changed = {}
    for name, old in frozen.items():
        new = now[name]
        if old["kind"] != new["kind"]:
            changed[name] = "kind"
            continue
        key = "params" if old["kind"] == "function" else "init"
        if old.get(key) and new.get(key):
            # existing parameters keep their name, order and kind; new ones need a default
            o, n = [_split(p) for p in old[key]], [_split(p) for p in new[key]]
            fixed = [p for p in o if not p[0].startswith("**")]
            for i, (pname, default) in enumerate(fixed):
                if i >= len(n) or n[i][0] != pname or (default and not n[i][1]):
                    changed[name] = f"parameter {pname!r}"
                    break
            if any(p[0].startswith("**") for p in o) and not any(p[0].startswith("**") for p in n):
                changed[name] = "**kwargs removed"
            for pname, default in n[len(fixed):]:
                if not pname.startswith("*") and not default:
                    changed[name] = f"new required parameter {pname!r}"
        for m in old.get("methods", []):
            if m not in new.get("methods", []):
                changed[name] = f"method {m!r} removed"
    assert not changed, f"incompatible changes to the stable API: {changed}"
    added = sorted(set(now) - set(frozen))
    assert not added, f"new stable names {added}: update the snapshot (NTPSTATS_UPDATE_API=1) and the docs"


def test_every_stable_name_is_documented():
    with open(DOCS) as fh:
        text = fh.read()
    missing = [n for n in api.__all__ if f"`{n}`" not in text]
    assert not missing, f"add to docs/api/stable.md: {missing}"


def test_objects_are_the_originals():
    from ntpstats import parsers, series, stability

    assert api.TimeSeries is series.TimeSeries
    assert api.load is parsers.load
    assert api.compute is stability.compute


def test_snapshot_is_detected_as_breaking(monkeypatch):
    """The check itself works: a removed parameter is reported."""

    def compute(x, tau0):  # drops 'kind' and the rest
        return None

    monkeypatch.setattr(api, "compute", compute)
    with pytest.raises(AssertionError, match="compute"):
        test_surface_matches_snapshot()
