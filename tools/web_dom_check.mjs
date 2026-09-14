#!/usr/bin/env node
/*
 * Boot the actual browser edition in Node and play with it.
 *
 * tools/web_smoke.mjs proves the Python payload works.  This one proves the
 * *page* works: it loads web/index.html into a DOM, installs a real Pyodide
 * worker in place of the browser's, imports web/js/app.js untouched, and then
 * does what a player does - plays a move, opens a puzzle set, lays an
 * Anarchess tile.
 *
 * Anything that would throw in a browser console throws here.
 *
 * Usage:  npm install --no-save --no-package-lock pyodide@0.27.7 jsdom
 *         node tools/web_dom_check.mjs
 */

import { JSDOM } from "jsdom";
import { loadPyodide } from "pyodide";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(join(dirname(fileURLToPath(import.meta.url)), ".."));
const WEB = join(ROOT, "web");
const PY = join(WEB, "python");

let passed = 0;
let failed = 0;

function check(ok, label, detail) {
  if (ok) {
    passed += 1;
    console.log("  ok    " + label + (detail ? " — " + detail : ""));
  } else {
    failed += 1;
    console.log("  FAIL  " + label + (detail ? " — " + detail : ""));
  }
}

/* --------------------------------------------------------------- the world */

const html = readFileSync(join(WEB, "index.html"), "utf8");
const dom = new JSDOM(html, { url: "http://localhost:8080/", pretendToBeVisual: true });
const win = dom.window;

// jsdom has no canvas: give it a 2D context that swallows every call
const fakeContext = new Proxy({}, {
  get: (target, key) => (key in target ? target[key] : () => {}),
  set: (target, key, value) => { target[key] = value; return true; },
});
win.HTMLCanvasElement.prototype.getContext = () => fakeContext;

for (const key of ["window", "document", "navigator", "localStorage", "location",
  "history", "HTMLElement", "Element", "Node", "Event", "CustomEvent", "MouseEvent",
  "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame", "DOMParser"]) {
  if (win[key] !== undefined) globalThis[key] = win[key];
}
globalThis.window = win;
globalThis.document = win.document;
globalThis.devicePixelRatio = 1;

