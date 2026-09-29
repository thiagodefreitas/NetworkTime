// SPDX-License-Identifier: MIT
// Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
//
// ntpstats web UI: plain JS + uPlot, no build step, no framework.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const PALETTE = ["#3b82f6", "#f97316", "#10b981", "#e11d48", "#8b5cf6", "#eab308", "#06b6d4", "#64748b"];
const KIND_LABEL = { adev: "ADEV", oadev: "OADEV", mdev: "MDEV", tdev: "TDEV", hdev: "HDEV", totdev: "TOTDEV", theo1: "Theo1", mtie: "MTIE", tierms: "TIErms" };
const TIME_KINDS = new Set(["tdev", "mtie", "tierms"]);
const NOISE = { "2": "white PM", "1": "flicker PM", "0": "white FM", "-1": "flicker FM", "-2": "RW FM" };

const state = {
  datasets: [],          // [{id, name, format, samples, ...}]
  active: null,          // id of focused dataset
  compare: new Set(),    // ids overlaid with the active one
  colors: {},            // id -> color
  tab: "overview",
  range: null,           // {start, end} POSIX seconds applied to analyses
  zoom: null,            // pending zoom selection on the offset chart
  kinds: new Set(["oadev", "mdev"]),
  mask: null,            // {id, name} of the loaded limit mask
  charts: {},            // name -> uPlot instance
  cache: {},             // last payloads for export
  live: null,
};

// ------------------------------------------------------------------ utils
function fmtSec(v, digits = 3) {
  if (v == null || !isFinite(v)) return "–";
  if (v === 0) return "0";
  const a = Math.abs(v);
  const units = [[1, "s"], [1e-3, "ms"], [1e-6, "µs"], [1e-9, "ns"], [1e-12, "ps"]];
  for (const [s, u] of units) if (a >= s || s === 1e-12) return `${+(v / s).toPrecision(digits)} ${u}`;
  return `${v} s`;
}
const fmtNum = (v, d = 3) => (v == null || !isFinite(v) ? "–" : (+v).toPrecision(d));
const fmtExp = (v) => (v == null || !isFinite(v) ? "–" : (+v).toExponential(2));
const fmtDate = (t) => (t == null ? "–" : new Date(t * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC");
function fmtDur(s) {
  if (s == null) return "–";
  if (s >= 86400 * 2) return `${(s / 86400).toFixed(1)} d`;
  if (s >= 7200) return `${(s / 3600).toFixed(1)} h`;
  if (s >= 120) return `${(s / 60).toFixed(1)} min`;
  return `${s.toFixed(1)} s`;
}
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, err = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (err ? " err" : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), err ? 6000 : 3000);
}

let busyCount = 0;
function busy(delta) {
  busyCount += delta;
  $("#busy").hidden = busyCount <= 0;
}

async function api(path, opts = {}) {
  busy(1);
  try {
    const headers = Object.assign({ "X-NTPStats": "1" }, opts.headers || {});
    let body = opts.body;
    if (body && typeof body === "object" && !(body instanceof Blob) && !(body instanceof ArrayBuffer)) {
      body = JSON.stringify(body);
      headers["Content-Type"] = "application/json";
    }
    const r = await fetch(path, { method: opts.method || "GET", headers, body });
    const data = r.headers.get("Content-Type")?.includes("json") ? await r.json() : await r.text();
    if (!r.ok) throw new Error(data.error || data || r.statusText);
    return data;
  } finally {
    busy(-1);
  }
}

function params(extra = {}) {
  const p = new URLSearchParams();
  const det = $("#detrend").value;
  if (det !== "none") p.set("detrend", det);
  if ($("#outliers").value) p.set("outliers", $("#outliers").value);
  if (state.range) {
    p.set("start", state.range.start);
    p.set("end", state.range.end);
  }
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== "") p.set(k, v);
  return p.toString();
}

const selectedIds = () => {
  if (!state.active) return [];
  return [state.active, ...[...state.compare].filter((id) => id !== state.active && state.datasets.some((d) => d.id === id))];
};
const dsById = (id) => state.datasets.find((d) => d.id === id);

// ---------------------------------------------------------------- uPlot glue
function axis(extra = {}) {
  return Object.assign({
    stroke: css("--axis"),
    grid: { stroke: css("--grid"), width: 1 },
    ticks: { stroke: css("--grid"), width: 1 },
    font: `11px ${css("--font")}`,
    labelFont: `12px ${css("--font")}`,
  }, extra);
}

function makeChart(name, el, opts, data) {
  if (state.charts[name]) state.charts[name].destroy();
  el.innerHTML = "";
  const width = Math.max(300, el.clientWidth - 16);
  const height = opts.height || (el.classList.contains("tall") ? 420 : el.classList.contains("short") ? 180 : 320);
  const u = new uPlot(Object.assign({ width, height }, opts), data, el);
  state.charts[name] = u;
  return u;
}

