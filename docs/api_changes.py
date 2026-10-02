#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""List the changes to the stable API (``ntpstats.api``) between two versions.

Reads the frozen surface ``tests/data/api_surface.json`` at a git tag and in the working tree:

    python docs/api_changes.py v2.15.0          # Markdown for the changelog
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = "tests/data/api_surface.json"


def at(ref):
    text = subprocess.run(["git", "show", f"{ref}:{SNAPSHOT}"], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout
    return json.loads(text)


def changes(old, new):
    out = {"added": [], "removed": [], "changed": []}
    for name in sorted(set(new) - set(old)):
        out["added"].append(f"`{name}` ({new[name]['kind']}, from `{new[name]['home']}`)")
    for name in sorted(set(old) - set(new)):
        out["removed"].append(f"`{name}`")
    for name in sorted(set(old) & set(new)):
        o, n, notes = old[name], new[name], []
        for key in ("params", "init", "fields", "methods"):
            a, b = o.get(key) or [], n.get(key) or []
            plus = [x for x in b if x not in a]
            minus = [x for x in a if x not in b]
            if plus:
                notes.append(f"new {key} {', '.join(f'`{x}`' for x in plus)}")
            if minus:
                notes.append(f"{key} no longer listed: {', '.join(f'`{x}`' for x in minus)}")
        if notes:
            out["changed"].append(f"`{name}`: " + "; ".join(notes))
    return out


def main(ref):
    c = changes(at(ref), json.load(open(os.path.join(ROOT, SNAPSHOT))))
    print(f"Stable API changes since {ref}:\n")
    for kind in ("added", "changed", "removed"):
        if c[kind]:
            print(f"- **{kind.capitalize()}**: " + "; ".join(c[kind]) + ".")
    if not c["removed"]:
        print("- **Removed**: nothing. Code written against the stable API of an earlier release keeps working.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v2.15.0")
