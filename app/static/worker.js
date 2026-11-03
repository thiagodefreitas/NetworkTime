// ntpstats in-browser edition: a module Web Worker running the ntpstats API under Pyodide (WebAssembly).
// Files never leave the page: the worker parses and analyses them locally.
const PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";

let ready = null;

async function boot(wheel, base) {
  const PYODIDE = new URL(base || PYODIDE_CDN, self.location.href).href;
  postMessage({ type: "progress", text: "loading Python (Pyodide)…" });
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");  // a failure is reported as fatal below
  const py = await loadPyodide({ indexURL: PYODIDE });
  postMessage({ type: "progress", text: "loading numpy…" });
  await py.loadPackage(["numpy", "micropip"]);
  postMessage({ type: "progress", text: "installing ntpstats…" });
  const micropip = py.pyimport("micropip");
  await micropip.install(new URL(wheel, self.location.href).href, { deps: false });
  py.runPython(`
import base64, json
from ntpstats.web.server import dispatch

def _call(method, path, headers_json, body):
    raw = bytes(body.to_py()) if hasattr(body, "to_py") else b""  # JS null arrives as JsNull
    r = dispatch(method, path, json.loads(headers_json), raw)
    return json.dumps({"status": r.status, "ctype": r.content_type, "headers": r.headers,
                       "body": base64.b64encode(r.body).decode()})
`);
  postMessage({ type: "ready", version: py.runPython("import ntpstats; ntpstats.__version__") });
  return py.globals.get("_call");
}

self.onmessage = async (ev) => {
  const m = ev.data;
  if (m.type === "boot") {
    ready = boot(m.wheel, m.pyodide).catch((e) => { postMessage({ type: "fatal", text: String(e.message || e) }); throw e; });
    return;
  }
  const call = await ready;
  try {
    const out = JSON.parse(call(m.method, m.path, JSON.stringify(m.headers || {}), m.body || null));
    postMessage({ type: "reply", id: m.id, ...out });
  } catch (e) {
    postMessage({ type: "reply", id: m.id, status: 500, ctype: "application/json",
                  body: btoa(JSON.stringify({ error: String(e) })) });
  }
};