const ro = new ResizeObserver(() => {
  for (const u of Object.values(state.charts)) {
    const el = u.root.parentElement;
    if (el && el.offsetParent) u.setSize({ width: Math.max(300, el.clientWidth - 16), height: u.height });
  }
});

function exportPng(name) {
  const u = state.charts[name];
  if (!u) return toast("nothing to export", true);
  const src = u.ctx.canvas;
  const c = document.createElement("canvas");
  c.width = src.width;
  c.height = src.height;
  const ctx = c.getContext("2d");
  ctx.fillStyle = css("--panel");
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(src, 0, 0);
  const a = document.createElement("a");
  a.download = `ntpstats-${name}.png`;
  a.href = c.toDataURL("image/png");
  a.click();
}

// log-scale tick labels with SI prefixes
const logVals = (fmt) => (u, vals) => vals.map((v) => (v == null ? "" : fmt(v)));
function tauFmt(v) {
  if (v >= 86400) return +(v / 86400).toPrecision(3) + "d";
  if (v >= 3600) return +(v / 3600).toPrecision(3) + "h";
  if (v >= 60) return +(v / 60).toPrecision(3) + "m";
  return +v.toPrecision(3) + "s";
}

function tauAxis(v) {
  return v < 1e4 ? `${+v.toPrecision(3)} s` : `${v.toExponential(0).replace("e+", "e")} s`;
}

// Hide helper series (confidence bounds) from a chart's legend.
function hideLegend(u, pred) {
  const rows = u.root.querySelectorAll(".u-legend .u-series");
  u.series.forEach((s, i) => { if (i && pred(s) && rows[i]) rows[i].style.display = "none"; });
}

// ------------------------------------------------------------ dataset list
async function refreshDatasets(selectId) {
  state.datasets = await api("/api/datasets");
  state.datasets.forEach((d, i) => (state.colors[d.id] ??= PALETTE[Object.keys(state.colors).length % PALETTE.length]));
  if (selectId) state.active = selectId;
  if (!dsById(state.active)) state.active = state.datasets[0]?.id ?? null;
  for (const id of [...state.compare]) if (!dsById(id)) state.compare.delete(id);
  renderDatasetList();
}

function renderDatasetList() {
  const ul = $("#datasets");
  ul.innerHTML = "";
  $("#empty-side").hidden = state.datasets.length > 0;
  for (const d of state.datasets) {
    const li = document.createElement("li");
    li.className = d.id === state.active ? "active" : "";
    li.innerHTML = `
      <input type="checkbox" title="Overlay for comparison" ${state.compare.has(d.id) || d.id === state.active ? "checked" : ""} ${d.id === state.active ? "disabled" : ""}>
      <span class="sw" style="background:${state.colors[d.id]}"></span>
      <span class="nm"><b title="${esc(d.name)}">${esc(d.name)}</b><small>${esc(d.format)} · ${d.samples.toLocaleString()} pts${d.live ? " · live" : ""}</small></span>
      <button class="x" title="Remove">×</button>`;
    li.addEventListener("click", (e) => {
      if (e.target.matches("input,button")) return;
      state.active = d.id;
      state.compare.delete(d.id);
      state.range = null;
      updateRangeChip();
      renderDatasetList();
      render();
    });
    $("input", li).addEventListener("change", (e) => {
      e.target.checked ? state.compare.add(d.id) : state.compare.delete(d.id);
      render();
    });
    $(".x", li).addEventListener("click", async () => {
      await api(`/api/datasets/${d.id}`, { method: "DELETE" });
      await refreshDatasets();
      render();
    });
    ul.appendChild(li);
  }
}

// ------------------------------------------------------------------ loading
async function uploadFiles(files) {
  const fmt = $("#format").value;
  let last = null;
  for (const f of files) {
    try {
      const res = await api(`/api/upload?format=${encodeURIComponent(fmt)}`, {
        method: "POST",
        body: await f.arrayBuffer(),  // binary-safe (pcap/pcapng)
        headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "application/octet-stream" },
      });
      last = res[0]?.id ?? last;
      toast(`Loaded ${f.name}: ${res.map((r) => `${r.samples} samples`).join(", ")}`);
    } catch (e) {
      toast(`${f.name}: ${e.message}`, true);
    }
  }
  if (last) {
    await refreshDatasets(last);
    render();
  }
}

// ------------------------------------------------------------------ render
async function render() {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${state.tab}`));
  $("#welcome").hidden = !!state.active;
  if (!state.active) {
    for (const u of Object.values(state.charts)) u.destroy();
    state.charts = {};
    $("#cards").innerHTML = "";
    $("#compare-table").innerHTML = "";
    return;
  }
  try {
    if (state.tab === "overview") await renderOverview();
    else if (state.tab === "offset") await renderOffset();
    else if (state.tab === "stability") await renderStability();
    else if (state.tab === "distribution") await renderDistribution();
    else if (state.tab === "network") await renderNetwork();
  } catch (e) {
    toast(e.message, true);
  }
}

function card(k, v, s = "") {
  return `<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
}

