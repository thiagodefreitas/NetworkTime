// SPDX-License-Identifier: MIT
// Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
//
// ntpstats web UI: plain JS + uPlot, no build step, no framework, works offline.
// Pages live under #/<workspace>/<page>; datasets are global; every render is
// tagged so a slow answer for an old selection is never drawn.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const PALETTE = ["#3b82f6", "#f97316", "#10b981", "#e11d48", "#8b5cf6", "#eab308", "#06b6d4", "#64748b"];
const KIND_LABEL = { adev: "ADEV", oadev: "OADEV", mdev: "MDEV", tdev: "TDEV", hdev: "HDEV", totdev: "TOTDEV", mtot: "MTOT", ttot: "TTOT", htot: "HTOT", theo1: "Theo1", theobr: "TheoBR", theoh: "TheoH", mtie: "MTIE", tierms: "TIErms" };
const KIND_COLOR = { adev: PALETTE[5], oadev: PALETTE[0], mdev: PALETTE[1], tdev: PALETTE[2], hdev: PALETTE[4], totdev: PALETTE[6], mtot: "#0f766e", ttot: "#134e4a", htot: "#7c3aed", theo1: PALETTE[7], theobr: "#374151", theoh: "#9333ea", mtie: PALETTE[3], tierms: "#a16207" };
const TIME_KINDS = new Set(["tdev", "ttot", "mtie", "tierms"]);
const NOISE = { "2": "white PM", "1": "flicker PM", "0": "white FM", "-1": "flicker FM", "-2": "RW FM" };

const WORKSPACES = {
  analyze: { label: "Analyze", pages: [["overview", "Overview"], ["offset", "Offset"], ["stability", "Stability"], ["distribution", "Distribution"], ["network", "Network"], ["spectrum", "Spectrum"], ["holdover", "Holdover"], ["events", "Events"]] },
  compare: { label: "Compare", pages: [["table", "Side by side"], ["reference", "Against a reference"], ["hat", "Cornered hat"]] },
  comply: { label: "Comply", pages: [["timeerror", "Time error"], ["audit", "Audit"]] },
  lab: { label: "Lab", pages: [["simulate", "Simulate"], ["bench", "Bench"], ["chain", "PTP chain"]] },
  live: { label: "Live", pages: [["monitor", "Monitor"]] },
};
const WS_ORDER = Object.keys(WORKSPACES);
const NO_DATA_OK = new Set(["compare/table", "lab/simulate", "lab/bench", "lab/chain", "live/monitor"]);
const GLOBAL_CONTROLS = (p) => p.startsWith("analyze/") || p.startsWith("comply/") || p === "compare/reference";

const state = {
  datasets: [], active: null, compare: new Set(), colors: {},
  page: "analyze/overview", lastPage: {}, seq: 0,
  range: null, zoom: null,
  kinds: new Set(["oadev", "mdev"]), mask: null,
  charts: {}, info: null, estimators: null,
  bench: { scenarios: new Set(["lan", "internet"]), estimators: new Set(["raw", "mindelay", "regression", "kalman"]) },
  live: null, filter: "",
};

// ------------------------------------------------------------------ utils
function fmtSec(v, digits = 3) {
  if (v == null || !isFinite(v)) return "–";
  if (v === 0) return "0";
  const a = Math.abs(v);
  for (const [s, u] of [[1, "s"], [1e-3, "ms"], [1e-6, "µs"], [1e-9, "ns"], [1e-12, "ps"]]) if (a >= s || s === 1e-12) return `${+(v / s).toPrecision(digits)} ${u}`;
  return `${v} s`;
}
const fmtNum = (v, d = 3) => (v == null || !isFinite(v) ? "–" : (+v).toPrecision(d));
const fmtExp = (v) => (v == null || !isFinite(v) ? "–" : (+v).toExponential(2));
function fmtPpm(v) {  // fractional frequency given in ppm, shown in the unit that keeps it short
  if (v == null || !isFinite(v)) return "–";
  const a = Math.abs(v);
  return a >= 0.1 ? `${+v.toPrecision(3)} ppm` : a >= 1e-4 ? `${+(v * 1e3).toPrecision(3)} ppb` : `${+(v * 1e6).toPrecision(3)} ppt`;
}
const fmtPct = (v) => (v == null || !isFinite(v) ? "–" : `${+(v * 100).toPrecision(3)} %`);
const fmtDate = (t) => (t == null ? "–" : new Date(t * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC");
function fmtDur(s) {
  if (s == null || !isFinite(s)) return "–";
  if (s >= 86400 * 2) return `${(s / 86400).toFixed(1)} d`;
  if (s >= 7200) return `${(s / 3600).toFixed(1)} h`;
  if (s >= 120) return `${(s / 60).toFixed(1)} min`;
  return `${+s.toPrecision(3)} s`;
}
function parseTime(txt) {  // "1.1us" -> 1.1e-6
  const m = /^\s*([-+0-9.eE]+)\s*(s|ms|us|µs|ns|ps)?\s*$/.exec(String(txt || ""));
  if (!m) return null;
  return +m[1] * ({ s: 1, ms: 1e-3, us: 1e-6, "µs": 1e-6, ns: 1e-9, ps: 1e-12 }[m[2] || "s"]);
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
  busyCount = Math.max(0, busyCount + delta);
  $("#busy").hidden = busyCount <= 0;
}

// Transport: fetch() against the local server, or the in-browser (Pyodide) bridge.
async function fetchTransport(method, path, headers, body) {
  const r = await fetch(path, { method, headers, body });
  const h = {};
  r.headers.forEach((v, k) => (h[k] = v));
  return { status: r.status, contentType: r.headers.get("Content-Type") || "", headers: h, bytes: new Uint8Array(await r.arrayBuffer()) };
}
const transport = window.NTPSTATS_TRANSPORT || fetchTransport;

async function download(path) {
  if (!window.NTPSTATS_BROWSER) { location.href = path; return; }
  busy(1);
  try {
    const r = await transport("GET", path, { "X-NTPStats": "1" }, null);
    if (r.status >= 400) throw new Error(new TextDecoder().decode(r.bytes));
    const disp = r.headers["Content-Disposition"] || r.headers["content-disposition"] || "";
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disp);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([r.bytes], { type: r.contentType }));
    a.download = m ? decodeURIComponent(m[1]) : path.split("/").pop().split("?")[0];
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  } catch (e) { toast(e.message, true); } finally { busy(-1); }
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
    const r = await transport(opts.method || "GET", path, headers, body);
    const text = new TextDecoder().decode(r.bytes);
    const data = r.contentType.includes("json") ? JSON.parse(text) : text;
    if (r.status >= 400) throw new Error(data.error || data || `HTTP ${r.status}`);
    return data;
  } finally { busy(-1); }
}
const tryApi = (path, opts) => api(path, opts).catch((e) => ({ __error: e.message }));

function params(extra = {}) {
  const p = new URLSearchParams();
  const det = $("#detrend").value;
  if (det !== "none") p.set("detrend", det);
  if ($("#outliers").value) p.set("outliers", $("#outliers").value);
  if (state.range) { p.set("start", state.range.start); p.set("end", state.range.end); }
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== "") p.set(k, v);
  return p.toString();
}
const selectedIds = () => (state.active ? [state.active, ...[...state.compare].filter((id) => id !== state.active && dsById(id))] : []);
const dsById = (id) => state.datasets.find((d) => d.id === id);
const dsName = (id) => dsById(id)?.name ?? id;

// ---------------------------------------------------------------- uPlot glue
function axis(extra = {}) {
  return Object.assign({ stroke: css("--axis"), grid: { stroke: css("--grid"), width: 1 }, ticks: { stroke: css("--grid"), width: 1 },
    font: `11px ${css("--font")}`, labelFont: `12px ${css("--font")}` }, extra);
}
function chartHeight(el) {
  if (el.closest(".panel.expanded")) return Math.max(300, el.closest(".panel").clientHeight - 90);
  return el.classList.contains("tall") ? 420 : el.classList.contains("short") ? 190 : 320;
}
// On log scales uPlot cannot place ticks for values that are zero to numerical precision (its tick
// generator rounds to a fixed number of decimals and never terminates), so those become gaps.
const LOG_FLOOR = 1e-20;
function sanitizeLog(opts, data) {
  const scales = opts.scales || {};
  let empty = false;
  for (const [key, sc] of Object.entries(scales)) {
    if (key === "x" || !sc || sc.distr !== 3) continue;
    let any = false;
    (opts.series || []).forEach((s, i) => {
      if (!i || (s.scale || "y") !== key || !data[i]) return;
      data[i] = Array.from(data[i], (v) => (v == null || !isFinite(v) || Math.abs(v) < LOG_FLOOR ? null : v));
      any = any || data[i].some((v) => v != null && v > 0);
    });
    if (!any) { sc.range = [1e-12, 1e-9]; empty = true; }
  }
  return empty;
}
function makeChart(name, el, opts, data) {
  if (state.charts[name]) state.charts[name].destroy();
  el.innerHTML = "";
  el.classList.remove("loading");
  const empty = sanitizeLog(opts, data);
  const u = new uPlot(Object.assign({ width: Math.max(280, el.clientWidth - 16), height: opts.height || chartHeight(el) }, opts), data, el);
  if (empty) el.insertAdjacentHTML("beforeend", `<p class="note">Nothing to plot on a log scale: the values are zero to numerical precision (noise-free or quantised data).</p>`);
  state.charts[name] = u;
  return u;
}
function dropChart(name) { state.charts[name]?.destroy(); delete state.charts[name]; }
const ro = new ResizeObserver(() => {
  for (const u of Object.values(state.charts)) {
    const el = u.root.parentElement;
    if (el && el.offsetParent) u.setSize({ width: Math.max(280, el.clientWidth - 16), height: el.closest(".panel.expanded") ? chartHeight(el) : u.height });
  }
});
function exportPng(name) {
  const u = state.charts[name];
  if (!u) return toast("nothing to export", true);
  const src = u.ctx.canvas, c = document.createElement("canvas");
  c.width = src.width; c.height = src.height;
  const ctx = c.getContext("2d");
  ctx.fillStyle = css("--panel"); ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(src, 0, 0);
  const a = document.createElement("a");
  a.download = `ntpstats-${name}.png`; a.href = c.toDataURL("image/png"); a.click();
}
const logVals = (fmt) => (u, vals) => vals.map((v) => (v == null ? "" : fmt(v)));
function tauFmt(v) {
  if (v >= 86400) return +(v / 86400).toPrecision(3) + "d";
  if (v >= 3600) return +(v / 3600).toPrecision(3) + "h";
  if (v >= 60) return +(v / 60).toPrecision(3) + "m";
  return +v.toPrecision(3) + "s";
}
const tauAxis = (v) => (v < 1e4 ? `${+v.toPrecision(3)} s` : `${v.toExponential(0).replace("e+", "e")} s`);
function hideLegend(u, pred) {
  const rows = u.root.querySelectorAll(".u-legend .u-series");
  u.series.forEach((s, i) => { if (i && pred(s) && rows[i]) rows[i].style.display = "none"; });
}
const card = (k, v, s = "", cls = "") => `<div class="card ${cls}"><div class="k">${k}</div><div class="v" title="${esc(String(v).replace(/<[^>]+>/g, ""))}">${v}</div><div class="s">${s}</div></div>`;
const verdict = (ok, text) => `<div class="verdict ${ok ? "pass" : "fail"}"><b>${ok ? "PASS" : "FAIL"}</b><span>${text}</span></div>`;
const swatch = (id) => `<span class="sw" style="background:${state.colors[id] || css("--muted")}"></span>`;

