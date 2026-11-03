// ntpstats in-browser edition: routes the UI's /api requests to the Pyodide worker instead of a server.
"use strict";
(function () {
  const cfg = window.NTPSTATS_CONFIG || {};
  const worker = new Worker("static/worker.js", { type: "module" });
  const pending = new Map();
  let seq = 0;
  let readyResolve, readyReject;
  const ready = new Promise((res, rej) => { readyResolve = res; readyReject = rej; });

  const banner = document.createElement("div");
  banner.id = "boot";
  banner.className = "boot";
  banner.innerHTML = `<b>ntpstats in your browser</b> — <span id="boot-text">starting…</span>
    <small>First visit downloads about 15 MB (Python and numpy, then cached). Files you open are analysed
    in this page and never uploaded.</small>`;
  document.addEventListener("DOMContentLoaded", () => document.body.prepend(banner));

  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === "progress") {
      const t = document.getElementById("boot-text");
      if (t) t.textContent = m.text;
    } else if (m.type === "ready") {
      banner.remove();
      readyResolve(m.version);
    } else if (m.type === "fatal") {
      const t = document.getElementById("boot-text");
      if (t) t.textContent = "could not start: " + m.text;
      readyReject(new Error(m.text));
    } else if (m.type === "reply") {
      const p = pending.get(m.id);
      pending.delete(m.id);
      const bin = atob(m.body);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      p.resolve({ status: m.status, contentType: m.ctype || "", headers: m.headers || {}, bytes });
    }
  };
  worker.onerror = (e) => {
    const t = document.getElementById("boot-text");
    if (t) t.textContent = "could not start: " + (e.message || "worker error");
    readyReject(new Error(e.message || "worker error"));
  };
  worker.postMessage({ type: "boot", wheel: cfg.wheel, pyodide: cfg.pyodide });

  async function toBytes(body) {
    if (body == null) return null;
    if (typeof body === "string") return new TextEncoder().encode(body);
    if (body instanceof ArrayBuffer) return new Uint8Array(body);
    if (body instanceof Blob) return new Uint8Array(await body.arrayBuffer());
    return new TextEncoder().encode(String(body));
  }

  window.NTPSTATS_BROWSER = true;
  window.NTPSTATS_READY = ready;
  // transport(method, path, headers, body) -> {status, contentType, headers, bytes}
  window.NTPSTATS_TRANSPORT = async (method, path, headers, body) => {
    await ready;
    const id = ++seq;
    const bytes = await toBytes(body);
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      worker.postMessage({ type: "call", id, method, path, headers, body: bytes }, bytes ? [bytes.buffer] : []);
    });
  };
})();