async function renderOverview() {
  const ids = selectedIds();
  const series = await Promise.all(ids.map((id) => api(`/api/series/${id}?${params({ max_points: 2 })}`)));
  const s = series[0].summary;
  const p = s.percentiles || {};
  $("#cards").innerHTML = [
    card("Samples", s.samples.toLocaleString(), `${fmtDur(s.span_s)} · median Δt ${fmtDur(s.median_interval_s)}`),
    card("Mean offset", fmtSec(s.mean), `median ${fmtSec(p.p50)}`),
    card("RMS offset", fmtSec(s.rms), `σ ${fmtSec(s.std)}`),
    card("90 % range", fmtSec(s.range_90), `p5 ${fmtSec(p.p5)} … p95 ${fmtSec(p.p95)}`),
    card("98 % range", fmtSec(s.range_98), `p1 ${fmtSec(p.p1)} … p99 ${fmtSec(p.p99)}`),
    card("Frequency trend", s.offset_slope_ppm == null ? "–" : `${fmtNum(s.offset_slope_ppm, 4)} ppm`, `robust ${fmtNum(s.offset_slope_robust_ppm, 4)} ppm`),
    card("Detrended RMS", fmtSec(s.residual_rms), `${s.outliers_5mad ?? 0} outliers > 5 MAD`),
    card("Sampling", `${Math.round((s.regularity ?? 1) * 100)} % regular`, `${s.gaps ?? 0} gaps, longest ${fmtDur(s.longest_gap_s)}`),
  ].join("");
  const rows = series.map((x, i) => {
    const m = x.summary, pp = m.percentiles || {};
    return `<tr><td><span class="sw" style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${state.colors[ids[i]]}"></span> ${esc(m.name)}</td>
      <td>${esc(m.format)}</td><td>${m.samples}</td><td>${fmtDate(m.start)}</td><td>${fmtDur(m.span_s)}</td>
      <td>${fmtSec(m.mean)}</td><td>${fmtSec(m.rms)}</td><td>${fmtSec(m.range_90)}</td><td>${fmtNum(m.offset_slope_ppm, 4)}</td></tr>`;
  });
  $("#compare-table").innerHTML = `<h3>${ids.length > 1 ? "Comparison" : "Dataset"}</h3><div class="table-wrap"><table>
    <tr><th>Dataset</th><th>Format</th><th>Samples</th><th>Start</th><th>Span</th><th>Mean</th><th>RMS</th><th>90 % range</th><th>Trend ppm</th></tr>
    ${rows.join("")}</table></div>`;
}

async function renderOffset() {
  const ids = selectedIds();
  const overlay = $("#overlay").value;
  const payloads = await Promise.all(ids.map((id, i) =>
    api(`/api/series/${id}?${params({ overlay: i === 0 ? overlay : "", max_points: 5000 })}`)));
  state.cache.offset = payloads;
  const first = payloads[0];

  // auxiliary column selector
  const auxSel = $("#aux");
  const cols = Object.keys(first.extra).filter((c) => c !== "true_offset");
  const prev = auxSel.value;
  auxSel.innerHTML = `<option value="">none</option>` + cols.map((c) => `<option>${esc(c)}</option>`).join("");
  auxSel.value = cols.includes(prev) ? prev : (cols.find((c) => /freq|delay|jitter/.test(c)) || "");

  const tables = payloads.map((p) => [p.t, p.offset]);
  const series = [{}];
  payloads.forEach((p, i) => series.push({
    label: dsById(ids[i])?.name ?? p.name, stroke: state.colors[ids[i]], width: 1.25,
    value: (u, v) => fmtSec(v), points: { show: false },
  }));
  if (first.truth) {
    tables.push([first.t, first.truth]);
    series.push({ label: "true offset", stroke: css("--good"), width: 1.5, dash: [4, 3], value: (u, v) => fmtSec(v) });
  }
  if (first.overlay) {
    tables.push([first.overlay.t, first.overlay.offset]);
    series.push({ label: first.overlay.label, stroke: css("--text"), width: 1.75, value: (u, v) => fmtSec(v) });
  }
  const data = tables.length === 1 ? tables[0] : uPlot.join(tables);
  const det = $("#detrend").value;
  const u = makeChart("offset", $("#chart-offset"), {
    series: series.map((s, i) => (i ? Object.assign({ spanGaps: true }, s) : s)),
    scales: { x: { time: true } },
    axes: [axis(), axis({ label: det === "none" ? "offset" : `offset (${det} detrended)`, values: logVals((v) => fmtSec(v, 3)), size: 70 })],
    cursor: { drag: { x: true, y: false } },
    hooks: { setScale: [(u, key) => key === "x" && onZoom(u)] },
  }, data);
  u._full = [data[0][0], data[0][data[0].length - 1]];

  // auxiliary panel
  const aux = auxSel.value;
  const auxEl = $("#chart-aux");
  if (aux) {
    const at = payloads.map((p) => [p.t, p.extra[aux] || p.t.map(() => null)]);
    const as = [{}].concat(payloads.map((p, i) => ({ label: `${aux} – ${p.name}`, stroke: state.colors[ids[i]], width: 1, spanGaps: true })));
    makeChart("aux", auxEl, {
      series: as, scales: { x: { time: true } }, height: 180,
      axes: [axis(), axis({ label: aux, size: 70 })],
      cursor: { sync: { key: "offset" } },
    }, at.length === 1 ? at[0] : uPlot.join(at));
    auxEl.hidden = false;
  } else {
    state.charts.aux?.destroy();
    delete state.charts.aux;
    auxEl.hidden = true;
  }

  const notes = [];
  if (first.decimated) notes.push(`Display decimated to ${first.t.length.toLocaleString()} points (min/max per bucket); statistics use all samples.`);
  if (first.overlay?.params) {
    const pr = first.overlay.params;
    notes.push(`Kalman noise model fitted from OADEV: r = ${fmtExp(pr.r)} s², q_phase = ${fmtExp(pr.q_phase)} s, q_freq = ${fmtExp(pr.q_freq)} s⁻¹.`);
  }
  if (first.truth) notes.push("Simulated data: dashed green line is the true offset.");
  notes.push("Drag on the chart to zoom; double-click to reset.");
  $("#offset-note").textContent = notes.join(" ");
}

