# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Research and time-laboratory data: CGGTTS, RINEX clock, BIPM Circular T, RIPE Atlas, NTP Pool.

* **CGGTTS** (BIPM/CCTF generic GNSS time-transfer format, V2E): one line per
  satellite track. REFSYS (reference − GNSS system time, 0.1 ns) is averaged
  per epoch into a series; line checksums are verified. :func:`common_view`
  differences two stations, satellite by satellite (common view) or epoch by
  epoch (all in view), giving UTC(A) − UTC(B).
* **RINEX clock** (IGS ``.clk``, 3.0x): one series per receiver (AR) or
  satellite (AS) clock bias, in seconds against the file's time scale.
* **BIPM Circular T**, section 1: ``UTC − UTC(k)`` per laboratory every five
  days. Concatenate several issues into one file for a long series.
* **RIPE Atlas** NTP results (JSON from the public API): one series per
  probe and server. Atlas reports offsets as local − server; they are
  negated to the ntpstats convention (server − local).
* **NTP Pool** score logs (``/scores/<ip>/log?monitor=*`` CSV): one series per
  monitor, with round-trip time and score.
"""

from __future__ import annotations

import calendar
import json
import math
import re
from collections import OrderedDict, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .series import TimeSeries

MJD_UNIX = 40587
NTP_UNIX = 2208988800


class ResearchFormatError(ValueError):
    pass


def _mjd_to_unix(mjd: Any) -> Any:
    return (mjd - MJD_UNIX) * 86400.0


def _series(t, v, name, fmt, extra=None, meta=None) -> TimeSeries:
    if not len(t):
        raise ResearchFormatError(f"no usable samples for format {fmt}")
    return TimeSeries(np.asarray(t, dtype=float), np.asarray(v, dtype=float), name=name, source_format=fmt,
                      extra={k: np.asarray(x, dtype=float) for k, x in (extra or {}).items()},
                      meta=meta or {}).sorted()


# ------------------------------------------------------------------ CGGTTS
def cggtts_tracks(lines: Sequence[str]) -> Dict[str, Any]:
    """Header fields and one record per track (dict of columns) of a CGGTTS file.

    Several files concatenated together (as in the BIPM archives) are accepted.
    """
    header: Dict[str, str] = {}
    cols: List[str] = []
    rows: List[List[str]] = []
    bad = 0
    for ln in lines:
        s = ln.rstrip("\r\n")
        if not s.strip():
            continue
        if s.startswith("SAT CL") or s.startswith("PRN CL"):
            cols = s.split()
            continue
        if not cols:
            m = re.match(r"^\s*([A-Z][A-Z0-9 _]*?)\s*=\s*(.*)$", s)
            if m:
                header.setdefault(m.group(1).strip(), m.group(2).strip())
            elif s.startswith("CGGTTS"):
                header.setdefault("FORMAT", s.strip())
            continue
        tok = s.split()
        if not tok or not re.fullmatch(r"[A-Z]?\d{1,3}", tok[0]):
            if re.match(r"^\s*([A-Z][A-Z0-9 _]*?)\s*=", s):  # a new header (concatenated files)
                cols = []
                m = re.match(r"^\s*([A-Z][A-Z0-9 _]*?)\s*=\s*(.*)$", s)
                if m:
                    header.setdefault(m.group(1).strip(), m.group(2).strip())
            continue
        if len(tok) != len(cols):
            continue
        body = s.rstrip()
        try:  # the last field is the line checksum: sum of the preceding characters mod 256, in hex
            if int(tok[-1], 16) != sum(map(ord, body[: -len(tok[-1])])) % 256:
                bad += 1
                continue
        except ValueError:
            pass
        rows.append(tok)
    if not rows:
        raise ResearchFormatError("no CGGTTS tracks found")
    table = {c: [r[i] for r in rows] for i, c in enumerate(cols)}
    return {"header": header, "columns": cols, "tracks": table, "bad_checksums": bad}


def _track_arrays(tr: Dict[str, Any]):
    t: Dict[str, List[str]] = tr["tracks"]
    mjd = np.array(t["MJD"], dtype=float)
    st = t["STTIME"]
    sec = np.array([int(x[:2]) * 3600 + int(x[2:4]) * 60 + int(x[4:6]) for x in st], dtype=float)
    trkl = np.array(t.get("TRKL", ["780"] * len(st)), dtype=float)
    mid = _mjd_to_unix(mjd) + sec + trkl / 2  # REFSV/REFSYS refer to the middle of the track
    sats = np.array(t["SAT"] if "SAT" in t else t["PRN"])
    refsys = np.array(t["REFSYS"], dtype=float) * 1e-10
    refsv = np.array(t["REFSV"], dtype=float) * 1e-10
    return mid, sats, refsys, refsv


def parse_cggtts(lines: Sequence[str], name: str = "cggtts") -> List[TimeSeries]:
    """REFSYS (reference − GNSS time) averaged over the satellites of each epoch."""
    tr = cggtts_tracks(lines)
    mid, sats, refsys, _ = _track_arrays(tr)
    epochs, inv = np.unique(mid, return_inverse=True)
    n = np.bincount(inv)
    mean = np.bincount(inv, refsys) / n
    sq = np.bincount(inv, refsys ** 2) / n
    std = np.sqrt(np.maximum(sq - mean ** 2, 0.0))
    hdr: Dict[str, str] = tr["header"]
    lab = hdr.get("LAB", "")
    systems = sorted({s[0] for s in sats if s and s[0].isalpha()})
    return [_series(epochs, mean, f"{name} [{lab} REFSYS {''.join(systems)}]".replace("  ", " "), "cggtts",
                    extra={"satellites": n, "refsys_std": std},
                    meta={"peer": lab, "lab": lab, "receiver": hdr.get("RCVR", ""), "reference": hdr.get("REF", ""),
                          "quantity": "REF - GNSS system time", "bad_checksums": tr["bad_checksums"],
                          "note": "one sample per CGGTTS epoch (track midpoint), mean of all satellites"})]


def common_view(a_lines: Sequence[str], b_lines: Sequence[str], mode: str = "cv", min_sats: int = 1,
                name: Optional[str] = None) -> TimeSeries:
    """REF(A) − REF(B) from two CGGTTS files.

    ``mode="cv"``: common view, REFSV differences of the same satellite at the
    same epoch, averaged per epoch (satellite clock errors cancel).
    ``mode="aiv"``: all in view, difference of the per-epoch REFSYS means
    (needs no common satellites; relies on precise orbits and clocks).
    """
    ta, tb = cggtts_tracks(a_lines), cggtts_tracks(b_lines)
    ma, sa, ysa, vsa = _track_arrays(ta)
    mb, sb, ysb, vsb = _track_arrays(tb)
    la = ta["header"].get("LAB", "A")
    lb = tb["header"].get("LAB", "B")
    rows: Dict[float, List[float]] = defaultdict(list)
    if mode == "cv":
        idx = {(round(t, 1), s): v for t, s, v in zip(mb, sb, vsb)}
        for t, s, v in zip(ma, sa, vsa):
            w = idx.get((round(t, 1), s))
            if w is not None:
                rows[t].append(v - w)
    elif mode == "aiv":
        ea: Dict[float, List[float]] = defaultdict(list)
        eb: Dict[float, List[float]] = defaultdict(list)
        for t, v in zip(ma, ysa):
            ea[round(t, 1)].append(v)
        for t, v in zip(mb, ysb):
            eb[round(t, 1)].append(v)
        for t in ea.keys() & eb.keys():
            rows[t] = [float(np.mean(ea[t]) - np.mean(eb[t]))] * min(len(ea[t]), len(eb[t]))
    else:
        raise ValueError("mode must be 'cv' or 'aiv'")
    keep = sorted(t for t, v in rows.items() if len(v) >= min_sats)
    if not keep:
        raise ResearchFormatError("no common epochs between the two files")
    t = np.array(keep)
    v = np.array([np.mean(rows[k]) for k in keep])
    n = np.array([len(rows[k]) for k in keep], dtype=float)
    return _series(t, v, name or f"{la} - {lb} ({mode.upper()})", "cggtts", extra={"satellites": n},
                   meta={"peer": f"{la}-{lb}", "quantity": f"REF({la}) - REF({lb})", "mode": mode})


# ------------------------------------------------------------------ RINEX clock
def parse_rinex_clock(lines: Sequence[str], name: str = "rinex-clock", types: Iterable[str] = ("AR", "AS"),
                      clocks: Optional[Iterable[str]] = None) -> List[TimeSeries]:
    """Clock bias series from a RINEX clock file (one per receiver/satellite)."""
    want_t = set(types)
    want_c = set(clocks) if clocks else None
    in_hdr, tscale = True, "GPS"
    data: "OrderedDict[str, List[Tuple[float, float, float]]]" = OrderedDict()
    for ln in lines:
        if in_hdr:
            if "TIME SYSTEM ID" in ln[60:]:
                tscale = ln[:60].strip() or tscale
            if "END OF HEADER" in ln[60:]:
                in_hdr = False
            continue
        tok = ln.split()
        if len(tok) < 10 or tok[0] not in want_t:
            continue
        clk = tok[1]
        if want_c is not None and clk not in want_c:
            continue
        try:
            y, mo, d, h, mi = (int(x) for x in tok[2:7])
            sec = float(tok[7])
            bias = float(tok[9].replace("D", "E"))
            sig = float(tok[10].replace("D", "E")) if len(tok) > 10 else float("nan")
        except ValueError:
            continue
        t = calendar.timegm((y, mo, d, h, mi, 0)) + sec
        data.setdefault(f"{tok[0]} {clk}", []).append((t, bias, sig))
    if in_hdr:
        raise ResearchFormatError("RINEX clock: END OF HEADER not found")
    out = []
    for key, rows in data.items():
        a = np.array(rows)
        kind, clk = key.split(" ", 1)
        out.append(_series(a[:, 0], a[:, 1], f"{name} [{clk}]", "rinex-clock", extra={"sigma": a[:, 2]},
                           meta={"peer": clk, "clock_type": "receiver" if kind == "AR" else "satellite",
                                 "time_scale": tscale, "quantity": f"clock - {tscale} reference",
                                 "note": "epochs are in the file's time scale (no leap-second correction)"}))
    if not out:
        raise ResearchFormatError("RINEX clock: no clock records")
    return out


# ------------------------------------------------------------------ BIPM Circular T
_CIRT_LAB = re.compile(r"^([A-Z][A-Z0-9]{0,5})\s+\(([^)]*)\)\s+(.*)$")


def parse_circular_t(lines: Sequence[str], name: str = "circular-t", labs: Optional[Iterable[str]] = None
                     ) -> List[TimeSeries]:
    """UTC − UTC(k) per laboratory from section 1 of one or more concatenated Circular T issues."""
    want = set(labs) if labs else None
    data: Dict[str, Dict[int, float]] = defaultdict(dict)
    unc: Dict[str, Tuple[float, float, float]] = {}
    city: Dict[str, str] = {}
    mjds: List[int] = []
    in_s1 = False
    issues = 0
    for ln in lines:
        s = ln.rstrip()
        if re.match(r"^1 - ", s):
            in_s1, mjds = True, []
            issues += 1
            continue
        if re.match(r"^[2-9] - ", s):
            in_s1 = False
            continue
        if not in_s1:
            continue
        if s.strip().startswith("MJD"):
            mjds = [int(x) for x in s.split()[1:] if re.fullmatch(r"\d{5}", x)]
            continue
        m = _CIRT_LAB.match(s)
        if not m or not mjds:
            continue
        lab = m.group(1)
        if want is not None and lab not in want:
            continue
        tok = m.group(3).split()
        vals = tok[: len(mjds)]
        if len(vals) < len(mjds):
            continue
        city[lab] = m.group(2).strip()
        for day, v in zip(mjds, vals):
            try:
                data[lab][day] = float(v) * 1e-9
            except ValueError:
                pass  # "-": no value
        rest = tok[len(mjds): len(mjds) + 3]
        try:
            unc[lab] = tuple(float(x) * 1e-9 if x not in ("-", "NC") else float("nan") for x in rest)  # type: ignore[assignment]
        except ValueError:
            pass
    if not issues:
        raise ResearchFormatError("Circular T: section 1 not found")
    out = []
    for lab, d in sorted(data.items()):
        if not d:
            continue
        mj = np.array(sorted(d))
        u = unc.get(lab, (float("nan"),) * 3)
        out.append(_series(_mjd_to_unix(mj), [d[k] for k in mj], f"{name} [UTC-UTC({lab})]", "circular-t",
                           meta={"peer": lab, "lab": lab, "city": city.get(lab, ""),
                                 "quantity": "UTC - UTC(k)", "uA": u[0], "uB": u[1], "u": u[2],
                                 "issues": issues}))
    if not out:
        raise ResearchFormatError("Circular T: no laboratory values")
    return out


# ------------------------------------------------------------------ RIPE Atlas
def parse_ripe_atlas(text: str, name: str = "atlas") -> List[TimeSeries]:
    """NTP measurement results from the RIPE Atlas API (JSON list or JSON lines)."""
    text = text.strip()
    if text.startswith("["):
        items = json.loads(text)
    else:
        items = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    groups: "OrderedDict[Tuple[int, str], Dict[str, list]]" = OrderedDict()
    info: Dict[Tuple[int, str], Dict[str, object]] = {}
    timeouts = 0
    for it in items:
        if it.get("type") != "ntp":
            continue
        key = (int(it.get("prb_id", 0)), str(it.get("dst_addr") or it.get("dst_name", "")))
        g = groups.setdefault(key, {"t": [], "off": [], "delay": [], "stratum": [], "root_delay": [],
                                    "root_dispersion": []})
        info.setdefault(key, {"dst_name": it.get("dst_name"), "msm_id": it.get("msm_id"), "af": it.get("af"),
                              "from": it.get("from")})
        for r in it.get("result", []):
            if "offset" not in r:
                timeouts += 1
                continue
            t = r.get("final-ts") or r.get("origin-ts")
            g["t"].append(float(t) - NTP_UNIX if t else float(it.get("timestamp", 0)))
            g["off"].append(-float(r["offset"]))  # Atlas: local - server
            g["delay"].append(float(r.get("rtt", np.nan)))
            g["stratum"].append(float(it.get("stratum", np.nan)))
            g["root_delay"].append(float(it.get("root-delay", np.nan)))
            g["root_dispersion"].append(float(it.get("root-dispersion", np.nan)))
    out = []
    for (prb, dst), g in groups.items():
        if not g["t"]:
            continue
        extra = {k: g[k] for k in ("delay", "stratum", "root_delay", "root_dispersion")}
        meta = {"peer": dst, "probe": prb, **info[(prb, dst)], "quantity": "server - probe clock"}
        out.append(_series(g["t"], g["off"], f"{name} [probe {prb} -> {info[(prb, dst)]['dst_name'] or dst}]",
                           "ripe-atlas", extra=extra, meta=meta))
    if not out:
        raise ResearchFormatError(f"RIPE Atlas: no NTP responses ({timeouts} timeouts)")
    for s in out:
        s.meta["timeouts_in_file"] = timeouts
    return out


def group_summary(series: Sequence[TimeSeries], by: str = "peer") -> List[Dict[str, object]]:
    """Offset distribution per group (``peer``: server, ``probe``: vantage point) across many series."""
    groups: Dict[str, List[np.ndarray]] = defaultdict(list)
    for s in series:
        groups[str(s.meta.get(by, s.name))].append(s.offset)
    out = []
    for k, arrs in groups.items():
        x = np.concatenate(arrs)
        out.append({by: k, "series": len(arrs), "samples": int(x.size), "median_offset": float(np.median(x)),
                    "p95_abs_offset": float(np.percentile(np.abs(x), 95)), "max_abs_offset": float(np.abs(x).max())})
    return sorted(out, key=lambda r: -float(r["p95_abs_offset"]))  # type: ignore[arg-type]


# ------------------------------------------------------------------ NTP Pool
def parse_ntppool(lines: Sequence[str], name: str = "ntppool") -> List[TimeSeries]:
    """NTP Pool monitoring log CSV: one series per monitor (offset in s, rtt in ms)."""
    hdr = [c.strip() for c in lines[0].split(",")]
    if "ts_epoch" not in hdr or "offset" not in hdr:
        raise ResearchFormatError("not an NTP Pool score log")
    ix = {c: i for i, c in enumerate(hdr)}
    groups: "OrderedDict[str, Dict[str, list]]" = OrderedDict()
    for ln in lines[1:]:
        f = ln.rstrip("\r\n").split(",")
        if len(f) < len(hdr) or not f[ix["offset"]]:
            continue
        mon = f[ix["monitor_name"]] if "monitor_name" in ix and f[ix["monitor_name"]] else "score"
        g = groups.setdefault(mon, {"t": [], "off": [], "delay": [], "score": [], "step": []})
        try:
            g["t"].append(float(f[ix["ts_epoch"]]))
            g["off"].append(float(f[ix["offset"]]))
            g["delay"].append(float(f[ix["rtt"]]) * 1e-3 if "rtt" in ix and f[ix["rtt"]] else np.nan)
            g["score"].append(float(f[ix["score"]]) if "score" in ix and f[ix["score"]] else np.nan)
            g["step"].append(float(f[ix["step"]]) if "step" in ix and f[ix["step"]] else np.nan)
        except ValueError:
            continue
    out = [_series(g["t"], g["off"], f"{name} [{mon}]", "ntppool",
                   extra={"delay": g["delay"], "score": g["score"], "step": g["step"]},
                   meta={"peer": mon, "monitor": mon, "quantity": "server - monitor"})
           for mon, g in groups.items() if g["t"]]
    if not out:
        raise ResearchFormatError("NTP Pool log has no offsets")
    return out


# ------------------------------------------------------------------ ntpstats open interop dataset
def parse_interop(lines: Sequence[str], name: str = "interop") -> List[TimeSeries]:
    """The ntpstats Live-interop dataset (JSON lines, ``data/interop/``): one series per test and server.

    Failed probes carry no offset; they are counted in ``meta`` (``probes``,
    ``failures``, ``availability``) and their times in ``meta["failure_times"]``.
    """
    groups: "OrderedDict[Tuple[str, str], Dict[str, list]]" = OrderedDict()
    for ln in lines:
        ln = ln.strip()
        if not ln or not ln.startswith("{"):
            continue
        rec = json.loads(ln)
        if "schema" not in rec or "test" not in rec:
            continue
        key = (str(rec["test"]), str(rec.get("server", "")))
        g = groups.setdefault(key, {"t": [], "off": [], "delay": [], "stratum": [], "fail": [], "runs": []})
        g["runs"].append(rec.get("run"))
        if rec.get("ok") and rec.get("offset") is not None:
            g["t"].append(float(rec["time"]))
            g["off"].append(float(rec["offset"]))
            g["delay"].append(float(rec.get("delay", np.nan)))
            g["stratum"].append(float(rec.get("stratum", np.nan)))
        elif not rec.get("ok"):
            g["fail"].append(float(rec["time"]))
    out = []
    for (test, server), g in groups.items():
        if not g["t"]:
            continue
        probes = len(g["t"]) + len(g["fail"])
        out.append(_series(g["t"], g["off"], f"{name} [{test} {server}]", "interop",
                           extra={"delay": g["delay"], "stratum": g["stratum"]},
                           meta={"peer": server, "test": test, "probes": probes, "failures": len(g["fail"]),
                                 "availability": len(g["t"]) / probes, "failure_times": g["fail"],
                                 "runs": len(set(g["runs"])), "quantity": "server - runner clock"}))
    if not out:
        raise ResearchFormatError("interop dataset: no successful probes with an offset")
    return out


def interop_summary(lines: Sequence[str]) -> List[Dict[str, object]]:
    """Per test and server: runs, availability, median offset/delay, last error (from the raw records)."""
    groups: Dict[Tuple[str, str], Dict[str, Any]] = OrderedDict()
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        rec = json.loads(ln)
        if "schema" not in rec or "test" not in rec:
            continue
        g = groups.setdefault((rec["test"], str(rec.get("server", ""))),
                              {"ok": [], "off": [], "delay": [], "runs": set(), "err": [], "flags": []})
        g["runs"].add(rec.get("run"))
        g["ok"].append(bool(rec.get("ok")))
        if rec.get("offset") is not None:
            g["off"].append(float(rec["offset"]))
        if rec.get("delay") is not None:
            g["delay"].append(float(rec["delay"]))
        if rec.get("error"):
            g["err"].append((rec.get("run"), rec["error"]))
        for k in ("interleaved", "offers_v5"):
            if k in rec:
                g["flags"].append((k, bool(rec[k])))
    out = []
    for (test, server), g in groups.items():
        flags: Dict[str, List[bool]] = {}
        for k, v in g["flags"]:
            flags.setdefault(k, []).append(v)
        out.append({"test": test, "server": server, "runs": len(g["runs"]), "probes": len(g["ok"]),
                    "availability": sum(g["ok"]) / len(g["ok"]),
                    "median_offset": float(np.median(g["off"])) if g["off"] else None,
                    "median_delay": float(np.median(g["delay"])) if g["delay"] else None,
                    **{k: sum(v) / len(v) for k, v in flags.items()},
                    "last_error": g["err"][-1][1] if g["err"] else None})
    return out


#: tests whose offsets form the per-run consensus of :func:`interop_trend` (all are NTP exchanges)
CONSENSUS_TESTS = ("ntp4", "nts", "interleaved", "ntpv5")


def interop_trend(lines: Sequence[str], shift: float = 1e-3, consensus_tests: Sequence[str] = CONSENSUS_TESTS
                  ) -> List[Dict[str, Any]]:
    """Per test and server, how its offset, delay and availability evolve over the runs of the dataset.

    The runner's clock is not a reference and changes between runs, so each
    offset is taken relative to the run's *consensus*: the median offset of
    all successful NTP-family probes (``consensus_tests``) in that run. The
    runner's own clock error cancels; what remains is the server's offset from
    the other public servers plus the path asymmetry of that run.

    Each row has the runs where the server was probed, its availability
    overall and in the last run, the relative offset (median, first, last and,
    with three runs or more, the least-squares slope per week), the delay at
    the first and last run, and ``status``:

    ``gone``
        probed successfully before, failing in the last run;
    ``new``
        first probed after the dataset's first run;
    ``shift``
        the last relative offset differs from the median of the earlier ones
        by more than the two runs' error bounds plus ``shift`` seconds
        (default 1 ms). The bound of an NTP exchange is half its round-trip
        delay (the offset error of a correct server and client cannot exceed
        it, whatever the path asymmetry); of a Roughtime response, its radius.
        A path change alone cannot produce a shift; a server whose clock moved
        can;
    ``ok``
        none of these.

    ``timeline`` lists, per run, ``[run, ok, relative offset, delay, bound]``.
    """
    recs = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        rec = json.loads(ln)
        if "schema" in rec and "test" in rec and rec.get("run"):
            recs.append(rec)
    runs = sorted({r["run"] for r in recs})
    if not runs:
        raise ResearchFormatError("interop dataset: no records with a run")
    cons: Dict[str, float] = {}
    for run in runs:
        v = [float(r["offset"]) for r in recs if r["run"] == run and r.get("ok") and r.get("offset") is not None
             and r["test"] in consensus_tests]
        cons[run] = float(np.median(v)) if v else float("nan")
    groups: Dict[Tuple[str, str], Dict[str, list]] = OrderedDict()
    for r in sorted(recs, key=lambda r: (r["run"], float(r.get("time", 0.0)))):
        if r["test"] == "roughtime-chain":
            continue
        g = groups.setdefault((str(r["test"]), str(r.get("server", ""))), {})
        g.setdefault(r["run"], []).append(r)

    def run_seconds(run: str) -> float:
        return float(calendar.timegm(_iso(run)))

    out = []
    for (test, server), byrun in groups.items():
        timeline = []
        for run in runs:
            if run not in byrun:
                continue
            rs = byrun[run]
            good = [x for x in rs if x.get("ok") and x.get("offset") is not None]
            ok = any(x.get("ok") for x in rs)
            rel = float(np.median([float(x["offset"]) for x in good])) - cons[run] if good else None
            if rel is not None and not math.isfinite(rel):
                rel = None
            d = [float(x["delay"]) for x in good if x.get("delay") is not None]
            delay = float(np.median(d)) if d else None
            radius = [float(x["radius"]) for x in good if x.get("radius") is not None]
            bound = float(np.median(radius)) if radius else (delay / 2 if delay is not None else 0.0)
            timeline.append([run, ok, rel, delay, bound])
        probes = sum(len(v) for v in byrun.values())
        oks = sum(1 for v in byrun.values() for x in v if x.get("ok"))
        rels = [(run_seconds(t[0]), t[2]) for t in timeline if t[2] is not None]
        bounds = [t[4] for t in timeline if t[2] is not None]
        dl = [t[3] for t in timeline if t[3] is not None]
        row: Dict[str, Any] = {"test": test, "server": server, "runs": len(timeline), "first": timeline[0][0],
                               "last": timeline[-1][0], "availability": oks / probes if probes else 0.0,
                               "last_ok": bool(timeline[-1][1]),
                               "rel_offset": float(np.median([v for _, v in rels])) if rels else None,
                               "rel_first": rels[0][1] if rels else None, "rel_last": rels[-1][1] if rels else None,
                               "slope_per_week": None, "delay_first": dl[0] if dl else None,
                               "delay_last": dl[-1] if dl else None, "timeline": timeline}
        if len(rels) >= 3:
            x = np.array([a for a, _ in rels]) / 604800.0
            y = np.array([b for _, b in rels])
            if np.ptp(x) > 0:
                row["slope_per_week"] = float(np.polyfit(x - x[0], y, 1)[0])
        if not timeline[-1][1] and any(t[1] for t in timeline[:-1]):
            status = "gone"
        elif timeline[0][0] != runs[0]:
            status = "new"
        elif len(rels) >= 2 and timeline[-1][2] is not None and \
                abs(rels[-1][1] - float(np.median([v for _, v in rels[:-1]]))) > \
                shift + bounds[-1] + float(np.median(bounds[:-1])):
            status = "shift"
        else:
            status = "ok"
        row["status"] = status
        out.append(row)
    return out


def _iso(run: str):
    import time as _time

    return _time.strptime(run.rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S")


def detect(lines: Sequence[str]) -> Optional[str]:
    head = "\n".join(lines[:40])
    first = lines[0] if lines else ""
    if first.startswith("CGGTTS") or ("SAT CL" in head and "REFSYS" in head):
        return "cggtts"
    if "RINEX VERSION / TYPE" in first and first[20:21] == "C":
        return "rinex-clock"
    if "CIRCULAR T" in head[:400]:
        return "circular-t"
    if first.startswith("ts_epoch,") and "offset" in first:
        return "ntppool"
    h = head.lstrip()
    if h.startswith("{") and '"schema"' in first and '"test"' in first:
        return "interop"
    if (h.startswith("[") or h.startswith("{")) and '"type": "ntp"' in head.replace('"type":"ntp"', '"type": "ntp"'):
        return "ripe-atlas"
    return None


# ------------------------------------------------------------------ registration (the plugin API, used in-house)
def _register() -> None:
    from .plugins import ParserPlugin, register_parser

    def det(fmt):
        return lambda lines: 1.0 if detect(lines) == fmt else 0.0

    for fmt, fn, desc in (
        ("cggtts", parse_cggtts, "CGGTTS V2E GNSS time transfer (BIPM)"),
        ("rinex-clock", parse_rinex_clock, "RINEX clock files (IGS .clk)"),
        ("circular-t", parse_circular_t, "BIPM Circular T, UTC - UTC(k)"),
        ("ntppool", parse_ntppool, "NTP Pool monitor score logs"),
        ("interop", parse_interop, "ntpstats open interop dataset (JSON lines)"),
    ):
        register_parser(ParserPlugin(fmt, fn, det(fmt), desc))
    def atlas(lines: Sequence[str], name: str = "atlas") -> List[TimeSeries]:
        return parse_ripe_atlas("\n".join(lines), name)

    register_parser(ParserPlugin("ripe-atlas", atlas, det("ripe-atlas"), "RIPE Atlas NTP measurement results (JSON)"))

    from . import simio

    register_parser(ParserPlugin("omnetpp-vec", simio.parse_omnetpp, simio.detect,
                                 "OMNeT++/INET output vectors (.vec): clock time error, or raw vectors"))


_register()