// ------------------------------------------------------------ dataset list
async function refreshDatasets(selectId) {
  state.datasets = await api("/api/datasets");
  for (const d of state.datasets) state.colors[d.id] ??= PALETTE[Object.keys(state.colors).length % PALETTE.length];
  if (selectId) state.active = selectId;
  if (!dsById(state.active)) state.active = state.datasets[0]?.id ?? null;
  for (const id of [...state.compare]) if (!dsById(id)) state.compare.delete(id);
  renderDatasetList();
  renderStatus();
  $("#global-controls").hidden = !GLOBAL_CONTROLS(state.page) || !state.active;
}

function sparkSvg(vals, color) {
  const v = (vals || []).filter((x) => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), n = vals.length;
  const pts = vals.map((x, i) => (x == null ? null : `${((i / (n - 1)) * 100).toFixed(1)},${(18 - (hi > lo ? ((x - lo) / (hi - lo)) * 16 : 8)).toFixed(1)}`)).filter(Boolean).join(" ");
  return `<svg class="spark" viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.2" vector-effect="non-scaling-stroke"/></svg>`;
}

function renderDatasetList() {
  const ul = $("#datasets");
  const f = state.filter.toLowerCase();
  const shown = state.datasets.filter((d) => !f || `${d.name} ${d.format}`.toLowerCase().includes(f));
  ul.innerHTML = "";
  $("#empty-side").hidden = state.datasets.length > 0;
  $("#ds-count").textContent = state.datasets.length ? `${state.datasets.length}` : "";
  for (const d of shown) {
    const li = document.createElement("li");
    li.className = d.id === state.active ? "active" : "";
    li.tabIndex = 0;
    li.innerHTML = `
      <input type="checkbox" title="Overlay with the active dataset" ${state.compare.has(d.id) || d.id === state.active ? "checked" : ""} ${d.id === state.active ? "disabled" : ""} aria-label="overlay">
      <span class="nm" title="${esc(d.name)}"><b>${esc(shortName(d))}</b><small>${esc(fileOf(d))} · ${d.samples.toLocaleString()} pts${d.live ? " · live" : ""}</small></span>
      <button class="x" title="Remove" aria-label="Remove">×</button>
      ${sparkSvg(d.spark, state.colors[d.id])}`;
    li.addEventListener("click", (e) => { if (!e.target.matches("input,button")) selectDataset(d.id); });
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") selectDataset(d.id); });
    li.addEventListener("dblclick", (e) => { if (e.target.closest(".nm")) startRename(li, d); });
    $("input", li).addEventListener("change", (e) => { e.target.checked ? state.compare.add(d.id) : state.compare.delete(d.id); render(); });
    $(".x", li).addEventListener("click", async () => {
      await api(`/api/datasets/${d.id}`, { method: "DELETE" });
      await refreshDatasets();
      render();
    });
    ul.appendChild(li);
  }
}

// "file.log [192.0.2.10]" -> the peer/flow is the distinguishing part; show it first.
function shortName(d) {
  const m = /^(.*?)\s*\[(.+)\]\s*$/.exec(d.name);
  return m ? m[2] : d.name;
}
function fileOf(d) {
  const m = /^(.*?)\s*\[(.+)\]\s*$/.exec(d.name);
  return m ? m[1] : d.format;
}

function startRename(li, d) {
  const nm = $(".nm", li);
  nm.innerHTML = `<input class="rename" value="${esc(d.name)}" aria-label="New name">`;
  const inp = $("input", nm);
  inp.focus(); inp.select();
  const done = async (save) => {
    if (save && inp.value.trim() && inp.value !== d.name) await api(`/api/rename/${d.id}`, { method: "POST", body: { name: inp.value.trim() } });
    await refreshDatasets();
    render();
  };
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); e.stopPropagation(); });
  inp.addEventListener("blur", () => done(true), { once: true });
}

function selectDataset(id) {
  state.active = id;
  state.compare.delete(id);
  state.range = null;
  updateRangeChip();
  renderDatasetList();
  renderStatus();
  render();
}

function renderStatus() {
  const n = state.datasets.length;
  $("#st-ds").textContent = n ? `${n} dataset${n > 1 ? "s" : ""}` : "no datasets";
  const d = dsById(state.active);
  $("#st-active").textContent = d ? `active: ${d.name}${state.compare.size ? ` (+${state.compare.size} overlaid)` : ""}` : "";
}