function onZoom(u) {
  const min = u.scales.x.min, max = u.scales.x.max;
  const full = u._full || [min, max];
  const zoomed = min > full[0] + 1e-6 || max < full[1] - 1e-6;
  state.zoom = zoomed ? { start: min, end: max } : null;
  $("#apply-zoom").hidden = !zoomed;
}

function updateRangeChip() {
  const chip = $("#range-chip");
  if (state.range) {
    chip.textContent = `Range ${fmtDate(state.range.start)} → ${fmtDate(state.range.end)}  ✕`;
    chip.hidden = false;
  } else chip.hidden = true;
}

async function renderStability() {
  const ids = selectedIds();
  const kinds = [...state.kinds];
  if (!kinds.length) return toast("select at least one statistic", true);
  const ci = $("#ci").value;
  const q = params({ kinds: kinds.join(","), taus: $("#taus").value, ci, mask: state.mask?.id });
  const payloads = await Promise.all(ids.map((id) => api(`/api/stability/${id}?${q}`)));
  state.cache.stability = payloads;

  const tables = [], series = [{}], bands = [];
  const dashes = [[], [6, 3], [2, 3], [8, 3, 2, 3], [1, 2], [10, 4]];
  const showCi = +ci > 0;
  const kindColors = { adev: PALETTE[5], oadev: PALETTE[0], mdev: PALETTE[1], tdev: PALETTE[2], hdev: PALETTE[4], totdev: PALETTE[6], theo1: PALETTE[7], mtie: PALETTE[3], tierms: "#a16207" };
  payloads.forEach((p, i) => {
    p.results.forEach((r, j) => {
      if (!r.taus.length) return;
      const color = ids.length > 1 ? state.colors[ids[i]] : kindColors[r.kind];
      const name = `${KIND_LABEL[r.kind]}${ids.length > 1 ? " – " + (dsById(ids[i])?.name ?? p.name) : ""}`;
      tables.push([r.taus, r.dev]);
      series.push({ label: name, stroke: color, width: 1.75, dash: dashes[j % dashes.length], points: { show: true, size: 5, fill: color }, value: (u, v) => (TIME_KINDS.has(r.kind) ? fmtSec(v) : fmtExp(v)) });
      if (r.mask && i === 0) {
        tables.push([r.mask.taus, r.mask.limits]);
        series.push({ label: `mask ${r.mask.mask} (${KIND_LABEL[r.kind]})`, stroke: css("--bad"), width: 2, dash: [8, 4], points: { show: true, size: 4, fill: css("--bad") } });
      }
      if (showCi && r.lo && r.kind !== "mtie") {
        const devIdx = series.length - 1;
        tables.push([r.taus, r.hi]);
        series.push({ label: `${name} hi`, stroke: "transparent", points: { show: false }, _aux: true });
        tables.push([r.taus, r.lo]);
        series.push({ label: `${name} lo`, stroke: "transparent", points: { show: false }, _aux: true });
        bands.push({ series: [series.length - 2, series.length - 1], fill: color + "22" });
        void devIdx;
      }
    });
  });
  if (!tables.length) return toast("not enough data for the selected statistics", true);
  let data = tables.length === 1 ? tables[0] : uPlot.join(tables);

  // Optional power-law slope guides anchored at the first point of the first curve.
  if ($("#slopes").checked) {
    const r0 = payloads[0].results.find((r) => r.taus.length);
    if (r0) {
      const x0 = r0.taus[0], y0 = r0.dev[0];
      const guides = TIME_KINDS.has(r0.kind) ? [[-0.5, "slope −½ (white PM)"], [0, "slope 0 (flicker PM)"], [0.5, "slope +½ (white FM)"], [1, "slope +1 (flicker FM)"]] : [[-1, "slope −1 (white/flicker PM)"], [-0.5, "slope −½ (white FM)"], [0, "slope 0 (flicker FM)"], [0.5, "slope +½ (RW FM)"]];
      for (const [k, lbl] of guides) {
        data.push(data[0].map((x) => y0 * Math.pow(x / x0, k)));
        series.push({ label: lbl, stroke: css("--muted"), width: 1, dash: [2, 4], points: { show: false } });
      }
    }
  }
  const allTime = kinds.every((k) => TIME_KINDS.has(k));
  const anyTime = kinds.some((k) => TIME_KINDS.has(k));
  const su = makeChart("stability", $("#chart-stability"), {
    series: series.map((s, i) => (i ? Object.assign({ spanGaps: true }, s) : { label: "τ", value: (u, v) => (v == null ? "–" : tauFmt(v)) })),
    bands,
    scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
    axes: [
      axis({ label: "averaging time τ", values: logVals(tauAxis) }),
      axis({ label: allTime ? "time [s]" : anyTime ? "σ(τ) / time" : "σ_y(τ)", size: 72, values: logVals((v) => (allTime ? fmtSec(v, 2) : v.toExponential(0))) }),
    ],
    legend: { live: true },
  }, data);
  hideLegend(su, (s) => s._aux);

  // mask verdict
  const chip = $("#mask-chip");
  const verdicts = payloads[0].results.filter((r) => r.mask && r.mask.passed != null);
  if (state.mask && verdicts.length) {
    const ok = verdicts.every((r) => r.mask.passed);
    const worst = Math.min(...verdicts.map((r) => r.mask.worst_margin));
    chip.textContent = `${ok ? "PASS" : "FAIL"} · worst margin ${worst.toFixed(2)}×`;
    chip.className = "chip " + (ok ? "pass" : "fail");
    chip.hidden = false;
  } else chip.hidden = true;
  if ($("#dyn").checked) renderDynamic(ids[0], kinds.find((k) => k !== "mtie") || "oadev");
  $("#dyn-wrap").hidden = !$("#dyn").checked;

  // table
  const blocks = payloads.map((p, i) => p.results.map((r) => {
    const rows = r.taus.map((t, k) => `<tr><td>${tauFmt(t)}</td><td>${fmtNum(t, 6)}</td>
      <td>${TIME_KINDS.has(r.kind) ? fmtSec(r.dev[k]) : fmtExp(r.dev[k])}</td>
      <td>${r.lo ? (TIME_KINDS.has(r.kind) ? fmtSec(r.lo[k]) : fmtExp(r.lo[k])) : "–"}</td>
      <td>${r.hi ? (TIME_KINDS.has(r.kind) ? fmtSec(r.hi[k]) : fmtExp(r.hi[k])) : "–"}</td>
      <td>${r.edf ? fmtNum(r.edf[k], 3) : "–"}</td><td>${r.n[k]}</td>
      <td>${r.alpha && r.alpha[k] != null ? NOISE[String(r.alpha[k])] ?? "" : ""}</td>
      ${r.mask ? (r.mask.limit[k] == null ? "<td>–</td><td>–</td>" : `<td>${TIME_KINDS.has(r.kind) ? fmtSec(r.mask.limit[k]) : fmtExp(r.mask.limit[k])}</td><td class="${r.mask.margin[k] < 1 ? "fail" : ""}">${r.mask.margin[k].toFixed(2)}×</td>`) : ""}</tr>`).join("");
    const meta = r.meta || {};
    return `<h3>${esc(r.description)} — ${esc(dsById(ids[i])?.name ?? p.name)}</h3>
      <p class="note">τ₀ = ${fmtNum(r.tau0, 6)} s · ${meta.grid_points ?? "?"} grid points, ${meta.gap_points ?? 0} in gaps (not interpolated) · sampling ${Math.round((meta.regularity ?? 1) * 100)} % regular${r.ci ? ` · ${(r.ci * 100).toFixed(1)} % χ² interval (exact discrete EDF), lag-1 ACF noise ID` : ""}</p>
      <table><tr><th>τ</th><th>τ [s]</th><th>${KIND_LABEL[r.kind]}</th><th>lower</th><th>upper</th><th>EDF</th><th>terms</th><th>noise</th>${r.mask ? "<th>limit</th><th>margin</th>" : ""}</tr>${rows}</table>`;
  }).join("")).join("");
  $("#stability-table").innerHTML = blocks;
}