// relative fetches resolve against the site root, the way a browser does
globalThis.fetch = async (url) => {
  const path = String(url).replace(/^https?:\/\/[^/]+\//, "").replace(/^\.\//, "");
  try {
    const body = readFileSync(join(WEB, path));
    return { ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body };
  } catch (err) {
    return { ok: false, status: 404,
      json: async () => { throw err; }, text: async () => "" };
  }
};

/* ------------------------------------------------- the stand-in for Worker */

const files = JSON.parse(readFileSync(join(PY, "files.json"), "utf8"));

class NodeWorker {
  constructor() {
    this.onmessage = null;
    this.booting = (async () => {
      const py = await loadPyodide();
      py.FS.mkdirTree("/talos");
      for (const rel of files) {
        const slash = rel.lastIndexOf("/");
        if (slash > 0) py.FS.mkdirTree("/talos/" + rel.slice(0, slash));
        py.FS.writeFile("/talos/" + rel, readFileSync(join(PY, rel), "utf8"));
      }
      py.runPython("import sys\nsys.path.insert(0, '/talos')\nimport bridge\n");
      this.bridge = py.runPython("bridge");
      return py;
    })();
  }

  async postMessage(message) {
    if (message.type !== "call") return;
    await this.booting;
    let reply;
    try {
      reply = { type: "result", id: message.id, ok: true,
        value: this.bridge[message.fn](...message.args) };
    } catch (err) {
      reply = { type: "result", id: message.id, ok: false, error: String(err) };
    }
    if (this.onmessage) this.onmessage({ data: reply });
  }

  terminate() {}
}

globalThis.Worker = NodeWorker;

/* ------------------------------------------------------------------- boot */

const errors = [];
win.addEventListener("error", (event) => errors.push("window error: " + event.message));
process.on("unhandledRejection", (err) => errors.push("unhandled rejection: " + err));

console.log("TALOS - browser edition, live in a DOM\n");

await import(new URL("../web/js/app.js", import.meta.url).href);
const app = win.talos;
for (let i = 0; i < 400 && !app.info; i += 1) await sleep(50);

const $ = (id) => win.document.getElementById(id);

console.log("boot");
check(!!app.info, "the engine booted", app.info && "Python " + app.info.python);
check($("loader").classList.contains("hidden"), "the loader goes away");
check($("level").options.length === 12, "the level list is filled",
  $("level").options.length + " levels");
check($("rule-list").children.length === 15, "the rule switches are rendered",
  $("rule-list").children.length + " rules");
check(win.document.querySelectorAll("#board .sq").length === 64, "the board has 64 squares");
check(win.document.querySelectorAll("#board .piece").length === 32, "32 pieces stand on it");
check($("turn-chip").textContent === "White to move", "the turn chip", $("turn-chip").textContent);
check($("version-line").textContent.startsWith("TALOS"), "the version line",
  $("version-line").textContent.slice(0, 58));

console.log("\nplay");
await app.views.play.humanMove("e2e4");
check(app.views.play.san.length === 2, "my move and the engine's reply",
  app.views.play.san.join(" "));
app.set("side", "b");
await app.views.play.engineMove();
check(app.views.play.san.length === 3, "the engine takes the other side",
  app.views.play.san.join(" "));
await app.views.play.hint();
check(/Try /.test($("status-text").textContent), "the hint works",
  $("status-text").textContent);
await app.views.play.undo();
check(app.views.play.history.length === 2, "undo hands the move back",
  app.views.play.history.length + " positions");
app.set("side", "w");
await app.views.play.newGame();
check(app.views.play.san.length === 0, "a new game clears the move list");

console.log("\ntrain");
await app.show("train");
await app.views.train.activate();
check(app.views.train.sets.length > 100, "the training sets loaded",
  app.views.train.sets.length + " sets");
check($("tboard").children.length === 64, "the puzzle board is built");
check($("set-picker").options.length > 0, "the set picker is filled");

const train = app.views.train;
const firstSet = train.sets.find((entry) => entry.kind === "mates") || train.sets[0];
await train.openSet(firstSet.id);
check(!!train.puzzle, "a puzzle loaded", firstSet.name.slice(0, 40));
check($("tboard").querySelectorAll(".piece").length > 0, "the puzzle position is on the board");
const solution = train.line[0];
await train.answer(solution);
check(train.step > 0, "a correct move advances the line",
  "step " + train.step + " of " + train.line.length);
train.hint();
check(/Look at /.test($("t-feedback").textContent), "the puzzle hint works",
  $("t-feedback").textContent);
check(Number($("t-solved").textContent) + Number($("t-failed").textContent) >= 0,
  "the scoreboard is live");

console.log("\nanarchess");
await app.show("anarchess");
const an = app.views.anarchess;
check(!!an.state, "a game was created");
// The view's game may already be under way, so the opening is asserted on a
// pristine state asked straight from the engine.
const fresh = await an.app.engine.json("anarchess_new",
  [2, JSON.stringify(an.rules()), 20240914]);
check(fresh.tiles.length === 4, "the published opening is four tiles",
  fresh.tiles.length + " tiles");
const openingLight = fresh.tiles.filter((t) => t[2] === 1).length;
check(openingLight === 2, "two of them light", openingLight + " light");
check(fresh.drawn === true || fresh.drawn === false,
  "the die has already named a colour");
// the die sends the opposite colour first, so let the bots have their turn
// before the human is asked to click anything
await an.runBots();
const clickCell = (cx, cy) => an._click({
  clientX: an.ox + (cx + 0.5) * an.cell,
  clientY: an.oy + (cy + 0.5) * an.cell,
});
const before = an.state.tiles.length;
const spot = (an.legal.tiles || [])[0];
check(!!spot, "the human has a legal tile to lay");
await clickCell(spot.x, spot.y);
check(an.state.tiles.length === before + 1, "clicking lays a tile",
  an.state.tiles.length + " tiles");
const laid = an.state.tiles.find((t) => t[0] === spot.x && t[1] === spot.y);
check(!!laid && laid[2] === spot.colour, "it is the colour the die named",
  laid ? (laid[2] ? "light" : "dark") : "no tile");
check(an.phase() === true, "and it becomes the pawn-action phase");
await an.pass();
check(an.state.tiles.length >= before + 2, "the bots answer",
  an.state.tiles.length + " tiles");
check(an.state.current === 0, "the turn comes back round");
check($("an-players-list").textContent.includes("Light"), "the tribe panel is filled");

console.log("\nrules");
await app.show("rules");
$("preset-anarchy").dispatchEvent(new win.Event("click", { bubbles: true }));
check(Object.values(app.settings.rules).every((v) => v === true),
  "the full-anarchy preset switches everything on");
$("preset-off").dispatchEvent(new win.Event("click", { bubbles: true }));
check(Object.values(app.settings.rules).every((v) => v === false),
  "the all-off preset switches everything off");
$("preset-curated").dispatchEvent(new win.Event("click", { bubbles: true }));
check(Object.values(app.settings.rules).filter(Boolean).length > 0,
  "the curated preset switches some back on",
  Object.values(app.settings.rules).filter(Boolean).length + " of 15");

check(errors.length === 0, "no runtime errors anywhere", errors.join(" / "));
console.log("\n" + passed + " passed, " + failed + " failed");
process.exit(failed ? 1 : 0);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
