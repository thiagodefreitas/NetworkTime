# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Run an ntpstats check and write a Markdown summary for GitHub Actions.

    python summary.py COMMAND ARGS...

Runs ``ntpstats COMMAND ARGS... --json``, prints the JSON, appends a table to
``$GITHUB_STEP_SUMMARY`` (if set), writes ``result=pass|fail`` to
``$GITHUB_OUTPUT`` (if set) and exits with ntpstats' exit code (3 = a check
failed).
"""

import json
import os
import subprocess
import sys

CHECKS = ("stability", "timeerror", "audit", "bounds", "events")


def fmt(v):
    if v is None:
        return "–"
    from ntpstats.analysis import format_seconds

    return format_seconds(float(v))


def render(cmd, doc):
    lines = []
    if cmd == "audit":
        lines += ["| source | result | max bound | p99 | coverage | failing windows |", "|---|---|---|---|---|---|"]
        for r in doc["audit"]:
            s = r["summary"]
            lines.append(f"| {r['name']} | {'✅ pass' if s['passed'] else '❌ fail'} | {fmt(s['max_bound'])} | "
                         f"{fmt(s['p99_bound'])} | {s['coverage']:.1%} | {s['failing_windows']}/{s['windows']} |")
    elif cmd == "timeerror":
        lines += ["| source | result | max\\|TE\\| | cTE | max\\|TEL\\| | dTE_H p-p |", "|---|---|---|---|---|---|"]
        for r in doc:
            p = r["check"]["passed"]
            res = "–" if p is None else ("✅ pass" if p else "❌ fail")
            lines.append(f"| {r['name']} | {res} | {fmt(r['max_abs_te'])} | {fmt(r['cte'])} | "
                         f"{fmt(r['max_abs_tel'])} | {fmt(r['dte_h_pp'])} |")
    elif cmd == "bounds":
        lines += ["| compared | inside | violated | indeterminate | violation rate | worst excess |", "|---|---|---|---|---|---|"]
        lines.append(f"| {doc['compared']} | {doc['inside']} | {doc['violations']} | {doc['indeterminate']} | "
                     f"{doc['violation_rate']:.3%} | {fmt(doc['worst_excess'])} |")
    elif cmd == "events":
        lines += ["| source | events |", "|---|---|"]
        for r in doc:
            lines.append(f"| {r['name']} | {', '.join(f'{k}: {v}' for k, v in r['summary'].items()) or 'none'} |")
    elif cmd == "stability":
        lines += ["| source | statistic | mask | result |", "|---|---|---|---|"]
        for r in doc:
            for res in r["results"]:
                m = res.get("mask") or {}
                p = m.get("passed")
                lines.append(f"| {r['name']} | {res['kind'].upper()} | {m.get('mask', '–')} | "
                             f"{'–' if p is None else ('✅ pass' if p else '❌ fail')} |")
    return "\n".join(lines)


def main(argv):
    if len(argv) < 2 or argv[0] not in CHECKS:
        print(f"usage: summary.py {{{','.join(CHECKS)}}} ARGS...", file=sys.stderr)
        return 2
    cmd, args = argv[0], argv[1:]
    proc = subprocess.run([sys.executable, "-m", "ntpstats", cmd, *args, "--json"], capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    print(proc.stdout)
    rc = proc.returncode
    try:
        table = render(cmd, json.loads(proc.stdout))
    except (ValueError, KeyError, TypeError) as exc:
        table = f"(could not summarise the output: {exc})"
    verdict = "pass" if rc == 0 else "fail"
    title = f"### ntpstats {cmd}: {'✅ pass' if rc == 0 else '❌ fail (exit code %d)' % rc}"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"{title}\n\n`ntpstats {cmd} {' '.join(args)}`\n\n{table}\n\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"result={verdict}\n")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