async function renderDistribution() {
  const ids = selectedIds();
  const bins = $("#bins").value || 60;
  const det = $("#detrend").value;
  const payloads = await Promise.all(ids.map((id) => api(`/api/histogram/${id}?${params({ bins, detrend: det === "none" ? "none" : det })}`)));
  const bars = uPlot.paths.bars({ size: [0.95, Infinity], gap: 0 });
  const tables = [], series = [{}];
  payloads.forEach((p, i) => {
    const c = state.colors[ids[i]];
    tables.push([p.centers, p.density]);
    series.push({ label: dsById(ids[i])?.name ?? p.name, stroke: c, fill: c + (ids.length > 1 ? "44" : "88"), paths: bars, points: { show: false } });
    tables.push([p.centers, p.gauss]);
    series.push({ label: `Gaussian (σ ${fmtSec(p.std)})`, stroke: c, width: 1.5, dash: [5, 3], points: { show: false } });
  });
  makeChart("hist", $("#chart-hist"), {
    series: series.map((s, i) => (i ? Object.assign({ spanGaps: true }, s) : s)),
    scales: { x: { time: false } },
    axes: [axis({ label: "offset", values: logVals((v) => fmtSec(v, 3)) }), axis({ label: "density", size: 70, values: logVals((v) => v.toExponential(0)) })],
  }, tables.length === 1 ? tables[0] : uPlot.join(tables));
}

