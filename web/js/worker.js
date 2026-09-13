/*
 * TALOS - browser edition: the Pyodide worker.
 *
 * This worker is the only place Python runs.  Everything the page needs is
 * handed to it as a tiny JSON message and comes back as a JSON string, so the
 * UI never blocks: the engine can think while you are still looking at the
 * board.
 *
 * The Python core it loads is not a rewrite for the web - it is the very same
 * lc/core/engine.py, lc/variants/anarchchess.py and lc/anarchess/*.py that the
 * desktop application uses, copied into web/python by tools/build_web.py and
 * mounted here into the Pyodide file system.
 */

const PYODIDE_VERSION = "0.27.7";
const CDN = "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/";
const BASE = new URL("../", self.location.href).href;

let booting = null;

function say(text, pct) {
  self.postMessage({ type: "progress", text: text, pct: pct });
}

function boot() {
  if (booting) return booting;
  booting = (async () => {
    say("Downloading the Python runtime", 0.05);
    importScripts(CDN + "pyodide.js");

    const pyodide = await loadPyodide({ indexURL: CDN });
    say("Unpacking the TALOS core", 0.55);

    const files = await (await fetch(BASE + "python/files.json")).json();
    pyodide.FS.mkdirTree("/talos");
    for (let i = 0; i < files.length; i++) {
      const rel = files[i];
      const res = await fetch(BASE + "python/" + rel);
      if (!res.ok) throw new Error("missing core file: " + rel);
      const slash = rel.lastIndexOf("/");
      if (slash > 0) pyodide.FS.mkdirTree("/talos/" + rel.slice(0, slash));
      pyodide.FS.writeFile("/talos/" + rel, await res.text());
      if (i % 6 === 0) say("Unpacking the TALOS core", 0.55 + 0.35 * (i / files.length));
    }

    say("Waking the engine", 0.95);
    pyodide.runPython("import sys\nsys.path.insert(0, '/talos')\nimport bridge\n");
    const bridge = pyodide.pyimport("bridge");
    return { pyodide: pyodide, bridge: bridge };
  })().catch((err) => {
    booting = null;
    self.postMessage({ type: "fatal", error: String((err && err.message) || err) });
    throw err;
  });
  return booting;
}

self.onmessage = async (event) => {
  const msg = event.data || {};
  if (msg.type !== "call") return;
  const id = msg.id;
  try {
    const env = await boot();
    const fn = env.bridge[msg.fn];
    if (typeof fn !== "function") throw new Error("no such function: " + msg.fn);
    const raw = fn.apply(null, msg.args || []);
    self.postMessage({ type: "result", id: id, ok: true, value: raw });
  } catch (err) {
    self.postMessage({
      type: "result", id: id, ok: false,
      error: String((err && err.message) || err),
    });
  }
};

self.postMessage({ type: "hello" });