// ------------------------------------------------------------------ loading
async function uploadFiles(files) {
  const fmt = $("#format").value;
  let last = null;
  for (const f of files) {
    try {
      const res = await api(`/api/upload?format=${encodeURIComponent(fmt)}`, {
        method: "POST", body: await f.arrayBuffer(),
        headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "application/octet-stream" },
      });
      last = res[0]?.id ?? last;
      toast(`Loaded ${f.name}: ${res.length} series, ${res.reduce((a, r) => a + r.samples, 0).toLocaleString()} samples`);
    } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  if (last) {
    await refreshDatasets(last);
    if (!state.page.startsWith("analyze/") && !state.page.startsWith("comply/")) go("analyze/overview");
    else render();
  }
}
async function simulate(preset, hours = 24, seed = 1) {
  try {
    const res = await api("/api/simulate", { method: "POST", body: { preset, duration: hours * 3600, seed } });
    await refreshDatasets(res[0].id);
    toast(`Simulated ${preset}: ${res[0].samples.toLocaleString()} samples with the true offset`);
    go("analyze/offset");
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ routing
function go(page) {
  if (!page.includes("/")) page = state.lastPage[page] || `${page}/${WORKSPACES[page].pages[0][0]}`;
  if (location.hash !== `#/${page}`) location.hash = `#/${page}`;
  else route();
}
function route() {
  const m = /^#\/(\w+)\/(\w+)/.exec(location.hash);
  let page = m && WORKSPACES[m[1]] && WORKSPACES[m[1]].pages.some(([p]) => p === m[2]) ? `${m[1]}/${m[2]}` : "analyze/overview";
  state.page = page;
  const ws = page.split("/")[0];
  state.lastPage[ws] = page;
  $$(".rail button").forEach((b) => b.classList.toggle("active", b.dataset.ws === ws));
  $("#tabs").innerHTML = WORKSPACES[ws].pages.map(([p, label]) => `<a href="#/${ws}/${p}" role="tab" class="${`${ws}/${p}` === page ? "active" : ""}">${label}</a>`).join("");
  $$(".page").forEach((s) => s.classList.toggle("active", s.dataset.page === page));
  // a field left focused on a page that is now hidden would swallow the keyboard shortcuts
  if (document.activeElement && document.activeElement.closest(".page:not(.active)")) document.activeElement.blur();
  $("#global-controls").hidden = !GLOBAL_CONTROLS(page) || !state.active;
  document.title = `${WORKSPACES[ws].pages.find(([p]) => `${ws}/${p}` === page)[1]} · ntpstats`;
  render();
}
function stepPage(delta) {
  const [ws] = state.page.split("/");
  const pages = WORKSPACES[ws].pages.map(([p]) => `${ws}/${p}`);
  go(pages[(pages.indexOf(state.page) + delta + pages.length) % pages.length]);
}

// ------------------------------------------------------------------ render
const RENDER = {
  "analyze/overview": renderOverview, "analyze/offset": renderOffset, "analyze/stability": renderStability,
  "analyze/distribution": renderDistribution, "analyze/network": renderNetwork, "analyze/spectrum": renderSpectrum,
  "analyze/holdover": renderHoldover, "analyze/events": renderEventsPage,
  "compare/table": renderCompareTable, "compare/reference": renderReference, "compare/hat": renderHat,
  "comply/timeerror": renderTimeErrorPage, "comply/audit": renderAudit,
  "lab/simulate": () => {}, "lab/bench": renderBenchForm, "lab/chain": () => {}, "live/monitor": renderLive,
};

async function render() {
  const page = state.page;
  const tok = ++state.seq;
  $("#welcome").hidden = !!state.active;
  if (!state.active && !NO_DATA_OK.has(page)) {
    if (page !== "analyze/overview") $(`.page[data-page="${page}"]`).querySelectorAll(".chart").forEach((el) => (el.innerHTML = ""));
    for (const id of ["cards", "te-cards"]) $(`#${id}`).innerHTML = "";
    $("#te-wrap").hidden = true;
    $("#ov-offset-panel").hidden = $("#ov-adev-panel").hidden = true;
    return;
  }
  $$(".chart.loading").forEach((el) => el.classList.remove("loading"));  // a superseded render elsewhere left them
  $$(`.page[data-page="${page}"] .chart`).forEach((el) => el.classList.add("loading"));
  try {
    await RENDER[page](() => tok === state.seq);
  } catch (e) {
    if (tok === state.seq) toast(e.message, true);
  } finally {
    if (tok === state.seq) $$(`.page[data-page="${page}"] .chart`).forEach((el) => el.classList.remove("loading"));
  }
}

// ----- Analyze ---------------------------------------------------------------
async function renderOverview(fresh) {
  const id = state.active;
  const [series, stab, te, ev] = await Promise.all([
    api(`/api/series/${id}?${params({ max_points: 1200 })}`),
    tryApi(`/api/stability/${id}?${params({ kinds: "oadev", ci: 0 })}`),
    tryApi(`/api/timeerror/${id}?${params()}`),
    tryApi(`/api/events/${id}?${params()}`),
  ]);
  if (!fresh()) return;
  const s = series.summary, p = s.percentiles || {};
  $("#cards").innerHTML = [
    card("Samples", s.samples.toLocaleString(), `${fmtDur(s.span_s)} · Δt ${fmtDur(s.median_interval_s)}`),
    card("Mean offset", fmtSec(s.mean), `median ${fmtSec(p.p50)}`),
    card("RMS offset", fmtSec(s.rms), `σ ${fmtSec(s.std)}`),
    card("90 % range", fmtSec(s.range_90), `p5 ${fmtSec(p.p5)} … p95 ${fmtSec(p.p95)}`),
    card("Frequency trend", fmtPpm(s.offset_slope_ppm), `robust ${fmtPpm(s.offset_slope_robust_ppm)}`),
    card("Detrended RMS", fmtSec(s.residual_rms), `${s.outliers_5mad ?? 0} outliers > 5 MAD`),
    card("Regular sampling", `${Math.round((s.regularity ?? 1) * 100)} %`, `${s.gaps ?? 0} gaps, longest ${fmtDur(s.longest_gap_s)}`),
    card("Events", ev.__error ? "–" : String(ev.events.length), ev.__error ? "" : Object.entries(ev.summary || {}).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ") || "none detected"),
  ].join("");
  $("#ov-offset-panel").hidden = false;
  makeChart("ov", $("#chart-ov"), {
    series: [{}, { label: "offset", stroke: state.colors[id], width: 1.2, value: (u, v) => fmtSec(v), points: { show: false } }],
    scales: { x: { time: true } }, legend: { show: false },
    axes: [axis(), axis({ values: logVals((v) => fmtSec(v, 2)), size: 62 })],
  }, [series.t, series.offset]);
  const r = stab.__error ? null : stab.results.find((x) => x.taus.length);
  $("#ov-adev-panel").hidden = !r;
  if (r) makeChart("ov-adev", $("#chart-ov-adev"), {
    series: [{ value: (u, v) => (v == null ? "–" : tauFmt(v)) }, { label: "OADEV", stroke: PALETTE[0], width: 1.6, points: { show: true, size: 4, fill: PALETTE[0] }, value: (u, v) => fmtExp(v) }],
    scales: { x: { time: false, distr: 3 }, y: { distr: 3 } }, legend: { show: false },
    axes: [axis({ values: logVals(tauAxis) }), axis({ values: logVals((v) => v.toExponential(0)), size: 62 })],
  }, [r.taus, r.dev]);
  $("#te-wrap").hidden = !!te.__error;
  if (!te.__error) {
    const last = (x) => (x && x.dev && x.dev.length ? x.dev[x.dev.length - 1] : null);
    $("#te-cards").innerHTML = [
      card("max|TE|", fmtSec(te.max_abs_te), "unfiltered"),
      card("cTE", fmtSec(te.cte), `worst window ${fmtSec(te.max_abs_cte_window)}`),
      card("max|TEL|", fmtSec(te.max_abs_tel), `${te.lpf_hz} Hz low-pass`),
      card("dTE_L p-p", fmtSec(te.dte_l_pp), `MTIE ${fmtSec(last(te.dte_l_mtie))}`),
    ].join("") + `<a class="card" href="#/comply/timeerror"><div class="k">More</div><div class="v">Time error →</div><div class="s">TE/TEL chart, MTIE/TDEV</div></a>`;
  }
  $("#ov-events").innerHTML = "";
}

async function renderOffset(fresh) {
  const ids = selectedIds();
  const overlay = $("#overlay").value;
  const payloads = await Promise.all(ids.map((id, i) => api(`/api/series/${id}?${params({ overlay: i === 0 ? overlay : "", max_points: 5000 })}`)));
  if (!fresh()) return;
  const first = payloads[0];
  const auxSel = $("#aux");
  const cols = Object.keys(first.extra).filter((c) => c !== "true_offset");
  const prev = auxSel.value;
  auxSel.innerHTML = `<option value="">none</option>` + cols.map((c) => `<option>${esc(c)}</option>`).join("");
  auxSel.value = cols.includes(prev) ? prev : (cols.find((c) => /freq|delay|jitter/.test(c)) || "");
  const tables = payloads.map((p) => [p.t, p.offset]);
  const series = [{}];
  payloads.forEach((p, i) => series.push({ label: dsName(ids[i]), stroke: state.colors[ids[i]], width: 1.25, value: (u, v) => fmtSec(v), points: { show: false } }));
  if (first.truth) { tables.push([first.t, first.truth]); series.push({ label: "true offset", stroke: css("--good"), width: 1.5, dash: [4, 3], value: (u, v) => fmtSec(v) }); }
  if (first.overlay) { tables.push([first.overlay.t, first.overlay.offset]); series.push({ label: first.overlay.label, stroke: css("--text"), width: 1.75, value: (u, v) => fmtSec(v) }); }
  const data = tables.length === 1 ? tables[0] : uPlot.join(tables);
  const det = $("#detrend").value;
  const u = makeChart("offset", $("#chart-offset"), {
    series: series.map((s, i) => (i ? Object.assign({ spanGaps: true }, s) : s)),
    scales: { x: { time: true } },
    axes: [axis(), axis({ label: det === "none" ? "offset" : `offset (${det} detrended)`, values: logVals((v) => fmtSec(v, 3)), size: 70 })],
    cursor: { drag: { x: true, y: false }, sync: { key: "offset" } },
    hooks: { setScale: [(u, key) => key === "x" && onZoom(u)] },
  }, data);
  u._full = [data[0][0], data[0][data[0].length - 1]];
  const aux = auxSel.value, auxEl = $("#chart-aux");
  if (aux) {
    const at = payloads.map((p) => [p.t, p.extra[aux] || p.t.map(() => null)]);
    makeChart("aux", auxEl, {
      series: [{}].concat(payloads.map((p, i) => ({ label: `${aux} – ${dsName(ids[i])}`, stroke: state.colors[ids[i]], width: 1, spanGaps: true }))),
      scales: { x: { time: true } }, height: 180, cursor: { sync: { key: "offset" } },
      axes: [axis(), axis({ label: aux, size: 70, values: /delay|disp|jitter|offset|bound|error|rms/.test(aux) ? logVals((v) => fmtSec(v, 2)) : undefined })],
    }, at.length === 1 ? at[0] : uPlot.join(at));
    auxEl.hidden = false;
  } else { dropChart("aux"); auxEl.hidden = true; }
  const notes = [];
  if (first.decimated) notes.push(`Display decimated to ${first.t.length.toLocaleString()} points (min/max per bucket); statistics use all samples.`);
  if (first.overlay?.params) notes.push(`Kalman noise model from OADEV: r = ${fmtExp(first.overlay.params.r)} s², q_phase = ${fmtExp(first.overlay.params.q_phase)} s, q_freq = ${fmtExp(first.overlay.params.q_freq)} s⁻¹.`);
  if (first.truth) notes.push("Simulated: the dashed green line is the true offset.");
  $("#offset-note").textContent = notes.join(" ");
}

function onZoom(u) {
  const min = u.scales.x.min, max = u.scales.x.max, full = u._full || [min, max];
  const zoomed = min > full[0] + 1e-6 || max < full[1] - 1e-6;
  state.zoom = zoomed ? { start: min, end: max } : null;
  $("#apply-zoom").hidden = !zoomed;
}
function updateRangeChip() {
  const chip = $("#range-chip");
  chip.hidden = !state.range;
  if (state.range) chip.textContent = `${fmtDate(state.range.start)} → ${fmtDate(state.range.end)}  ✕`;
}

async function renderStability(fresh) {
  const ids = selectedIds();
  const kinds = [...state.kinds];
  if (!kinds.length) return toast("select at least one statistic", true);
  const ci = $("#ci").value;
  const q = params({ kinds: kinds.join(","), taus: $("#taus").value, ci, mask: state.mask?.id });
  const [payloads, noise] = await Promise.all([
    Promise.all(ids.map((id) => api(`/api/stability/${id}?${q}`))),
    $("#noisefit").checked ? tryApi(`/api/noise/${ids[0]}?${params({ kinds: kinds.join(",") })}`) : Promise.resolve(null),
  ]);
  if (!fresh()) return;
  const tables = [], series = [{}], bands = [];
  const dashes = [[], [6, 3], [2, 3], [8, 3, 2, 3], [1, 2], [10, 4]];
  payloads.forEach((p, i) => {
    p.results.forEach((r, j) => {
      if (!r.taus.length) return;
      const color = ids.length > 1 ? state.colors[ids[i]] : KIND_COLOR[r.kind];
      const name = `${KIND_LABEL[r.kind]}${ids.length > 1 ? " – " + dsName(ids[i]) : ""}`;
      tables.push([r.taus, r.dev]);
      series.push({ label: name, stroke: color, width: 1.75, dash: dashes[j % dashes.length], points: { show: true, size: 5, fill: color }, value: (u, v) => (TIME_KINDS.has(r.kind) ? fmtSec(v) : fmtExp(v)) });
      if (r.mask && i === 0) {
        tables.push([r.mask.taus, r.mask.limits]);
        series.push({ label: `mask ${r.mask.mask}`, stroke: css("--bad"), width: 2, dash: [8, 4], points: { show: true, size: 4, fill: css("--bad") } });
      }
      if (+ci > 0 && r.lo && r.kind !== "mtie") {
        tables.push([r.taus, r.hi]); series.push({ label: `${name} hi`, stroke: "transparent", points: { show: false }, _aux: true });
        tables.push([r.taus, r.lo]); series.push({ label: `${name} lo`, stroke: "transparent", points: { show: false }, _aux: true });
        bands.push({ series: [series.length - 2, series.length - 1], fill: color + "22" });
      }
    });
  });
  $("#noise-wrap").hidden = !(noise && !noise.__error);
  if (noise && !noise.__error && tables.length) {
    for (const [k, c] of Object.entries(noise.curves)) {
      tables.push([c.taus, c.dev]);
      series.push({ label: `model ${KIND_LABEL[k]}`, stroke: KIND_COLOR[k] || css("--muted"), width: 1.5, dash: [4, 4], points: { show: false }, value: (u, v) => (TIME_KINDS.has(k) ? fmtSec(v) : fmtExp(v)) });
    }
  } else if (noise?.__error) toast(`noise model: ${noise.__error}`, true);
  if (!tables.length) return toast("not enough data for the selected statistics", true);
  const data = tables.length === 1 ? tables[0] : uPlot.join(tables);
  if ($("#slopes").checked) {
    const r0 = payloads[0].results.find((r) => r.taus.length);
    if (r0) {
      const x0 = r0.taus[0], y0 = r0.dev[0];
      const guides = TIME_KINDS.has(r0.kind) ? [[-0.5, "−½ white PM"], [0, "0 flicker PM"], [0.5, "+½ white FM"], [1, "+1 flicker FM"]] : [[-1, "−1 white/flicker PM"], [-0.5, "−½ white FM"], [0, "0 flicker FM"], [0.5, "+½ RW FM"]];
      for (const [k, lbl] of guides) { data.push(data[0].map((x) => y0 * Math.pow(x / x0, k))); series.push({ label: `slope ${lbl}`, stroke: css("--muted"), width: 1, dash: [2, 4], points: { show: false } }); }
    }
  }
  const allTime = kinds.every((k) => TIME_KINDS.has(k)), anyTime = kinds.some((k) => TIME_KINDS.has(k));
  const su = makeChart("stability", $("#chart-stability"), {
    series: series.map((s, i) => (i ? Object.assign({ spanGaps: true }, s) : { label: "τ", value: (u, v) => (v == null ? "–" : tauFmt(v)) })),
    bands, scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
    axes: [axis({ label: "averaging time τ", values: logVals(tauAxis) }),
      axis({ label: allTime ? "time [s]" : anyTime ? "σ(τ) / time" : "σ_y(τ)", size: 72, values: logVals((v) => (allTime ? fmtSec(v, 2) : v.toExponential(0))) })],
  }, data);
  hideLegend(su, (s) => s._aux);
  const chip = $("#mask-chip");
  const verdicts = payloads[0].results.filter((r) => r.mask && r.mask.passed != null);
  if (state.mask && verdicts.length) {
    const ok = verdicts.every((r) => r.mask.passed);
    chip.textContent = `${ok ? "PASS" : "FAIL"} · worst margin ${Math.min(...verdicts.map((r) => r.mask.worst_margin)).toFixed(2)}×  ✕`;
    chip.className = "chip " + (ok ? "pass" : "fail");
    chip.hidden = false;
  } else chip.hidden = true;
  $("#dyn-wrap").hidden = !$("#dyn").checked;
  if ($("#dyn").checked) renderDynamic(ids[0], kinds.find((k) => k !== "mtie") || "oadev", fresh);
  $("#stability-table").innerHTML = payloads.map((p, i) => p.results.map((r) => {
    const f = (v) => (TIME_KINDS.has(r.kind) ? fmtSec(v) : fmtExp(v));
    const rows = r.taus.map((t, k) => `<tr><td>${tauFmt(t)}</td><td>${f(r.dev[k])}</td><td>${r.lo ? f(r.lo[k]) : "–"}</td><td>${r.hi ? f(r.hi[k]) : "–"}</td>
      <td>${r.edf ? fmtNum(r.edf[k], 3) : "–"}</td><td>${r.n[k]}</td><td>${r.alpha && r.alpha[k] != null ? NOISE[String(r.alpha[k])] ?? "" : ""}</td>
      ${r.mask ? (r.mask.limit[k] == null ? "<td>–</td><td>–</td>" : `<td>${f(r.mask.limit[k])}</td><td class="${r.mask.margin[k] < 1 ? "fail" : "pass"}">${r.mask.margin[k].toFixed(2)}×</td>`) : ""}</tr>`).join("");
    const meta = r.meta || {};
    return `<h3>${esc(r.description)} — ${esc(dsName(ids[i]))}</h3>
      <p class="note">τ₀ = ${fmtNum(r.tau0, 6)} s · ${meta.grid_points ?? "?"} grid points, ${meta.gap_points ?? 0} in gaps (never interpolated)${r.ci ? ` · ${(r.ci * 100).toFixed(1)} % χ² interval from the exact EDF` : ""}</p>
      <table><tr><th>τ</th><th>${KIND_LABEL[r.kind]}</th><th>lower</th><th>upper</th><th>EDF</th><th>terms</th><th>noise</th>${r.mask ? "<th>limit</th><th>margin</th>" : ""}</tr>${rows}</table>`;
  }).join("")).join("");
  if (noise && !noise.__error) renderNoiseTable(noise);
}

function renderNoiseTable(n) {
  $("#noise-table").innerHTML = `<table><tr><th>noise</th><th>α</th><th>h_α</th><th>95 % interval</th></tr>${n.alphas.map((a) => {
    const v = n.h[String(a)], lo = n.lo[String(a)], hi = n.hi[String(a)];
    return `<tr><td>${NOISE[String(a)]}</td><td>${a}</td><td>${v > 0 ? fmtExp(v) : "–"}</td><td>${v > 0 ? `${fmtExp(lo)} … ${fmtExp(hi)}` : hi != null ? `< ${fmtExp(hi)}` : "–"}</td></tr>`;
  }).join("")}</table>`;
  const corners = (n.corners || []).map((c) => `${c.from} → ${c.to} near τ ≈ ${tauFmt(c.tau)}`).join("; ");
  $("#noise-note").textContent = `reduced χ² ${fmtNum(n.reduced_chi2, 3)}${n.drift ? ` · drift ${fmtExp(n.drift)} /s` : ""}${corners ? ` · ${corners}` : ""}. Quick analytic intervals; ntpstats noise FILE gives bootstrap intervals, a simulator scenario and INET oscillator settings.`;
}

async function renderSpectrum(fresh) {
  const id = state.active, carrier = $("#sp-carrier").value;
  const p = await api(`/api/spectrum/${id}?${params({ kind: $("#sp-kind").value, method: $("#sp-method").value, carrier })}`);
  if (!fresh()) return;
  const lf = p.lf_dbc && carrier;
  const series = [{ label: "f", value: (u, v) => (v == null ? "–" : `${fmtExp(v)} Hz`) },
    { label: lf ? "L(f)" : p.kind === "x" ? "S_x(f)" : "S_y(f)", stroke: PALETTE[0], width: 1.75, points: { show: true, size: 4, fill: PALETTE[0] }, value: (u, v) => (v == null ? "–" : lf ? `${v.toFixed(1)} dBc/Hz` : fmtExp(v)) }];
  const data = [p.f, lf ? p.lf_dbc : p.psd];
  if (p.model && !lf) { data.push(p.model); series.push({ label: "power-law model", stroke: css("--muted"), width: 1.5, dash: [4, 4], points: { show: false }, value: (u, v) => fmtExp(v) }); }
  makeChart("spectrum", $("#chart-spectrum"), {
    series, scales: { x: { time: false, distr: 3 }, y: { distr: lf ? 1 : 3 } },
    axes: [axis({ label: "Fourier frequency f [Hz]", values: logVals((v) => v.toExponential(0)) }),
      axis({ label: lf ? "L(f) [dBc/Hz]" : p.kind === "x" ? "S_x(f) [s²/Hz]" : "S_y(f) [1/Hz]", size: 72, values: lf ? undefined : logVals((v) => v.toExponential(0)) })],
  }, data);
  const m = p.meta || {};
  $("#sp-note").textContent = `${m.method}, ${m.segments} segments of ${m.nperseg} points over ${m.stretches} gap-free stretch(es). One-sided PSDs (IEEE 1139).`;
}

async function renderHoldover(fresh) {
  let r;
  try {
    r = await api(`/api/holdover/${state.active}?${params({ horizon: $("#ho-horizon").value, limit: $("#ho-limits").value, model: $("#ho-model").value, source: $("#ho-source").value })}`);
  } catch (e) {
    $("#ho-cards").innerHTML = card("Holdover prediction unavailable", "–", esc(e.message));
    dropChart("holdover"); $("#chart-holdover").innerHTML = "";
    return;
  }
  if (!fresh()) return;
  const cards = [card("Frequency at loss", `${fmtNum(r.frequency * 1e9, 4)} ppb`, `fit over ${fmtDur(r.window)}`),
    card("Drift", `${fmtNum(r.drift * 86400e9, 3)} ppb/day`, r.meta.drift_in_mean ? "shifts the mean TIE" : "not significant")];
  for (const [lim, tt] of Object.entries(r.limits || {})) cards.push(card(`within ${fmtSec(+lim)}`, tt.envelope ? fmtDur(tt.envelope) : `> ${fmtDur(r.t[r.t.length - 1])}`, `${Math.round(r.ci * 100)} % envelope; expected ${tt.mean ? fmtDur(tt.mean) : "beyond horizon"}`));
  $("#ho-cards").innerHTML = cards.join("");
  const hiAbs = r.lo.map((v, i) => Math.max(Math.abs(v), Math.abs(r.hi[i])));
  const data = [r.t, r.mean.map((v) => Math.abs(v) || null), hiAbs];
  const series = [{ label: "after loss", value: (u, v) => (v == null ? "–" : fmtDur(v)) },
    { label: "|mean TIE|", stroke: PALETTE[0], width: 1.5, points: { show: false }, value: (u, v) => fmtSec(v) },
    { label: `${Math.round(r.ci * 100)} % envelope`, stroke: PALETTE[3], width: 2, points: { show: false }, value: (u, v) => fmtSec(v) }];
  for (const lim of Object.keys(r.limits || {})) { data.push(r.t.map(() => +lim)); series.push({ label: `limit ${fmtSec(+lim)}`, stroke: css("--bad"), width: 1, dash: [6, 4], points: { show: false }, value: (u, v) => fmtSec(v) }); }
  makeChart("holdover", $("#chart-holdover"), {
    series, scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
    axes: [axis({ label: "time since loss of reference", values: logVals(tauFmt) }), axis({ label: "|TIE| [s]", size: 72, values: logVals((v) => fmtSec(v, 2)) })],
  }, data);
  $("#ho-note").textContent = (r.meta.warning ? r.meta.warning + ". " : "") + "Predicted time error if the reference were lost at the end of the data, from the fitted noise model and its uncertainty. Check calibration with ntpstats holdover FILE --backtest 20.";
}

async function renderDistribution(fresh) {
  const ids = selectedIds(), det = $("#detrend").value;
  const payloads = await Promise.all(ids.map((id) => api(`/api/histogram/${id}?${params({ bins: $("#bins").value || 60, detrend: det === "none" ? "none" : det })}`)));
  if (!fresh()) return;
  const bars = uPlot.paths.bars({ size: [0.95, Infinity], gap: 0 });
  const tables = [], series = [{}];
  payloads.forEach((p, i) => {
    const c = state.colors[ids[i]];
    tables.push([p.centers, p.density]); series.push({ label: dsName(ids[i]), stroke: c, fill: c + (ids.length > 1 ? "44" : "88"), paths: bars, points: { show: false } });
    tables.push([p.centers, p.gauss]); series.push({ label: `Gaussian (σ ${fmtSec(p.std)})`, stroke: c, width: 1.5, dash: [5, 3], points: { show: false } });
  });
  makeChart("hist", $("#chart-hist"), {
    series: series.map((s, i) => (i ? Object.assign({ spanGaps: true }, s) : s)), scales: { x: { time: false } },
    axes: [axis({ label: "offset", values: logVals((v) => fmtSec(v, 3)) }), axis({ label: "density", size: 70, values: logVals((v) => v.toExponential(0)) })],
  }, tables.length === 1 ? tables[0] : uPlot.join(tables));
}

async function renderNetwork(fresh) {
  const id = state.active;
  const hasDelay = (dsById(id)?.columns || []).includes("delay");
  const [p, tr] = hasDelay ? await Promise.all([tryApi(`/api/network/${id}?${params()}`), tryApi(`/api/trace/${id}?${params()}`)])
    : [{ __error: "this dataset has no round-trip delay; network metrics need two-way exchanges (NTP or PTP logs and captures)" }, null];
  if (!fresh()) return;
  if (p.__error) {
    for (const k of ["wedge", "delay", "fpp", "trace"]) { dropChart(k); }
    $$('.page[data-page="analyze/network"] .chart').forEach((el) => (el.innerHTML = ""));
    $("#net-cards").innerHTML = card("Network metrics unavailable", "–", esc(p.__error));
    $("#trace-panel").hidden = true;
    return;
  }
  const s = p.stats, c = state.colors[id];
  $("#net-cards").innerHTML = [
    card("Floor delay", fmtSec(s.delay_min), `median ${fmtSec(s.delay_median)} · p95 ${fmtSec(s.delay_p95)}`),
    card("Queueing (median)", fmtSec(s.queueing_median), `max delay ${fmtSec(s.delay_max)}`),
    card("Near floor", `${(s.floor_fraction * 100).toFixed(1)} %`, `within ${fmtSec(s.cluster_width)} of floor`),
    card("Offset σ", fmtSec(s.offset_all_std), `floor packets only: ${fmtSec(s.offset_at_floor_std)}`),
    card("Asymmetry indicator", fmtSec(s.asymmetry_indicator), `offset/delay corr ${fmtNum(s.offset_delay_correlation, 2)}`),
  ].join("");
  const q = p.wedge.q, mid = p.wedge.offset.length ? median(p.wedge.offset.slice(0, 50)) : 0;
  makeChart("wedge", $("#chart-wedge"), {
    series: [{ label: "queueing", value: (u, v) => fmtSec(v) }, { label: "offset", stroke: c, paths: () => null, points: { show: true, size: 3, fill: c + "aa", stroke: c + "aa" }, value: (u, v) => fmtSec(v) },
      { label: "±q/2", stroke: css("--muted"), dash: [4, 4], points: { show: false } }, { label: "−q/2", stroke: css("--muted"), dash: [4, 4], points: { show: false } }],
    scales: { x: { time: false } }, cursor: { drag: { x: true, y: true } },
    axes: [axis({ label: "queueing delay (delay − floor)", values: logVals((v) => fmtSec(v, 2)) }), axis({ label: `offset (${p.detrend} detrended)`, size: 70, values: logVals((v) => fmtSec(v, 2)) })],
  }, [q, p.wedge.offset, q.map((v) => mid + v / 2), q.map((v) => mid - v / 2)]);
  makeChart("delay", $("#chart-delay"), {
    series: [{}, { label: "round-trip delay", stroke: c, width: 1, value: (u, v) => fmtSec(v) }], scales: { x: { time: true } },
    axes: [axis(), axis({ label: "delay", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
  }, [p.t, p.delay]);
  makeChart("fpp", $("#chart-fpp"), {
    series: [{}, { label: `FPP (${p.fpp.window} s windows)`, stroke: c, fill: c + "33", width: 1.5, value: (u, v) => (v == null ? "–" : v.toFixed(1) + " %") }],
    scales: { x: { time: true }, y: { range: [0, 100] } }, height: 180, axes: [axis(), axis({ label: "% near floor", size: 70 })],
  }, [p.fpp.t, p.fpp.pct]);
  $("#trace-panel").hidden = !!tr.__error;
  if (!tr.__error) {
    const st = tr.stats;
    $("#trace-cards").innerHTML = [
      card("To reference: floor", fmtSec(st.to_ref?.floor), `p99 PDV ${fmtSec(st.to_ref?.pdv_p99)}`),
      card("From reference: floor", fmtSec(st.from_ref?.floor), `p99 PDV ${fmtSec(st.from_ref?.pdv_p99)}`),
      card("Direction correlation", fmtNum(st.pdv_correlation, 2), `loss ${fmtPct(st.loss)}`),
    ].join("");
    makeChart("trace", $("#chart-trace"), {
      series: [{}, { label: "to reference", stroke: PALETTE[0], width: 1, value: (u, v) => fmtSec(v) }, { label: "from reference", stroke: PALETTE[1], width: 1, value: (u, v) => fmtSec(v) }],
      scales: { x: { time: true } }, height: 190, axes: [axis(), axis({ label: "one-way delay", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
    }, [tr.t, tr.to_ref, tr.from_ref]);
  }
  $("#net-note").textContent = `Offsets ${p.detrend}-detrended. Each exchange's offset error is bounded by half its queueing delay, so points fan out in a wedge; a non-zero asymmetry indicator means queueing is asymmetric on average, which no filter can remove.`;
}
function median(a) { const b = a.filter((v) => v != null).sort((x, y) => x - y); return b.length ? b[Math.floor(b.length / 2)] : 0; }

const EVENT_LABEL = { phase_step: "Phase step", spike: "Spike", frequency_change: "Frequency change", delay_floor_change: "Delay-floor change", leap_smear: "Leap smear" };
async function renderEventsPage(fresh) {
  const r = await api(`/api/events/${state.active}?${params()}`);
  if (!fresh()) return;
  const by = {};
  for (const e of r.events) by[e.kind] = (by[e.kind] || 0) + 1;
  $("#ev-cards").innerHTML = card("Events", String(r.events.length), "robust change detection") + Object.entries(EVENT_LABEL).map(([k, l]) => card(l, String(by[k] || 0))).join("");
  if (!r.events.length) { $("#events").innerHTML = `<p class="note">No steps, spikes, frequency or route changes detected.</p>`; return; }
  $("#events").innerHTML = `<table><tr><th>Time</th><th>Event</th><th>Size</th><th>Score</th><th>Detail</th></tr>${r.events.map((e) => {
    const mag = e.unit === "s/s" ? `${fmtNum(e.magnitude * 1e6, 3)} ppm` : fmtSec(e.magnitude);
    let info = "";
    if (e.detail && e.detail.path_changed !== undefined) info = e.detail.path_changed ? "path changed" : "path unchanged";
    if (e.kind === "delay_floor_change") info = `offset shift ${fmtSec(e.detail.offset_shift)} — ${esc(e.detail.interpretation)}`;
    if (e.kind === "leap_smear") info = `${fmtNum(e.detail.hours, 1)} h`;
    return `<tr class="click" data-t="${e.time}"><td>${fmtDate(e.time)}</td><td>${EVENT_LABEL[e.kind] || esc(e.kind)}</td><td>${mag}</td><td>${Math.round(e.score)}</td><td>${info}</td></tr>`;
  }).join("")}</table><p class="note">Click an event to see it on the offset chart.</p>`;
  $$("#events tr.click").forEach((tr) => tr.addEventListener("click", () => {
    const t = +tr.dataset.t, d = dsById(state.active), span = Math.max(600, ((d?.end ?? t) - (d?.start ?? t)) / 50);
    state.range = { start: t - span, end: t + span };
    updateRangeChip();
    go("analyze/offset");
  }));
}

// ------------------------------------------------------- dynamic heat-map
const VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"];
function heatColor(f) {
  const x = Math.min(0.9999, Math.max(0, f)) * (VIRIDIS.length - 1), i = Math.floor(x), t = x - i, a = VIRIDIS[i], b = VIRIDIS[i + 1];
  const mix = (k) => Math.round(parseInt(a.substr(k, 2), 16) * (1 - t) + parseInt(b.substr(k, 2), 16) * t);
  return `rgb(${mix(1)},${mix(3)},${mix(5)})`;
}
async function renderDynamic(id, kind, fresh) {
  let d;
  try { d = await api(`/api/dynamic/${id}?${params({ kind })}`); } catch (e) { $("#dyn-note").textContent = e.message; return; }
  if (fresh && !fresh()) return;
  const cv = $("#heat"), dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr); ctx.clearRect(0, 0, W, H);
  const L = 70, R = 90, T = 10, B = 34, nx = d.times.length, ny = d.taus.length;
  const vals = d.dev.flat().filter((v) => v != null && v > 0);
  if (!nx || !ny || !vals.length) { $("#dyn-note").textContent = "Not enough data for a sliding window."; return; }
  const lo = Math.log10(Math.min(...vals)), hi = Math.log10(Math.max(...vals)), cw = (W - L - R) / nx, ch = (H - T - B) / ny;
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
    const v = d.dev[i][j];
    if (v == null || !(v > 0)) continue;
    ctx.fillStyle = heatColor(hi > lo ? (Math.log10(v) - lo) / (hi - lo) : 0.5);
    ctx.fillRect(L + i * cw, T + (ny - 1 - j) * ch, Math.ceil(cw) + 0.5, Math.ceil(ch) + 0.5);
  }
  ctx.fillStyle = css("--axis"); ctx.font = `11px ${css("--font")}`; ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let j = 0; j < ny; j++) ctx.fillText(tauAxis(d.taus[j]), L - 6, T + (ny - 1 - j + 0.5) * ch);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  const ticks = Math.min(6, nx);
  for (let k = 0; k < ticks; k++) { const i = Math.round((k * (nx - 1)) / Math.max(1, ticks - 1)); ctx.fillText(new Date(d.times[i] * 1000).toISOString().slice(5, 16).replace("T", " "), L + (i + 0.5) * cw, H - B + 6); }
  for (let k = 0; k < 100; k++) { ctx.fillStyle = heatColor(k / 99); ctx.fillRect(W - R + 20, T + (H - T - B) * (1 - (k + 1) / 100), 14, (H - T - B) / 100 + 1); }
  ctx.fillStyle = css("--axis"); ctx.textAlign = "left"; ctx.textBaseline = "middle";
  const fmtv = TIME_KINDS.has(kind) ? (v) => fmtSec(v, 2) : (v) => v.toExponential(1);
  ctx.fillText(fmtv(10 ** hi), W - R + 38, T + 6); ctx.fillText(fmtv(10 ** lo), W - R + 38, H - B - 6);
  $("#dyn-note").textContent = `${KIND_LABEL[kind]} over ${fmtDur(d.window)} windows every ${fmtDur(d.step)}. Bands of change reveal non-stationarity: route changes, load cycles, temperature.`;
}

// ----- Compare ---------------------------------------------------------------
async function renderCompareTable(fresh) {
  if (!state.datasets.length) { $("#compare-table").innerHTML = `<p class="note">Load two or more datasets to compare them.</p>`; return; }
  const list = state.datasets.slice(0, 40);
  const sums = await Promise.all(list.map((d) => tryApi(`/api/series/${d.id}?max_points=2`)));
  if (!fresh()) return;
  $("#compare-table").innerHTML = `<table><tr><th></th><th class="nm">Dataset</th><th>Format</th><th>Samples</th><th>Start</th><th>Span</th><th>Mean</th><th>RMS</th><th>90 % range</th><th>Trend ppm</th></tr>${list.map((d, i) => {
    const m = sums[i].summary || {};
    return `<tr class="click" data-id="${d.id}"><td><input type="checkbox" ${state.compare.has(d.id) || d.id === state.active ? "checked" : ""} ${d.id === state.active ? "disabled" : ""}></td>
      <td class="nm">${swatch(d.id)}${esc(d.name)}${d.id === state.active ? " <span class='hint'>(active)</span>" : ""}</td><td>${esc(d.format)}</td><td>${d.samples.toLocaleString()}</td><td>${fmtDate(m.start)}</td><td>${fmtDur(m.span_s)}</td>
      <td>${fmtSec(m.mean)}</td><td>${fmtSec(m.rms)}</td><td>${fmtSec(m.range_90)}</td><td>${fmtNum(m.offset_slope_ppm, 4)}</td></tr>`;
  }).join("")}</table>`;
  $$("#compare-table tr.click").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      const id = tr.dataset.id;
      if (e.target.matches("input")) { e.target.checked ? state.compare.add(id) : state.compare.delete(id); renderDatasetList(); renderStatus(); return; }
      selectDataset(id);
    });
  });
}

async function renderReference(fresh) {
  const me = dsById(state.active);
  const overlaps = (d) => me && d.start < me.end && d.end > me.start;
  // datasets that overlap the active one in time first: only those can serve as its reference
  const others = state.datasets.filter((d) => d.id !== state.active).sort((a, b) => overlaps(b) - overlaps(a));
  const sel = $("#ref-select"), prev = sel.value;
  sel.innerHTML = others.map((d) => `<option value="${d.id}">${esc(d.name)}${overlaps(d) ? "" : " (no overlap)"}</option>`).join("");
  if (!others.length) { $("#ref-cards").innerHTML = card("Reference", "–", "load a second dataset (PPS, GNSS or a better server)"); return; }
  sel.value = others.some((d) => d.id === prev) ? prev : others[0].id;
  const r = overlaps(dsById(sel.value)) ? await tryApi(`/api/compare/${state.active}?${params({ ref: sel.value })}`)
    : { __error: "the two datasets do not overlap in time; pick a reference recorded over the same period" };
  if (!fresh()) return;
  if (r.__error) {
    $("#ref-cards").innerHTML = card("Cannot compare", "–", esc(r.__error));
    for (const k of ["ref-diff", "ref-stab"]) { dropChart(k); $(`#chart-${k}`).innerHTML = ""; }
    return;
  }
  const s = r.stats;
  $("#ref-cards").innerHTML = [card("Bias", fmtSec(s.bias), `${s.samples} common samples`), card("RMS", fmtSec(s.rms), `σ ${fmtSec(s.std)}`),
    card("95 % |error|", fmtSec(s.p95_abs)), card("max |error|", fmtSec(s.max_abs))].join("");
  makeChart("ref-diff", $("#chart-ref-diff"), {
    series: [{}, { label: `${r.name} − ${r.ref}`, stroke: state.colors[state.active], width: 1.2, value: (u, v) => fmtSec(v) }],
    scales: { x: { time: true } }, axes: [axis(), axis({ label: "difference", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
  }, [r.t, r.diff]);
  const st = r.stability.filter((x) => x.taus.length);
  if (st.length) {
    const tables = st.map((x) => [x.taus, x.dev]);
    makeChart("ref-stab", $("#chart-ref-stab"), {
      series: [{ value: (u, v) => (v == null ? "–" : tauFmt(v)) }].concat(st.map((x) => ({ label: KIND_LABEL[x.kind], stroke: KIND_COLOR[x.kind], width: 1.6, points: { show: true, size: 4, fill: KIND_COLOR[x.kind] }, value: (u, v) => fmtSec(v) }))),
      scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
      axes: [axis({ label: "τ", values: logVals(tauAxis) }), axis({ label: "time [s]", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
    }, tables.length === 1 ? tables[0] : uPlot.join(tables));
  }
}

async function renderHat(fresh) {
  const ids = selectedIds();
  if (ids.length < 3) {
    dropChart("hat"); $("#chart-hat").innerHTML = "";
    $("#hat-table").innerHTML = "";
    $("#hat-note").textContent = `Tick ${3 - ids.length} more dataset${ids.length === 2 ? "" : "s"} in the list: the cornered hat needs three or more sources measured against each other.`;
    return;
  }
  const r = await api(`/api/hat?${new URLSearchParams({ ids: ids.join(","), method: $("#hat-method").value })}`);
  if (!fresh()) return;
  const names = r.names, tables = [], series = [{ label: "τ", value: (u, v) => (v == null ? "–" : tauFmt(v)) }], bands = [];
  names.forEach((n, i) => {
    const s = r.sources[n], c = state.colors[ids[i]] || PALETTE[i % PALETTE.length];
    tables.push([r.taus, s.adev]); series.push({ label: dsName(ids[i]), stroke: c, width: 1.8, points: { show: true, size: 5, fill: c }, value: (u, v) => fmtExp(v) });
    tables.push([r.taus, s.hi]); series.push({ label: "hi", stroke: "transparent", points: { show: false }, _aux: true });
    tables.push([r.taus, s.lo]); series.push({ label: "lo", stroke: "transparent", points: { show: false }, _aux: true });
    bands.push({ series: [series.length - 2, series.length - 1], fill: c + "22" });
  });
  const u = makeChart("hat", $("#chart-hat"), {
    series, bands, scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
    axes: [axis({ label: "averaging time τ", values: logVals(tauAxis) }), axis({ label: "individual ADEV", size: 72, values: logVals((v) => v.toExponential(0)) })],
  }, uPlot.join(tables));
  hideLegend(u, (s) => s._aux);
  $("#hat-table").innerHTML = `<table><tr><th>τ</th>${names.map((n, i) => `<th>${swatch(ids[i])}${esc(dsName(ids[i]))}</th>`).join("")}</tr>${r.taus.map((t, k) => `<tr><td>${tauFmt(t)}</td>${names.map((n) => {
    const s = r.sources[n];
    return `<td class="${s.negative[k] ? "fail" : ""}" title="${s.negative[k] ? "negative variance estimate: not resolvable at this τ" : ""}">${fmtExp(s.adev[k])}</td>`;
  }).join("")}</tr>`).join("")}</table>`;
  $("#hat-note").textContent = `${r.method === "gcov" ? "Groslambert covariance" : "N-cornered hat"} over the common span; bands are ${Math.round((r.ci || 0.683) * 100)} % intervals. Red cells: negative variance estimates (the source is too quiet to resolve at that τ).`;
}

// ----- Comply ----------------------------------------------------------------
async function renderTimeErrorPage(fresh) {
  const te = await api(`/api/timeerror/${state.active}?${params({ series: 1, lpf_hz: $("#te-lpf").value, cte_window: $("#te-win").value })}`);
  if (!fresh()) return;
  const last = (x) => (x && x.dev && x.dev.length ? x.dev[x.dev.length - 1] : null);
  $("#te-full-cards").innerHTML = [
    card("max|TE|", fmtSec(te.max_abs_te), "unfiltered"), card("cTE", fmtSec(te.cte), "whole record"),
    card(`max |cTE| (${fmtDur(te.cte_window_s)})`, fmtSec(te.max_abs_cte_window), `${te.cte_windows.length} windows`),
    card("max|TEL|", fmtSec(te.max_abs_tel), `${te.lpf_hz} Hz low-pass`),
    card("dTE_L p-p", fmtSec(te.dte_l_pp), `MTIE ${fmtSec(last(te.dte_l_mtie))}`), card("dTE_H p-p", fmtSec(te.dte_h_pp), te.dte_h_pp == null || !isFinite(te.dte_h_pp) ? "sampling too slow to separate" : "high-pass part"),
  ].join("");
  makeChart("te", $("#chart-te"), {
    series: [{}, { label: "TE", stroke: state.colors[state.active], width: 1, value: (u, v) => fmtSec(v) }, { label: "TEL", stroke: css("--text"), width: 1.6, value: (u, v) => fmtSec(v) }],
    scales: { x: { time: true } }, axes: [axis(), axis({ label: "TE = local − reference", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
  }, [te.t, te.te, te.tel]);
  const curves = [te.dte_l_mtie, te.dte_l_tdev].filter((x) => x && x.taus.length);
  if (curves.length) {
    makeChart("te-mtie", $("#chart-te-mtie"), {
      series: [{ value: (u, v) => (v == null ? "–" : tauFmt(v)) }].concat(curves.map((x) => ({ label: KIND_LABEL[x.kind], stroke: KIND_COLOR[x.kind], width: 1.6, points: { show: true, size: 4, fill: KIND_COLOR[x.kind] }, value: (u, v) => fmtSec(v) }))),
      scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
      axes: [axis({ label: "observation interval τ", values: logVals(tauAxis) }), axis({ label: "time [s]", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
    }, curves.length === 1 ? [curves[0].taus, curves[0].dev] : uPlot.join(curves.map((x) => [x.taus, x.dev])));
  }
  $("#te-full-note").textContent = (te.warnings || []).join(" ") || "Definitions of ITU-T G.8260. Check limits and masks in CI with: ntpstats timeerror FILE --limits LIMITS --mask MASK (exit code 3 on failure).";
}

function auditParams() {
  return params({ limit: $("#au-limit").value, window: $("#au-window").value, reference_uncertainty: $("#au-ref").value, asymmetry: $("#au-asym").value });
}
async function renderAudit(fresh) {
  const r = await api(`/api/audit/${state.active}?${auditParams()}`);
  if (!fresh()) return;
  const s = r.summary;
  $("#au-verdict").innerHTML = verdict(s.passed, s.passed
    ? `The error bound to UTC stayed within ${fmtSec(r.limit)} in every ${fmtDur(r.window)} window.`
    : `${s.failing_windows} of ${s.windows} windows exceed ${fmtSec(r.limit)}${s.insufficient_windows ? ` and ${s.insufficient_windows} have too little data` : ""}.`);
  $("#au-cards").innerHTML = [
    card("Coverage", fmtPct(s.coverage), `unmonitored ${fmtDur(s.unmonitored_s)}`),
    card("Within limit", fmtPct(s.within_limit_fraction_of_monitored), "of the monitored time", s.within_limit_fraction_of_monitored >= 1 ? "pass" : "fail"),
    card("Max bound", fmtSec(s.max_bound), `median ${fmtSec(s.median_bound)}`),
    card("p99 bound", fmtSec(s.p99_bound)),
    card("Windows", `${s.windows - s.failing_windows} / ${s.windows}`, "passing"),
  ].join("");
  const lim = r.limit;
  const far = lim > 4 * 1.25 * Math.max(...r.offset.map((x, i) => Math.abs(x) + r.bound[i]).filter(isFinite));
  if (far) $("#au-cards").insertAdjacentHTML("beforeend", card("Limit", fmtSec(lim), "far above the bound: not drawn"));
  const auSeries = [{}, { label: "+bound", stroke: PALETTE[1], width: 1.2, value: (u, v) => fmtSec(v) }, { label: "−bound", stroke: PALETTE[1], width: 1.2, value: (u, v) => fmtSec(v) },
    { label: "offset", stroke: state.colors[state.active], width: 1, value: (u, v) => fmtSec(v) }];
  const auData = [r.t, r.offset.map((x, i) => x + r.bound[i]), r.offset.map((x, i) => x - r.bound[i]), r.offset];
  if (!far) {
    auSeries.push({ label: `limit ±${fmtSec(lim)}`, stroke: css("--bad"), dash: [6, 4], width: 1 }, { label: "−limit", stroke: css("--bad"), dash: [6, 4], width: 1, _aux: true });
    auData.push(r.t.map(() => lim), r.t.map(() => -lim));
  }
  const au = makeChart("audit", $("#chart-audit"), {
    series: auSeries,
    bands: [{ series: [1, 2], fill: PALETTE[1] + "1c" }],
    scales: { x: { time: true }, y: { range: () => { const m = 1.25 * Math.max(...r.offset.map((x, i) => Math.abs(x) + r.bound[i]).filter(isFinite)); const y = lim <= 4 * m ? Math.max(m, 1.1 * lim) : m; return [-y, y]; } } },
    axes: [axis(), axis({ label: "s", size: 70, values: logVals((v) => fmtSec(v, 2)) })],
  }, auData);
  hideLegend(au, (x) => x._aux);
  $("#au-rules").innerHTML = `<dl class="kvlist">${Object.entries(r.rules).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}${(r.notes || []).map((n) => `<dt>note</dt><dd>${esc(n)}</dd>`).join("")}</dl>`;
  $("#au-worst").innerHTML = `<table><tr><th>Time</th><th>Bound</th><th>Offset</th><th>Path</th><th>Upstream</th></tr>${r.worst.slice(0, 8).map((w) => `<tr><td>${fmtDate(w.time)}</td><td>${fmtSec(w.bound)}</td><td>${fmtSec(w.offset)}</td><td>${fmtSec(w.path)}</td><td>${fmtSec(w.upstream)}</td></tr>`).join("")}</table>`;
  $("#au-windows").innerHTML = `<table><tr><th>Start</th><th>Samples</th><th>Coverage</th><th>Max bound</th><th>Max |offset|</th><th>Status</th></tr>${r.windows.map((w) => `<tr><td>${fmtDate(w.start)}</td><td>${w.samples}</td><td>${fmtPct(w.coverage)}</td><td>${fmtSec(w.max_bound)}</td><td>${fmtSec(w.max_abs_offset)}</td><td class="${w.status === "pass" ? "pass" : "fail"}">${esc(w.status)}</td></tr>`).join("")}</table>`;
}

// ----- Lab -------------------------------------------------------------------
async function renderBenchForm() {
  if (!state.estimators) state.estimators = await api("/api/estimators");
  const d = dsById(state.active);
  const traceOk = d && d.columns.includes("delay");
  const scen = state.estimators.presets.map((p) => [p, p]).concat(traceOk ? [[`trace:${d.id}`, `trace: ${d.name}`]] : []);
  for (const k of [...state.bench.scenarios]) if (k.startsWith("trace:") && !scen.some(([v]) => v === k)) state.bench.scenarios.delete(k);
  $("#bench-scenarios").innerHTML = scen.map(([v, l]) => `<button data-v="${esc(v)}" class="${state.bench.scenarios.has(v) ? "on" : ""}" title="${v.startsWith("trace:") ? "replay the delays of this dataset under a simulated clock" : "preset scenario"}">${esc(l)}</button>`).join("");
  $("#bench-estimators").innerHTML = state.estimators.estimators.map((e) => `<button data-v="${esc(e.name)}" class="${state.bench.estimators.has(e.name) ? "on" : ""}" title="${esc(e.description)}${e.multi ? " (multi-server)" : ""}">${esc(e.name)}</button>`).join("");
}
async function runBench() {
  const body = { scenarios: [...state.bench.scenarios], estimators: [...state.bench.estimators], seeds: [...Array(Math.max(1, +$("#bench-seeds").value || 1)).keys()].map((k) => k + 1), duration: (+$("#bench-hours").value || 12) * 3600 };
  if (!body.scenarios.length || !body.estimators.length) return toast("pick at least one scenario and one estimator", true);
  $("#bench-table").innerHTML = `<p class="note">Running ${body.scenarios.length} scenario(s) × ${body.estimators.length} estimator(s) × ${body.seeds.length} seed(s)…</p>`;
  const r = await api("/api/bench", { method: "POST", body });
  const groups = {};
  for (const row of r.table) (groups[row.scenario] ??= []).push(row);
  const all = r.table.map((x) => x.rms).filter((v) => v > 0);
  const lo = Math.log10(Math.min(...all)), hi = Math.log10(Math.max(...all));
  const w = (v) => (v > 0 && hi > lo ? 6 + 94 * (Math.log10(v) - lo) / (hi - lo) : 50);
  $("#bench-table").innerHTML = Object.entries(groups).map(([sc, rows]) => {
    rows.sort((a, b) => a.rms - b.rms);
    return `<h3>${esc(sc)}</h3><table><tr><th>Estimator</th><th>RMS</th><th style="width:30%"></th><th>± seeds</th><th>Bias</th><th>p95 |e|</th><th>max |e|</th><th>MTIE 1 h</th><th>Time</th></tr>${rows.map((x, i) => `<tr><td class="${i ? "" : "best"}">${esc(x.estimator)}</td><td class="${i ? "" : "best"}">${fmtSec(x.rms)}</td>
      <td><span class="bar" style="width:${w(x.rms).toFixed(1)}%;${i ? "" : "background:var(--good)"}"></span></td><td>${fmtSec(x.rms_std)}</td><td>${fmtSec(x.bias)}</td><td>${fmtSec(x.p95_abs)}</td><td>${fmtSec(x.max_abs)}</td><td>${fmtSec(x.mtie_1h)}</td><td>${fmtSec(x.runtime_s, 2)}</td></tr>`).join("")}</table>`;
  }).join("");
}

async function runChain() {
  const body = {
    hops: +$("#ch-hops").value, servo: $("#ch-servo").value, sync_rate: +$("#ch-rate").value, duration: +$("#ch-dur").value,
    asymmetry_spread: parseTime($("#ch-asym").value) || 0, pdv: parseTime($("#ch-pdv").value) || null,
    kp: $("#ch-kp").value || null, ki: $("#ch-ki").value || null, cls: $("#ch-class").value, budget: parseTime($("#ch-budget").value) || 1.1e-6, seed: 1,
  };
  $("#ch-verdict").innerHTML = `<p class="note">Simulating ${body.hops} boundary clocks…</p>`;
  const r = await api("/api/chain", { method: "POST", body });
  const v = r.verdict, b = v.budget;
  $("#ch-verdict").innerHTML = verdict(v.passed, `End of chain max|TE| ${fmtSec(b.value)} against a ${fmtSec(b.limit)} budget (margin ${fmtSec(b.margin)}); ${v.hops_passed ? "every hop within" : "some hops exceed"} class ${esc(v.class || "")} limits.`);
  const nodes = r.nodes.map((n) => n.node);
  makeChart("chain", $("#chart-chain"), {
    series: [{ label: "node", value: (u, x) => (x == null ? "–" : `node ${x}`) },
      { label: "max|TE|", stroke: PALETTE[3], width: 2, points: { show: true, size: 6, fill: PALETTE[3] }, value: (u, x) => fmtSec(x) },
      { label: "|cTE|", stroke: PALETTE[0], width: 1.5, points: { show: true, size: 4, fill: PALETTE[0] }, value: (u, x) => fmtSec(x) },
      { label: "dTE_L MTIE", stroke: PALETTE[2], width: 1.5, points: { show: true, size: 4, fill: PALETTE[2] }, value: (u, x) => fmtSec(x) },
      { label: `budget ${fmtSec(b.limit)}`, stroke: css("--bad"), dash: [6, 4], width: 1.2, points: { show: false } }],
    scales: { x: { time: false }, y: { distr: 3 } },
    axes: [axis({ label: "boundary clock (hop)" }), axis({ label: "time error", size: 70, values: logVals((x) => fmtSec(x, 2)) })],
  }, [nodes, r.nodes.map((n) => n.max_te), r.nodes.map((n) => Math.abs(n.cte) || null), r.nodes.map((n) => n.dte_l_mtie), nodes.map(() => b.limit)]);
  const show = [...new Set([1, Math.ceil(nodes.length / 2), nodes.length])];
  makeChart("chain-te", $("#chart-chain-te"), {
    series: [{ label: "t", value: (u, x) => (x == null ? "–" : fmtDur(x)) }].concat(show.map((n, i) => ({ label: `node ${n}`, stroke: PALETTE[i], width: 1, value: (u, x) => fmtSec(x) }))),
    scales: { x: { time: false } }, axes: [axis({ label: "time since start [s], after the warm-up" }), axis({ label: "TE (local − GM)", size: 70, values: logVals((x) => fmtSec(x, 2)) })],
  }, (() => { const k = r.t.findIndex((x) => x >= r.warmup); return [r.t.slice(k)].concat(show.map((n) => r.te[String(n)].slice(k))); })());
  const bad = new Set(v.checks.filter((c) => !c.passed).map((c) => `${c.hop}:${c.metric}`));
  const cell = (hop, m, val) => `<td class="${bad.has(`${hop}:${m}`) ? "fail" : ""}">${fmtSec(val)}</td>`;
  $("#ch-table").innerHTML = `<table><tr><th>Node</th><th>Asymmetry</th><th>max|TE|</th><th>|cTE|</th><th>dTE_L MTIE</th><th>dTE_H p-p</th><th>Hop adds max|TE|</th><th>Hop |cTE|</th><th>Hop dTE_L MTIE</th></tr>${r.nodes.map((n, i) => {
    const h = r.per_hop[i];
    return `<tr><td>${n.node}</td><td>${fmtSec(h.asymmetry)}</td><td>${fmtSec(n.max_te)}</td><td>${fmtSec(Math.abs(n.cte))}</td><td>${fmtSec(n.dte_l_mtie)}</td><td>${fmtSec(n.dte_h_pp)}</td>${cell(h.hop, "max_te", h.max_te)}${cell(h.hop, "cte", Math.abs(h.cte))}${cell(h.hop, "dte_l_mtie", h.dte_l_mtie)}</tr>`;
  }).join("")}</table>`;
  $("#ch-note").textContent = `${r.servo} servo at ${r.sync_rate} Sync/s; first ${fmtDur(r.warmup)} excluded (servo locking${r.lock_time > r.warmup ? `; these settings need about ${fmtDur(r.lock_time)}: run longer` : ""}). Red cells exceed the per-hop class limits. A model of linuxptp-style servos, not of a particular product.`;
}

// ----- Live ------------------------------------------------------------------
async function renderLive() {
  const off = state.info && state.info.live === false;
  $("#live-unavailable").hidden = !off;
  $$("#live-form button, #live-form input, #live-form select").forEach((el) => (el.disabled = off));
  if (!off) pollLive();
}
async function pollLive() {
  try {
    const st = await api("/api/monitor");
    state.live = st;
    $("#live-dot").classList.toggle("on", st.running);
    $("#live-status").textContent = st.running
      ? `Running: ${st.servers.join(", ")} every ${st.interval} s, ${st.samples} samples so far.` + (st.log.length ? ` Last error: ${st.log[st.log.length - 1]}` : "")
      : st.log.length ? `Stopped. ${st.log[st.log.length - 1]}` : "Not running.";
    if (st.running) {
      const before = dsById(st.id)?.samples;
      await refreshDatasets();
      if (state.active === st.id && dsById(st.id)?.samples !== before && dsById(st.id)?.samples >= 3 && !state.page.startsWith("live/")) render();
    }
  } catch (e) { /* server gone */ }
}

// ---------------------------------------------------------- command palette
function commands() {
  const cmds = [];
  for (const [ws, w] of Object.entries(WORKSPACES)) for (const [p, label] of w.pages) cmds.push({ group: w.label, label, hint: `#/${ws}/${p}`, run: () => go(`${ws}/${p}`) });
  for (const d of state.datasets) cmds.push({ group: "Dataset", label: d.name, hint: `${d.format} · ${d.samples} pts`, run: () => selectDataset(d.id) });
  cmds.push({ group: "Action", label: "Open files…", hint: "O", run: () => $("#file-input").click() });
  for (const p of ["internet", "lan", "congested", "route-change", "falseticker", "ptp-lan", "ptp-tc"]) cmds.push({ group: "Action", label: `Simulate ${p}`, hint: "Lab", run: () => simulate(p) });
  // shown only when asked for ("format …"), so the dozens of formats do not crowd other results
  for (const o of $$("#format option")) cmds.push({ group: "Input format", label: `Format: ${o.textContent}`, hint: o.value, onlyFor: "format", run: () => { $("#format").value = o.value; toast(`Next files are read as ${o.textContent}`); } });
  cmds.push({ group: "Action", label: "Download HTML report of the active dataset", run: () => reportDownload() });
  cmds.push({ group: "Action", label: "Download audit evidence report", run: () => state.active && download(`/api/export/${state.active}/audit.html?${auditParams()}`) });
  cmds.push({ group: "Action", label: "Export offset CSV", run: () => state.active && download(`/api/export/${state.active}/series.csv?${params()}`) });
  cmds.push({ group: "Action", label: "Toggle light / dark theme", hint: "T", run: toggleTheme });
  cmds.push({ group: "Action", label: "Show / hide datasets panel", hint: "D", run: toggleSide });
  cmds.push({ group: "Action", label: "Keyboard shortcuts", hint: "?", run: () => $("#help").showModal() });
  if (state.range) cmds.push({ group: "Action", label: "Analyse the whole dataset (clear range)", run: clearRange });
  return cmds;
}
function score(q, text) {  // subsequence match; consecutive and word-start hits score higher
  if (!q) return 1;
  let s = 0, j = 0, run = 0;
  const t = text.toLowerCase();
  for (const ch of q.toLowerCase()) {
    const k = t.indexOf(ch, j);
    if (k < 0) return 0;
    run = k === j ? run + 1 : 1;
    s += run + (k === 0 || /\W/.test(t[k - 1]) ? 3 : 0);
    j = k + 1;
  }
  return s;
}
let palItems = [], palSel = 0;
function openPalette() {
  const dlg = $("#palette");
  $("#palette-input").value = "";
  drawPalette();
  dlg.showModal();
  $("#palette-input").focus();
}
function drawPalette() {
  const q = $("#palette-input").value.trim();
  const rank = (c) => {  // label matches beat group matches; a label that starts with the query wins
    const l = score(q, c.label);
    if (l) return 2 * l + (c.label.toLowerCase().startsWith(q.toLowerCase()) ? 25 : 0);
    return score(q, `${c.group} ${c.label}`);
  };
  const asked = (c) => !c.onlyFor || q.toLowerCase().startsWith(c.onlyFor.slice(0, Math.max(3, Math.min(q.length, c.onlyFor.length))));
  palItems = commands().filter(asked).map((c) => ({ c, s: rank(c) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 40).map((x) => x.c);
  palSel = 0;
  renderPalList();
}
function renderPalList() {
  $("#palette-list").innerHTML = palItems.map((c, i) => `<li class="${i === palSel ? "sel" : ""}" data-i="${i}"><span class="grp">${esc(c.group)}</span><span>${esc(c.label)}</span><small>${esc(c.hint || "")}</small></li>`).join("") || `<li><span class="hint">No match</span></li>`;
  $("#palette-list .sel")?.scrollIntoView({ block: "nearest" });
}
function runPalette(i) {
  const c = palItems[i];
  $("#palette").close();
  $("#palette-input").blur();  // give the keyboard back to the page shortcuts
  if (c) c.run();
}

// ------------------------------------------------------------------- wiring
function toggleTheme() {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("ntpstats-theme", document.documentElement.dataset.theme); } catch { /* private mode */ }
  render();
}
function toggleSide() {
  document.body.classList.toggle("noside");
  try { localStorage.setItem("ntpstats-side", document.body.classList.contains("noside") ? "0" : "1"); } catch { /* */ }
  setTimeout(() => ro.disconnect() || $$(".chart").forEach((el) => ro.observe(el)), 0);
}
function clearRange() { state.range = null; updateRangeChip(); render(); }
function reportDownload() {
  if (!state.active) return toast("select a dataset first", true);
  download(`/api/export/${state.active}/report.html?${params({ kinds: [...state.kinds].filter((k) => k !== "mtie").join(",") || "oadev", ci: $("#ci").value })}`);
}
function cycleDataset(delta) {
  if (!state.datasets.length) return;
  const i = state.datasets.findIndex((d) => d.id === state.active);
  selectDataset(state.datasets[(i + delta + state.datasets.length) % state.datasets.length].id);
}

function init() {
  try {
    const saved = localStorage.getItem("ntpstats-theme");
    if (saved) document.documentElement.dataset.theme = saved;
    const side = localStorage.getItem("ntpstats-side");
    if (side === "0" || (side === null && matchMedia("(max-width: 760px)").matches)) document.body.classList.add("noside");
  } catch { /* private mode */ }

  api("/api/info").then((i) => {
    state.info = i;
    $("#version").textContent = "v" + i.version;
    $("#edition").textContent = i.live === false ? "in your browser" : "";
    $("#live-unavailable").hidden = i.live !== false;
    if (i.formats) $("#format").innerHTML = `<option value="auto">auto-detect</option>` + i.formats.map((f) => `<option value="${esc(f.name)}">${esc(f.description)}</option>`).join("");
    $("#kinds").innerHTML = Object.keys(i.kinds).map((k) => `<button data-kind="${k}" title="${esc(i.kinds[k])}" class="${state.kinds.has(k) ? "on" : ""}">${KIND_LABEL[k] || k}</button>`).join("");
  });

  $$(".rail button").forEach((b) => b.addEventListener("click", () => go(b.dataset.ws)));
  addEventListener("hashchange", route);
  $("#kinds").addEventListener("click", (e) => {
    const k = e.target.dataset.kind;
    if (!k) return;
    state.kinds.has(k) ? state.kinds.delete(k) : state.kinds.add(k);
    e.target.classList.toggle("on");
    render();
  });
  for (const id of ["detrend", "outliers", "overlay", "aux", "taus", "ci", "slopes", "bins", "dyn", "noisefit", "sp-kind", "sp-method", "sp-carrier", "ho-horizon", "ho-limits", "ho-model", "ho-source",
    "ref-select", "hat-method", "te-lpf", "te-win", "au-limit", "au-window", "au-ref", "au-asym"]) $(`#${id}`).addEventListener("change", render);
  $("#mask-chip").addEventListener("click", () => { state.mask = null; $("#mask-label").textContent = "Mask…"; render(); });
  $("#mask-input").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      state.mask = await api("/api/mask", { method: "POST", body: await f.text(), headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "text/plain" } });
      $("#mask-label").textContent = `Mask: ${state.mask.name}`;
      render();
    } catch (err) { toast(err.message, true); }
  });
  $("#file-input").addEventListener("change", (e) => { uploadFiles([...e.target.files]); e.target.value = ""; });
  $("#ds-filter").addEventListener("input", (e) => { state.filter = e.target.value; renderDatasetList(); });
  $$("[data-export]").forEach((b) => b.addEventListener("click", () => exportPng(b.dataset.export)));
  $$("[data-expand]").forEach((b) => b.addEventListener("click", () => {
    const p = b.closest(".panel");
    p.classList.toggle("expanded");
    requestAnimationFrame(() => $$(".chart", p).forEach((el) => { const u = Object.values(state.charts).find((c) => c.root.parentElement === el); if (u) u.setSize({ width: Math.max(280, el.clientWidth - 16), height: chartHeight(el) }); }));
  }));
  $$("[data-csv]").forEach((b) => b.addEventListener("click", () => {
    if (!state.active) return;
    const extra = b.dataset.csv === "stability.csv" ? { kinds: [...state.kinds].join(","), taus: $("#taus").value, ci: $("#ci").value } : {};
    download(`/api/export/${state.active}/${b.dataset.csv}?${params(extra)}`);
  }));
  $("#au-report").addEventListener("click", () => state.active && download(`/api/export/${state.active}/audit.html?${auditParams()}`));
  $("#apply-zoom").addEventListener("click", () => { state.range = state.zoom; state.zoom = null; $("#apply-zoom").hidden = true; updateRangeChip(); render(); });
  $("#range-chip").addEventListener("click", clearRange);
  $("#theme").addEventListener("click", toggleTheme);
  $("#toggle-side").addEventListener("click", toggleSide);
  $("#help-btn").addEventListener("click", () => $("#help").showModal());
  $("#palette-btn").addEventListener("click", openPalette);
  $("#palette-input").addEventListener("input", drawPalette);
  $("#palette-input").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); palSel = (palSel + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) % Math.max(1, palItems.length); renderPalList(); }
    if (e.key === "Enter") { e.preventDefault(); runPalette(palSel); }
  });
  $("#palette-list").addEventListener("click", (e) => { const li = e.target.closest("li[data-i]"); if (li) runPalette(+li.dataset.i); });
  $("#palette").addEventListener("click", (e) => { if (e.target === $("#palette")) $("#palette").close(); });

  // Lab
  $$("[data-demo]").forEach((b) => b.addEventListener("click", () => simulate(b.dataset.demo, 24, 1)));
  $$("#presets [data-preset]").forEach((b) => b.addEventListener("click", () => simulate(b.dataset.preset, +$("#sim-hours").value || 24, +$("#sim-seed").value || 1)));
  for (const [el, key] of [["#bench-scenarios", "scenarios"], ["#bench-estimators", "estimators"]]) {
    $(el).addEventListener("click", (e) => {
      const v = e.target.dataset.v;
      if (!v) return;
      const set = state.bench[key];
      set.has(v) ? set.delete(v) : set.add(v);
      e.target.classList.toggle("on");
    });
  }
  $("#bench-run").addEventListener("click", () => runBench().catch((e) => { toast(e.message, true); $("#bench-table").innerHTML = ""; }));
  $("#ch-run").addEventListener("click", () => runChain().catch((e) => { toast(e.message, true); $("#ch-verdict").innerHTML = ""; }));
  $("#trace-to-bench").addEventListener("click", () => { if (state.active) state.bench.scenarios.add(`trace:${state.active}`); });

  // Live
  $("#live-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const action = e.submitter?.value, f = new FormData(e.target);
    try {
      if (action === "query") {
        const server = String(f.get("servers")).split(/[\s,]+/)[0];
        const r = await api("/api/query", { method: "POST", body: { server, version: +f.get("version") } });
        $("#query-result").textContent = `${r.server} (${r.address})  NTPv${r.version}  stratum ${r.stratum}  ${r.version === 5 ? `timescale ${r.timescale} era ${r.era}` : `refid ${r.refid}`}\noffset ${fmtSec(r.offset)}   delay ${fmtSec(r.delay)}\nroot delay ${fmtSec(r.root_delay)}   root disp ${fmtSec(r.root_dispersion)}   leap ${r.leap}`;
      } else if (action === "start") {
        const r = await api("/api/monitor/start", { method: "POST", body: { source: f.get("source"), servers: f.get("servers"), interval: +f.get("interval"), version: +f.get("version") } });
        await refreshDatasets(r.id);
        toast(`Monitoring ${r.servers.join(", ")}`);
      } else if (action === "stop") await api("/api/monitor/stop", { method: "POST", body: {} });
      pollLive();
    } catch (err) { toast(err.message, true); }
  });

  // keyboard
  addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (e.target.matches("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey || $("dialog[open]")) return;
    const k = e.key;
    if (k >= "1" && k <= "5") go(WS_ORDER[+k - 1]);
    else if (k === "[") stepPage(-1);
    else if (k === "]") stepPage(1);
    else if (k === "j") cycleDataset(1);
    else if (k === "k") cycleDataset(-1);
    else if (k === "/") { e.preventDefault(); if (document.body.classList.contains("noside")) toggleSide(); $("#ds-filter").focus(); }
    else if (k === "o") $("#file-input").click();
    else if (k === "d") toggleSide();
    else if (k === "t") toggleTheme();
    else if (k === "?") $("#help").showModal();
    else if (k === "Escape") {
      const ex = $(".panel.expanded");
      if (ex) { ex.classList.remove("expanded"); render(); } else if (state.range) clearRange();
    }
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
  refreshDatasets().then(route);
  setInterval(() => { if (state.live?.running) pollLive(); }, 5000);
}

document.addEventListener("DOMContentLoaded", init);