async function renderNetwork() {
  const id = state.active;
  let p;
  try {
    p = await api(`/api/network/${id}?${params()}`);
  } catch (e) {
    for (const k of ["wedge", "delay", "fpp"]) { state.charts[k]?.destroy(); delete state.charts[k]; }
    $("#net-cards").innerHTML = `<div class="card"><div class="k">Network metrics unavailable</div><div class="s">${esc(e.message)}</div></div>`;
    return;
  }
  const s = p.stats;
  $("#net-cards").innerHTML = [
    card("Floor delay", fmtSec(s.delay_min), `median ${fmtSec(s.delay_median)} · p95 ${fmtSec(s.delay_p95)}`),
    card("Queueing (median)", fmtSec(s.queueing_median), `max delay ${fmtSec(s.delay_max)}`),
    card("Near floor", `${(s.floor_fraction * 100).toFixed(1)} %`, `within ${fmtSec(s.cluster_width)} of floor`),
    card("Offset σ", fmtSec(s.offset_all_std), `floor packets only: ${fmtSec(s.offset_at_floor_std)}`),
    card("Asymmetry indicator", fmtSec(s.asymmetry_indicator), `offset/delay corr ${fmtNum(s.offset_delay_correlation, 2)}`),
  ].join("");
  const c = state.colors[id];
  const q = p.wedge.q;
  makeChart("wedge", $("#chart-wedge"), {
    series: [{ label: "queueing", value: (u, v) => fmtSec(v) }, { label: "offset", stroke: c, paths: () => null, points: { show: true, size: 3, fill: c + "aa", stroke: c + "aa" }, value: (u, v) => fmtSec(v) },
      { label: "±q/2 bound", stroke: css("--muted"), dash: [4, 4], points: { show: false } }, { label: "−q/2", stroke: css("--muted"), dash: [4, 4], points: { show: false } }],
    scales: { x: { time: false } },
    axes: [axis({ label: "queueing delay (delay − floor)", values: logVals((v) => fmtSec(v, 2)) }), axis({ label: `offset (${p.detrend} detrended)`, size: 70, values: logVals((v) => fmtSec(v, 2)) })],
    cursor: { drag: { x: true, y: true } },
  }, [q, p.wedge.offset, q.map((v) => (p.wedge.offset.length ? median(p.wedge.offset.slice(0, 50)) : 0) + v / 2), q.map((v) => (p.wedge.offset.length ? median(p.wedge.offset.slice(0, 50)) : 0) - v / 2)]);
  makeChart("delay", $("#chart-delay"), {
    series: [{}, { label: "round-trip delay", stroke: c, width: 1, value: (u, v) => fmtSec(v) }],
    scales: { x: { time: true } },
    axes: [axis(), axis({ label: "delay", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
  }, [p.t, p.delay]);
  makeChart("fpp", $("#chart-fpp"), {
    series: [{}, { label: `FPP (${p.fpp.window} s windows)`, stroke: c, fill: c + "33", width: 1.5, value: (u, v) => (v == null ? "–" : v.toFixed(1) + " %") }],
    scales: { x: { time: true }, y: { range: [0, 100] } },
    height: 180,
    axes: [axis(), axis({ label: "% near floor", size: 70 })],
  }, [p.fpp.t, p.fpp.pct]);
  $("#net-note").textContent = `Offsets are ${p.detrend}-detrended for this view. FPP uses ${fmtDur(p.fpp.window)} windows. ` + "Each exchange's offset error is bounded by half its queueing delay, so points fan out in a wedge; samples near the apex (floor delay) are the most trustworthy. A non-zero asymmetry indicator means queueing is asymmetric on average — no filter can remove that bias without extra information.";
}

function median(a) {
  const b = a.filter((v) => v != null).sort((x, y) => x - y);
  return b.length ? b[Math.floor(b.length / 2)] : 0;
}


// ------------------------------------------------------- dynamic heat-map
const VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"];
function heatColor(f) {
  const x = Math.min(0.9999, Math.max(0, f)) * (VIRIDIS.length - 1);
  const i = Math.floor(x), t = x - i;
  const a = VIRIDIS[i], b = VIRIDIS[i + 1];
  const mix = (k) => Math.round(parseInt(a.substr(k, 2), 16) * (1 - t) + parseInt(b.substr(k, 2), 16) * t);
  return `rgb(${mix(1)},${mix(3)},${mix(5)})`;
}

async function renderDynamic(id, kind) {
  let d;
  try {
    d = await api(`/api/dynamic/${id}?${params({ kind })}`);
  } catch (e) {
    $("#dyn-note").textContent = e.message;
    return;
  }
  const cv = $("#heat");
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const L = 70, R = 90, T = 10, B = 34;
  const nx = d.times.length, ny = d.taus.length;
  const vals = d.dev.flat().filter((v) => v != null && v > 0);
  if (!nx || !ny || !vals.length) { $("#dyn-note").textContent = "Not enough data for a sliding window."; return; }
  const lo = Math.log10(Math.min(...vals)), hi = Math.log10(Math.max(...vals));
  const cw = (W - L - R) / nx, ch = (H - T - B) / ny;
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
    const v = d.dev[i][j];
    if (v == null || !(v > 0)) continue;
    ctx.fillStyle = heatColor(hi > lo ? (Math.log10(v) - lo) / (hi - lo) : 0.5);
    ctx.fillRect(L + i * cw, T + (ny - 1 - j) * ch, Math.ceil(cw) + 0.5, Math.ceil(ch) + 0.5);
  }
  ctx.fillStyle = css("--axis");
  ctx.font = `11px ${css("--font")}`;
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let j = 0; j < ny; j++) ctx.fillText(tauAxis(d.taus[j]), L - 6, T + (ny - 1 - j + 0.5) * ch);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  const ticks = Math.min(6, nx);
  for (let k = 0; k < ticks; k++) {
    const i = Math.round((k * (nx - 1)) / Math.max(1, ticks - 1));
    ctx.fillText(new Date(d.times[i] * 1000).toISOString().slice(5, 16).replace("T", " "), L + (i + 0.5) * cw, H - B + 6);
  }
  // colour bar
  for (let k = 0; k < 100; k++) {
    ctx.fillStyle = heatColor(k / 99);
    ctx.fillRect(W - R + 20, T + (H - T - B) * (1 - (k + 1) / 100), 14, (H - T - B) / 100 + 1);
  }
  ctx.fillStyle = css("--axis");
  ctx.textAlign = "left"; ctx.textBaseline = "middle";
  const fmtv = TIME_KINDS.has(kind) ? (v) => fmtSec(v, 2) : (v) => v.toExponential(1);
  ctx.fillText(fmtv(10 ** hi), W - R + 38, T + 6);
  ctx.fillText(fmtv(10 ** lo), W - R + 38, H - B - 6);
  $("#dyn-note").textContent = `${KIND_LABEL[kind]} over ${fmtDur(d.window)} windows every ${fmtDur(d.step)} (UTC on the x axis, τ on the y axis). Horizontal bands of change reveal non-stationarity: route changes, load cycles, temperature.`;
}

// -------------------------------------------------------------- live monitor
async function pollLive() {
  try {
    const st = await api("/api/monitor");
    state.live = st;
    $("#live-dot").classList.toggle("on", st.running);
    $("#live-status").textContent = st.running
      ? `Running: ${st.servers.join(", ")} every ${st.interval} s — ${st.samples} samples.` + (st.log.length ? ` Last error: ${st.log[st.log.length - 1]}` : "")
      : st.log.length ? `Stopped. ${st.log[st.log.length - 1]}` : "Not running.";
    if (st.running) {
      const before = dsById(st.id)?.samples;
      await refreshDatasets();
      if (state.active === st.id && dsById(st.id)?.samples !== before && dsById(st.id)?.samples >= 3) render();
    }
  } catch (e) { /* server gone */ }
}

// ------------------------------------------------------------------- wiring
function init() {
  api("/api/info").then((i) => {
    $("#version").textContent = "v" + i.version;
    $("#kinds").innerHTML = Object.keys(i.kinds).map((k) =>
      `<button data-kind="${k}" title="${esc(i.kinds[k])}" class="${state.kinds.has(k) ? "on" : ""}">${KIND_LABEL[k] || k}</button>`).join("");
  });
  $("#kinds").addEventListener("click", (e) => {
    const k = e.target.dataset.kind;
    if (!k) return;
    state.kinds.has(k) ? state.kinds.delete(k) : state.kinds.add(k);
    e.target.classList.toggle("on");
    render();
  });

  $$(".tabs button").forEach((b) => b.addEventListener("click", () => { state.tab = b.dataset.tab; render(); }));
  for (const id of ["detrend", "outliers", "overlay", "aux", "taus", "ci", "slopes", "bins", "dyn"]) $(`#${id}`).addEventListener("change", render);
  $("#mask-chip").addEventListener("click", () => { state.mask = null; $("#mask-label").textContent = "Mask…"; render(); });
  $("#mask-chip").title = "Click to remove the mask";
  $("#mask-input").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const m = await api("/api/mask", { method: "POST", body: await f.text(), headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "text/plain" } });
      state.mask = m;
      $("#mask-label").textContent = `Mask: ${m.name}`;
      render();
    } catch (err) { toast(err.message, true); }
  });
  $("#file-input").addEventListener("change", (e) => { uploadFiles([...e.target.files]); e.target.value = ""; });
  $$("[data-export]").forEach((b) => b.addEventListener("click", () => exportPng(b.dataset.export)));
  $$("[data-csv]").forEach((b) => b.addEventListener("click", () => {
    if (!state.active) return;
    const extra = b.dataset.csv === "stability.csv" ? { kinds: [...state.kinds].join(","), taus: $("#taus").value, ci: $("#ci").value } : {};
    location.href = `/api/export/${state.active}/${b.dataset.csv}?${params(extra)}`;
  }));
  $("#apply-zoom").addEventListener("click", () => {
    state.range = state.zoom;
    state.zoom = null;
    $("#apply-zoom").hidden = true;
    updateRangeChip();
    render();
  });
  $("#range-chip").addEventListener("click", () => { state.range = null; updateRangeChip(); render(); });

  // theme
  const saved = (() => { try { return localStorage.getItem("ntpstats-theme"); } catch { return null; } })();
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("ntpstats-theme", document.documentElement.dataset.theme); } catch { /* private mode */ }
    render();
  });

  // dialogs
  $$("[data-dialog]").forEach((b) => b.addEventListener("click", () => { $(`#${b.dataset.dialog}`).showModal(); pollLive(); }));
  $("#dlg-sim").addEventListener("close", async (e) => {
    const dlg = e.target;
    if (dlg.returnValue !== "ok") return;
    const f = new FormData($("form", dlg));
    try {
      const res = await api("/api/simulate", { method: "POST", body: { preset: f.get("preset"), duration: +f.get("hours") * 3600, seed: +f.get("seed") } });
      await refreshDatasets(res[0].id);
      state.tab = state.tab === "overview" ? "offset" : state.tab;
      render();
    } catch (err) { toast(err.message, true); }
  });
  $("#dlg-live form").addEventListener("submit", async (e) => {
    const action = e.submitter?.value;
    if (action === "cancel") return;
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      if (action === "query") {
        const server = String(f.get("servers")).split(/[\s,]+/)[0];
        const r = await api("/api/query", { method: "POST", body: { server, version: +f.get("version") } });
        $("#query-result").textContent =
          `${r.server} (${r.address})  NTPv${r.version}  stratum ${r.stratum}  ${r.version === 5 ? `timescale ${r.timescale} era ${r.era}` : `refid ${r.refid}`}\noffset ${fmtSec(r.offset)}   delay ${fmtSec(r.delay)}\nroot delay ${fmtSec(r.root_delay)}   root disp ${fmtSec(r.root_dispersion)}   leap ${r.leap}`;
      } else if (action === "start") {
        const r = await api("/api/monitor/start", { method: "POST", body: { source: f.get("source"), servers: f.get("servers"), interval: +f.get("interval"), version: +f.get("version") } });
        await refreshDatasets(r.id);
        toast(`Monitoring ${r.servers.join(", ")}`);
        render();
      } else if (action === "stop") {
        await api("/api/monitor/stop", { method: "POST", body: {} });
      }
      pollLive();
    } catch (err) { toast(err.message, true); }
  });
  $("#demo").addEventListener("click", async () => {
    const res = await api("/api/simulate", { method: "POST", body: { preset: "internet", duration: 86400, seed: 1 } });
    await refreshDatasets(res[0].id);
    render();
  });

  // drag and drop
  let dragDepth = 0;
  addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; $("#drop").hidden = false; });
  addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("#drop").hidden = true; } });
  addEventListener("dragover", (e) => e.preventDefault());
  addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    $("#drop").hidden = true;
    if (e.dataTransfer?.files?.length) uploadFiles([...e.dataTransfer.files]);
  });

  $$(".chart").forEach((el) => ro.observe(el));
  refreshDatasets().then(render);
  setInterval(() => { if (state.live?.running) pollLive(); }, 5000);
}

document.addEventListener("DOMContentLoaded", init);
