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

// jsdom has no canvas: give it a 2D context that swallows every call. The
// land renderer intentionally uses gradients as part of its canvas artwork.
const fakeGradient = { addColorStop() {} };
const fakeContext = new Proxy({}, {
  get: (target, key) => {
    if (key === "createLinearGradient" || key === "createRadialGradient") {
      return () => fakeGradient;
    }
    return key in target ? target[key] : () => {};
  },
  set: (target, key, value) => { target[key] = value; return true; },
});
win.HTMLCanvasElement.prototype.getContext = () => fakeContext;
// Give every map a believable CSS rectangle: jsdom has no layout engine, but
// controller hit testing and DPR sizing deliberately depend on visible pixels.
Object.defineProperties(win.HTMLCanvasElement.prototype, {
  clientWidth: { configurable: true, get: () => 640 },
  clientHeight: { configurable: true, get: () => 420 },
});
class FakeResizeObserver {
  constructor(callback) { this.callback = callback; }
  observe(target) {
    this.callback([{ target, contentRect: {
      width: target.clientWidth || 1, height: target.clientHeight || 1,
    } }]);
  }
  disconnect() {}
}
win.ResizeObserver = FakeResizeObserver;

for (const key of ["window", "document", "navigator", "localStorage", "location",
  "history", "HTMLElement", "Element", "Node", "Event", "CustomEvent", "MouseEvent",
  "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame", "DOMParser",
  "ResizeObserver"]) {
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
check($("level").options.length === 15, "the level list is filled",
  $("level").options.length + " levels");
check($("think-time").options.length === 3,
  "the chess thinking-budget selector is filled");
check($("rule-list").children.length === 15, "the rule switches are rendered",
  $("rule-list").children.length + " rules");
check(win.document.querySelectorAll("#board .sq").length === 64, "the board has 64 squares");
check(win.document.querySelectorAll("#board .piece").length === 32, "32 pieces stand on it");
check($("turn-chip").textContent === "White to move", "the turn chip", $("turn-chip").textContent);
check($("version-line").textContent.startsWith("TALOS"), "the version line",
  $("version-line").textContent.slice(0, 58));

console.log("\nplay");
const play = app.views.play;
$("level").value = $("level").options[$("level").options.length - 1].value;
$("level").dispatchEvent(new win.Event("change", { bubbles: true }));
$("think-time").value = "quick";
$("think-time").dispatchEvent(new win.Event("change", { bubbles: true }));
const quickBudget = play.thinkBudget();
$("think-time").value = "deep";
$("think-time").dispatchEvent(new win.Event("change", { bubbles: true }));
check(app.settings.think === "deep" && play.thinkBudget() > quickBudget,
  "the selected chess think-time changes the engine budget");
// Restore a fast profile, then observe the real worker request—not only the
// UI helper—to protect the engine_move wiring from regressing to a fixed time.
$("level").value = "Club";
$("level").dispatchEvent(new win.Event("change", { bubbles: true }));
$("think-time").value = "quick";
$("think-time").dispatchEvent(new win.Event("change", { bubbles: true }));
let requestedBudget = null;
const rawEngineJson = app.engine.json;
const callEngineJson = rawEngineJson.bind(app.engine);
app.engine.json = async (fn, args) => {
  if (fn === "analyse") requestedBudget = args[2];
  return callEngineJson(fn, args);
};
await play.humanMove("e2e4");
app.engine.json = rawEngineJson;
check(requestedBudget === play.thinkBudget(),
  "the actual chess-engine request receives the selected budget", String(requestedBudget));
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
check(!!an.state && !an.state.rules.solo && !an.state.rules.checkers,
  "the original Anarchess page starts its own game");
check($("view-anarchess").classList.contains("active") && !$("an-mode"),
  "Anarchess has a dedicated page instead of an attached mode switch");
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
// The die sends the opposite colour first, so let the bots have their turn
// before the human is asked to click anything.
await an.runBots();
const clickCell = async (view, cx, cy) => view._click({
  clientX: view.ox + (cx + 0.5) * view.cell,
  clientY: view.oy + (cy + 0.5) * view.cell,
});
const before = an.state.tiles.length;
const spot = (an.legal.tiles || [])[0];
check(!!spot, "the human has a legal tile to lay");
await clickCell(an, spot.x, spot.y);
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
check(an.el.list.textContent.includes("Light"),
  "the original game tribe panel is filled");

console.log("\nanarchess SOLO");
await app.show("solo");
const solo = app.views.solo;
check(!!solo.state && solo.state.rules.solo && solo.state.players === 2,
  "SOLO has its own two-tribe game", solo.state.players + " tribes");
check(solo.el.players === null && solo.el.level === null,
  "SOLO removes table-only controls");
check($("view-solo").classList.contains("active") && solo.root.querySelector("h2").textContent.includes("SOLO"),
  "SOLO has its own page and title");
const soloBefore = solo.state.tiles.length;
const soloSpot = (solo.legal.tiles || [])[0];
check(!!soloSpot, "the solo player has a tile to lay");
await clickCell(solo, soloSpot.x, soloSpot.y);
check(solo.state.tiles.length === soloBefore + 1 && solo.state.placed,
  "the solo player can act on either turn", solo.state.tiles.length + " tiles");
check(Number.isInteger(solo.state.pawn_player),
  "the pawn-action tribe is carried in the snapshot", String(solo.state.pawn_player));
// The turn owner can be Light while the SOLO pawn actor is Dark. Make that
// state explicit and verify the controller selects the Dark pawn, not a
// hard-coded Light one; applying the second click is outside this UI check.
const savedSoloState = solo.state;
const savedSoloLegal = solo.legal;
solo.state = { current: 0, pawn_player: 1, placed: true, rules: { solo: true },
  names: ["Light", "Dark"], pawns: [[3, 3, 1]], tiles: [], areas: [], finished: false };
solo.legal = { tiles: [], pawns: [{ kind: "move", x: 4, y: 3, fx: 3, fy: 3 }], can_pass: false };
solo.source = null;
solo.ox = 0;
solo.oy = 0;
solo.cell = 1;
await solo._click({ clientX: 3.5, clientY: 3.5 });
check(Array.isArray(solo.source) && solo.source[0] === 3 && solo.source[1] === 3,
  "the solo player can select the other tribe's pawn");
solo.state = savedSoloState;
solo.legal = savedSoloLegal;
solo.source = null;

const savedApply = solo.apply;
let passedSoloAction = null;
solo.state = { current: 0, placed: true, rules: { solo: true }, names: ["Light", "Dark"],
  pawns: [], reserve: [0, 0], scores: [0, 0], final: null,
  supply: { light: 0, dark: 0 }, left: 0, status: "No pawn action", finished: false };
solo.legal = { tiles: [], pawns: [], can_pass: true };
solo._panel();
solo.apply = async (action) => { passedSoloAction = action; return true; };
await solo.pass();
check(!solo.el.pass.disabled && solo.el.pass.textContent.includes("Pass")
  && passedSoloAction && passedSoloAction.kind === "pass",
  "a stranded solo player is offered a pass");
solo.apply = savedApply;
solo.state = savedSoloState;
solo.legal = savedSoloLegal;
solo.source = null;

console.log("\nanarcheckers");
await app.show("anarcheckers");
const checkers = app.views.anarcheckers;
check(!!checkers.state && checkers.state.rules.checkers && !checkers.state.rules.solo,
  "Anarcheckers has its own game rules");
check($("view-anarcheckers").classList.contains("active")
  && checkers.root.querySelector("h2").textContent.toLowerCase().includes("anarcheckers"),
  "Anarcheckers has its own page and title");
const chainSnapshot = {
  players: 2, rules: { checkers: true, tiles_per_colour: 16 }, names: ["Light", "Dark"],
  tiles: [[0, 0, 1], [1, 1, 0], [2, 2, 1], [3, 3, 0], [4, 4, 1],
          [5, 1, 1], [6, 2, 0], [7, 3, 1]],
  pawns: [[0, 0, 0], [1, 1, 1], [3, 3, 1], [5, 1, 0], [6, 2, 1]],
  supply: { light: 4, dark: 4 }, reserve: [7, 8], current: 0, turn: 1,
  placed: true, last_tile: [0, 0], used: false, finished: false,
};
const firstChain = await checkers.app.engine.json("anarchess_apply",
  [JSON.stringify(chainSnapshot), JSON.stringify({ kind: "attack", fx: 0, fy: 0, x: 2, y: 2 })]);
const chainedLegal = await checkers.app.engine.json("anarchess_legal",
  [JSON.stringify(firstChain.state)]);
const hijackedChain = await checkers.app.engine.json("anarchess_apply",
  [JSON.stringify(firstChain.state), JSON.stringify({ kind: "attack", fx: 5, fy: 1, x: 7, y: 3 })]);
check(firstChain.ok && JSON.stringify(firstChain.state.chain) === JSON.stringify([2, 2])
  && chainedLegal.pawns.length === 1 && chainedLegal.pawns[0].fx === 2
  && !hijackedChain.ok,
  "Anarcheckers keeps compulsory chains with the original pawn");

console.log("\nresponsive graphics");
check(win.document.querySelectorAll("#board svg.piece").length === 32,
  "the chessboard uses scalable SVG piece geometry");
const map = an.canvas;
Object.defineProperties(map, {
  clientWidth: { configurable: true, get: () => 640 },
  clientHeight: { configurable: true, get: () => 420 },
});
Object.defineProperty(win, "devicePixelRatio", { configurable: true, value: 2 });
globalThis.devicePixelRatio = 2;
an.draw();
check(map.width === 1280 && map.height === 840,
  "land artwork uses a DPR-aware canvas backing store", map.width + "×" + map.height);
// Zooming at a pointer position must retain the map cell under it. This is
// distinct from merely changing canvas size: a wrong camera sign makes art
// visibly jump away from the user's cursor at every zoom step.
const zoomX = 510;
const zoomY = 94;
const beforeZoomWorld = [(zoomX - an.ox) / an.cell, (zoomY - an.oy) / an.cell];
an.zoomAt(1.2, zoomX, zoomY);
const afterZoomWorld = [(zoomX - an.ox) / an.cell, (zoomY - an.oy) / an.cell];
check(Math.abs(beforeZoomWorld[0] - afterZoomWorld[0]) < 1e-9
  && Math.abs(beforeZoomWorld[1] - afterZoomWorld[1]) < 1e-9,
"map zoom stays anchored under the pointer");
an.resetCamera();
Object.defineProperty(win, "devicePixelRatio", { configurable: true, value: 1 });
globalThis.devicePixelRatio = 1;

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
