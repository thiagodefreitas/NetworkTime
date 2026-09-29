# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""Self-contained HTML reports (one file, works offline, no server needed).

The page embeds uPlot, the computed data and a small renderer, plus the
ntpstats version, the parameters and SHA-256 hashes of the inputs so the
report can be attached to a ticket or a paper supplement and reproduced.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import time
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from . import __version__
from .analysis import detrend as _detrend
from .analysis import format_seconds, summary
from .series import TimeSeries
from .stability import NOISE_NAMES, TIME_KINDS, series_stability

_VENDOR = os.path.join(os.path.dirname(__file__), "web", "vendor")
PALETTE = ["#3b82f6", "#f97316", "#10b981", "#e11d48", "#8b5cf6", "#eab308", "#06b6d4", "#64748b"]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _f(a):
    return [None if not np.isfinite(v) else float(v) for v in np.asarray(a, dtype=float)]


def _decimate(t, y, n=3000):
    if t.size <= n:
        return np.arange(t.size)
    edges = np.linspace(0, t.size, n // 2 + 1).astype(int)
    idx = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b > a:
            seg = y[a:b]
            idx += [a + int(np.nanargmin(seg)), a + int(np.nanargmax(seg))]
    return np.unique(idx)


_CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--border:#e3e6eb;--text:#16181d;--muted:#697080;--grid:#0000000f}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--panel:#161a21;--border:#262c36;--text:#e6e8ec;--muted:#8b93a3;--grid:#ffffff12}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 48px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
h3{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin:18px 0 6px}.meta{color:var(--muted);font-size:12.5px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:10px 12px}
.card .k{color:var(--muted);font-size:12px}.card .v{font-size:18px;font-weight:650;font-variant-numeric:tabular-nums}
.chart{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:8px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:var(--panel);font-variant-numeric:tabular-nums}
th,td{padding:5px 9px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}th{color:var(--muted)}td:first-child,th:first-child{text-align:left}
.wrap{overflow-x:auto}code{font-size:12px}footer{color:var(--muted);font-size:12px;margin-top:32px}
.u-legend{font-size:12px;color:var(--text)}
"""

_JS = r"""
const css=(n)=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function fmtSec(v,d=3){if(v==null||!isFinite(v))return"–";if(v===0)return"0";const a=Math.abs(v);
 for(const[s,u]of[[1,"s"],[1e-3,"ms"],[1e-6,"µs"],[1e-9,"ns"],[1e-12,"ps"]])if(a>=s||s===1e-12)return`${+(v/s).toPrecision(d)} ${u}`;}
const FMT={sec:(v)=>fmtSec(v),exp:(v)=>v==null?"":v.toExponential(1),num:(v)=>v==null?"":+v.toPrecision(3),
 tau:(v)=>v<1e4?`${+v.toPrecision(3)} s`:`${v.toExponential(0).replace("e+","e")} s`};
function axis(label,fmt,size){const a={stroke:css("--muted"),grid:{stroke:css("--grid")},ticks:{stroke:css("--grid")},label};
 if(fmt)a.values=(u,vs)=>vs.map((v)=>v==null?"":FMT[fmt](v));if(size)a.size=size;return a;}
function draw(spec){const el=document.getElementById(spec.id);const W=Math.max(320,el.clientWidth-16);
 const series=[{label:spec.xlabel||"x",value:(u,v)=>v==null?"–":(spec.xfmt?FMT[spec.xfmt](v):v)}];const data=[spec.x];const bands=[];
 for(const s of spec.series){data.push(s.y);const o={label:s.label,stroke:s.color,width:s.width||1.5,spanGaps:true,dash:s.dash,
  points:{show:!!s.points,size:5,fill:s.color}};if(spec.kind==="bars")Object.assign(o,{fill:s.color+"99",paths:uPlot.paths.bars({size:[0.7,64]}),points:{show:false}});
  if(spec.kind==="scatter")Object.assign(o,{paths:()=>null,points:{show:true,size:3,fill:s.color}});series.push(o);
  if(s.lo&&s.hi){data.push(s.hi,s.lo);const n=series.length;series.push({label:s.label+" hi",stroke:"transparent",points:{show:false}},{label:s.label+" lo",stroke:"transparent",points:{show:false}});
   bands.push({series:[n,n+1],fill:s.color+"22"});}}
 const log=spec.kind==="loglog";const xa=axis(spec.xlabel,spec.kind==="time"?null:spec.xfmt);const sx={time:spec.kind==="time",distr:log?3:1};
 if(spec.xlabels){const L=spec.xlabels;xa.splits=()=>L.map((_,i)=>i);xa.values=(u,vs)=>vs.map((v)=>L[v]??"");xa.size=40;
  sx.range=()=>[-0.6,L.length-0.4];series[0].value=(u,v)=>v==null?"–":L[v];}
 const u=new uPlot({width:W,height:spec.height||300,series,bands,scales:{x:sx,y:{distr:log||spec.ylog?3:1}},
  axes:[xa,axis(spec.ylabel,spec.yfmt,72)]},data,el);
 u.root.querySelectorAll(".u-legend .u-series").forEach((r,i)=>{if(u.series[i]&&/ (hi|lo)$/.test(u.series[i].label))r.style.display="none";});}
for(const s of REPORT.charts)draw(s);
"""


def _shell(title: str, body: str, charts: List[dict], meta: dict) -> str:
    with open(os.path.join(_VENDOR, "uPlot.iife.min.js"), encoding="utf-8") as fh:
        uplot_js = fh.read()
    with open(os.path.join(_VENDOR, "uPlot.min.css"), encoding="utf-8") as fh:
        uplot_css = fh.read()
    payload = json.dumps({"charts": charts, "meta": meta}, allow_nan=False).replace("</", "<\\/")
    return f"""<!doctype html>
<!-- Generated by ntpstats {__version__} - https://github.com/thiagodefreitas/NetworkTime - MIT (c) Thiago de Freitas -->
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{uplot_css}{_CSS}</style></head>
<body><main>{body}
<footer>Generated {html.escape(meta['generated'])} by ntpstats {__version__}
(<a href="https://github.com/thiagodefreitas/NetworkTime">github.com/thiagodefreitas/NetworkTime</a>) · MIT © Thiago de Freitas.
Parameters and input hashes are embedded in this file (<code>REPORT.meta</code>).</footer></main>
<script>{uplot_js}</script><script>const REPORT={payload};{_JS}</script></body></html>"""


def _cards(items):
    return '<div class="cards">' + "".join(
        f'<div class="card"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>' for k, v in items
    ) + "</div>"


def _table(head, rows):
    h = "".join(f"<th>{html.escape(c)}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><tr>{h}</tr>{b}</table></div>'


def dataset_report(series: Sequence[TimeSeries], kinds=("oadev", "mdev", "tdev"), detrend: Optional[str] = None,
                   ci: float = 0.683, inputs: Sequence[str] = (), title: str = "ntpstats report") -> str:
    charts: List[dict] = []
    body = [f"<h1>{html.escape(title)}</h1>",
            f'<div class="meta">{len(series)} dataset(s) · stability: {", ".join(k.upper() for k in kinds)}'
            f' · detrend: {detrend or "none"} · CI {"off" if not ci else f"{ci:.1%}"}</div>']
    for i, s in enumerate(series):
        c = PALETTE[i % len(PALETTE)]
        sm: Dict[str, Any] = summary(s)
        p: Dict[str, float] = sm.get("percentiles", {})
        body.append(f"<h2>{html.escape(s.name)} <span class=meta>({html.escape(s.source_format)})</span></h2>")
        body.append(_cards([
            ("Samples", f"{sm['samples']:,}"), ("Span", f"{sm['span_s'] / 3600:.2f} h"),
            ("Mean offset", format_seconds(sm["mean"])), ("RMS offset", format_seconds(sm["rms"])),
            ("90 % range", format_seconds(sm.get("range_90"))), ("p99 |p1", f"{format_seconds(p.get('p99'))} | {format_seconds(p.get('p1'))}"),
            ("Trend", f"{sm.get('offset_slope_ppm', float('nan')):+.4f} ppm"), ("Detrended RMS", format_seconds(sm.get("residual_rms"))),
        ]))
        y = _detrend(s.t, s.offset, detrend) if detrend else s.offset
        idx = _decimate(s.t, y)
        charts.append({"id": f"off{i}", "kind": "time", "x": _f(s.t[idx]), "xlabel": "time", "ylabel": "offset", "yfmt": "sec",
                       "series": [{"label": "offset", "y": _f(y[idx]), "color": c, "width": 1}]})
        body.append(f'<h3>Offset</h3><div class="chart" id="off{i}"></div>')
        results = series_stability(s, kinds=kinds, ci=ci, detrend=detrend)
        taus = sorted({float(t) for r in results for t in r.taus})
        stab_series: List[dict] = []
        spec: Dict[str, Any] = {"id": f"stab{i}", "kind": "loglog", "x": taus, "series": stab_series, "xlabel": "τ",
                                "xfmt": "tau", "ylabel": "σ(τ) / time", "yfmt": "exp", "height": 360}
        rows = []
        for j, r in enumerate(results):
            col = PALETTE[(i + j) % len(PALETTE)]
            m = {float(t): k for k, t in enumerate(r.taus)}

            def pick(arr, m=m, taus=taus):
                return [None if (arr is None or t not in m) else float(arr[m[t]]) for t in taus]

            stab_series.append({"label": r.kind.upper(), "y": pick(r.dev), "color": col, "points": True,
                                   "lo": pick(r.lo) if r.lo is not None else None, "hi": pick(r.hi) if r.hi is not None else None})
            for k, t in enumerate(r.taus):
                v = format_seconds(r.dev[k]) if r.kind in TIME_KINDS else f"{r.dev[k]:.3e}"
                lo = "" if r.lo is None else (format_seconds(r.lo[k]) if r.kind in TIME_KINDS else f"{r.lo[k]:.3e}")
                hi = "" if r.hi is None else (format_seconds(r.hi[k]) if r.kind in TIME_KINDS else f"{r.hi[k]:.3e}")
                nz = NOISE_NAMES.get(int(r.alpha[k]), "") if r.alpha is not None and np.isfinite(r.alpha[k]) else ""
                rows.append([r.kind.upper(), f"{t:.6g}", v, lo, hi, "" if r.edf is None else f"{r.edf[k]:.3g}", int(r.n[k]), nz])
        charts.append(spec)
        body.append(f'<h3>Stability</h3><div class="chart" id="stab{i}"></div>')
        body.append(_table(["stat", "τ [s]", "value", "lower", "upper", "EDF", "terms", "noise"], rows))
        if "delay" in s.extra and np.isfinite(s.extra["delay"]).any():
            from .network import delay_stats, wedge

            ds = delay_stats(TimeSeries(s.t, _detrend(s.t, s.offset, "linear"), extra=dict(s.extra)))
            q, x, _ = wedge(TimeSeries(s.t, _detrend(s.t, s.offset, "linear"), extra=dict(s.extra)))
            o = np.argsort(q)
            if o.size > 3000:
                o = o[np.linspace(0, o.size - 1, 3000).astype(int)]
            charts.append({"id": f"wedge{i}", "kind": "scatter", "x": _f(q[o]), "xlabel": "queueing delay", "xfmt": "sec",
                           "ylabel": "offset (detrended)", "yfmt": "sec", "series": [{"label": "samples", "y": _f(x[o]), "color": c}]})
            body.append("<h3>Network</h3>" + _cards([
                ("Floor delay", format_seconds(ds["delay_min"])), ("Median delay", format_seconds(ds["delay_median"])),
                ("Near floor", f"{ds['floor_fraction']:.1%}"), ("Asymmetry indicator", format_seconds(ds["asymmetry_indicator"])),
            ]) + f'<div class="chart" id="wedge{i}"></div>')
    inputs_meta: List[Dict[str, str]] = [
        {"path": os.path.basename(p), "sha256": sha256(p)} for p in inputs if os.path.exists(p)
    ]
    meta: Dict[str, Any] = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "version": __version__,
        "parameters": {"kinds": list(kinds), "detrend": detrend, "ci": ci},
        "inputs": inputs_meta,
    }
    if inputs_meta:
        body.append("<h2>Inputs</h2>" + _table(["file", "sha256"], [[d["path"], d["sha256"]] for d in inputs_meta]))
    return _shell(title, "\n".join(body), charts, meta)


def bench_report(rows: Sequence[dict], table: Sequence[dict], params: Optional[Dict] = None,
                 title: str = "ntpstats benchmark") -> str:
    scenarios = list(dict.fromkeys(r["scenario"] for r in table))
    ests = list(dict.fromkeys(r["estimator"] for r in table))
    charts, body = [], [f"<h1>{html.escape(title)}</h1>",
                        f'<div class="meta">{len(scenarios)} scenario(s) × {len(ests)} estimator(s) × '
                        f'{len({r["seed"] for r in rows})} seed(s). Error = estimate − true offset.</div>']
    for i, sc in enumerate(scenarios):
        sub = [r for r in table if r["scenario"] == sc]
        charts.append({"id": f"b{i}", "kind": "bars", "x": list(range(len(sub))), "xlabel": "estimator",
                       "xlabels": [r["estimator"] for r in sub],
                       "ylabel": "RMS error", "yfmt": "sec", "ylog": True, "height": 260,
                       "series": [{"label": "RMS error", "y": _f([r["rms"] for r in sub]), "color": PALETTE[i % len(PALETTE)]}]})
        body.append(f"<h2>{html.escape(sc)}</h2><div class='chart' id='b{i}'></div>")
        body.append(_table(["estimator", "RMS", "± (seeds)", "bias", "p95 |e|", "max |e|", "MTIE 1 h", "runtime"],
                           [[r["estimator"], format_seconds(r["rms"]), format_seconds(r["rms_std"]), format_seconds(r["bias"]),
                             format_seconds(r["p95_abs"]), format_seconds(r["max_abs"]), format_seconds(r["mtie_1h"]),
                             f"{r['runtime_s'] * 1e3:.0f} ms"] for r in sub]))
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "version": __version__,
            "parameters": params or {}, "rows": [{k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in r.items()} for r in rows]}
    return _shell(title, "\n".join(body), charts, meta)
