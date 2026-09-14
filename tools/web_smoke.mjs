#!/usr/bin/env node
/*
 * Smoke test for the browser edition.
 *
 * Two halves:
 *   1. the static tree - every file index.html, the manifest and the service
 *      worker point at really exists, and the JS is syntactically loadable;
 *   2. the Python payload - the same files the page ships are booted inside
 *      Pyodide and the bridge is driven through a whole game, a whole puzzle
 *      and a whole Anarchess turn.
 *
 * Half 2 uses no network: python-chess is vendored into web/python by
 * tools/build_web.py precisely so this can run offline.
 *
 * Usage:  npm install pyodide@0.27.7 && node tools/web_smoke.mjs
 */

import { loadPyodide } from "pyodide";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(join(dirname(fileURLToPath(import.meta.url)), ".."));
const WEB = join(ROOT, "web");

let passed = 0;
let failed = 0;

function check(ok, label, detail) {
  if (ok) {
    passed += 1;
    console.log("  ok    " + label);
  } else {
    failed += 1;
    console.log("  FAIL  " + label + (detail ? " — " + detail : ""));
  }
}

function read(rel) {
  return readFileSync(join(WEB, rel), "utf8");
}

/* ------------------------------------------------------------ static tree */

function staticChecks() {
  console.log("static tree");

  const required = [
    "index.html", "manifest.webmanifest", "sw.js",
    "css/style.css",
    "js/app.js", "js/board.js", "js/engine.js", "js/play.js", "js/train.js",
    "js/anarchess.js", "js/worker.js",
    "python/bridge.py", "python/files.json", "python/chess/__init__.py",
    "python/lc/core/engine.py", "python/lc/variants/anarchchess.py",
    "python/lc/anarchess/rules.py", "python/lc/anarchess/ai.py",
    "icons/talos.svg", "icons/favicon.ico", "icons/talos-192.png",
    "icons/talos-512.png", "icons/talos-maskable-512.png",
    "icons/apple-touch-icon.png",
  ];
  for (const rel of required) {
    check(existsSync(join(WEB, rel)), rel);
  }

  // every local file index.html points at
  const html = read("index.html");
  const refs = new Set();
  for (const match of html.matchAll(/(?:href|src)="([^"#:]+)"/g)) refs.add(match[1]);
  for (const ref of refs) {
    check(existsSync(join(WEB, ref)), "index.html -> " + ref);
  }

  // every module the JS imports
  for (const name of readdirSync(join(WEB, "js"))) {
    const source = read(join("js", name));
    for (const match of source.matchAll(/from "(\.\/[^"]+)"/g)) {
      const target = join(WEB, "js", match[1]);
      check(existsSync(target), name + " imports " + match[1]);
    }
  }

  // the manifest
  const manifest = JSON.parse(read("manifest.webmanifest"));
  check(manifest.name && manifest.short_name, "manifest has a name");
  check(Array.isArray(manifest.icons) && manifest.icons.length >= 2, "manifest has icons");
  for (const icon of manifest.icons || []) {
    check(existsSync(join(WEB, icon.src)), "manifest icon " + icon.src);
  }
  check(manifest.display === "standalone", "manifest is standalone");

  // the service worker's precache list
  const sw = read("sw.js");
  const block = sw.match(/const SHELL = \[([\s\S]*?)\];/);
  check(!!block, "sw.js declares SHELL");
  if (block) {
    const entries = [...block[1].matchAll(/"(\.\/[^"]+)"/g)].map((m) => m[1]);
    check(entries.length >= 10, "sw.js precaches the shell", String(entries.length) + " entries");
    for (const entry of entries) {
      check(existsSync(join(WEB, entry)), "sw.js precache " + entry);
    }
  }

  // the file index the worker downloads
  const files = JSON.parse(read("python/files.json"));
  check(files.includes("bridge.py"), "files.json lists the bridge");
  for (const rel of files) {
    if (!existsSync(join(WEB, "python", rel))) {
      check(false, "files.json -> " + rel);
      break;
    }
  }
  check(files.every((rel) => existsSync(join(WEB, "python", rel))),
    "files.json paths all exist", files.length + " files");
}

/* ------------------------------------------------------------ the payload */

async function pythonChecks() {
  console.log("\npython payload (Pyodide)");

  const files = JSON.parse(read("python/files.json"));
  const pyodide = await loadPyodide();
  pyodide.FS.mkdirTree("/talos");
  for (const rel of files) {
    const slash = rel.lastIndexOf("/");
    if (slash > 0) pyodide.FS.mkdirTree("/talos/" + rel.slice(0, slash));
    pyodide.FS.writeFile("/talos/" + rel, read(join("python", rel)));
  }
  pyodide.runPython("import sys\nsys.path.insert(0, '/talos')\nimport bridge\n");
  // a tiny helper inside Python so argument marshalling stays honest
  pyodide.runPython(`
def _call(fn, *args):
    return getattr(bridge, fn)(*args)
`);
  const callPy = pyodide.runPython("_call");
  const bridge = (fn, ...args) => JSON.parse(callPy(fn, ...args));

  const about = bridge("about");
  check(about.app === "TALOS", "bridge.about", JSON.stringify(about.app));
  check(about.chess && about.chess.split(".").length >= 2,
    "python-chess is vendored", "version " + about.chess);

  const levels = bridge("levels");
  check(levels.length >= 8, "bridge.levels", levels.length + " levels");
  check(levels[0].elo < levels[levels.length - 1].elo, "levels are graded by Elo");

  // a miniature game: four moves, each one generated by the engine
  let fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  let ok = true;
  const moves = [];
  for (let i = 0; i < 4; i += 1) {
    const answer = bridge("analyse", fen, "Club", 200, "standard", null);
    if (!answer.bestmove) { ok = false; break; }
    const next = bridge("push", fen, answer.bestmove, "standard", null);
    if (!next.ok) { ok = false; break; }
    moves.push(next.played_san);
    fen = next.fen;
  }
  check(ok && moves.length === 4, "engine plays four moves", moves.join(" "));
  const illegal = bridge("push", fen, "e2e7", "standard", null);
  check(illegal.ok === false, "illegal moves are rejected");

  // The scholar's mate, found by the engine.  Asked of Master+, not Club:
  // the weaker levels are built to blunder on purpose (Club plays a worse
  // move 8% of the time), so expecting mate from one is a coin toss.
  const mate = bridge("analyse",
    "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 0 1",
    "Master+", 1500, "standard", null);
  check(mate.mate === 1, "engine sees mate in one", JSON.stringify(mate.san));

  // anarchchess
  const book = bridge("anarch_rules");
  check(book.rules.length >= 10, "anarch_rules", book.rules.length + " rules");
  const preset = JSON.stringify(book.presets.anarchchess);
  const anarch = bridge("position",
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "anarchchess", preset);
  check(anarch.moves.length > 0, "anarchchess generates moves");
  const anarchy = bridge("position",
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "anarchy", JSON.stringify(book.presets.anarchy));
  check(anarchy.moves.length > 0, "full anarchy generates moves");

  // anarchess: a full turn for every player, driven by the bot
  const game = bridge("anarchess_new", 2, null, 12345);
  // the published opening is four tiles, the two light ones diagonal
  check(game.tiles.length === 4 && game.players === 2,
    "anarchess_new opens on four tiles", game.tiles.length + " tiles");
  const solo = bridge("anarchess_new", 4, JSON.stringify({ mode: "solo" }), 12345);
  check(solo.rules.solo && solo.players === 2 && Array.isArray(solo.reserve)
    && solo.reserve.length === 2,
    "SOLO always opens as two tribes", solo.players + " tribes");
  // Old browser builds could persist a four-player SOLO table. Restoring it
  // must trim surplus tribes, normalise its current index and leave the
  // no-pawn exception usable through the same JSON API.
  const oldSolo = {
    players: 4, rules: { mode: "solo", tiles_per_colour: 16 },
    names: ["Light", "Dark", "old third", "old fourth"],
    tiles: [[0, 0, 1]], pawns: [], supply: { light: 7, dark: 8 },
    reserve: [0, 0, 99, 99], current: 3, turn: 1, placed: true,
    last_tile: [0, 0], used: false, finished: false,
  };
  const oldSoloLegal = bridge("anarchess_legal", JSON.stringify(oldSolo));
  check(oldSoloLegal.can_pass && oldSoloLegal.pawns.length === 0,
    "a stranded legacy SOLO snapshot offers its pass");
  const oldSoloPass = bridge("anarchess_apply", JSON.stringify(oldSolo),
    JSON.stringify({ kind: "pass" }));
  check(oldSoloPass.ok && oldSoloPass.state.players === 2
    && oldSoloPass.state.reserve.length === 2 && !oldSoloPass.state.placed,
    "legacy SOLO restores as a usable two-tribe game");
  let state = game;
  let turns = 0;
  while (!state.finished && state.tiles.length < 8 && turns < 40) {
    const answer = bridge("anarchess_bot", JSON.stringify(state), 2, null);
    if (!answer.actions || !answer.actions.length) break;
    for (const action of answer.actions) {
      const res = bridge("anarchess_apply", JSON.stringify(state), JSON.stringify(action));
      if (!res.ok) { check(false, "anarchess_apply " + action.kind); state = res.state; break; }
      state = res.state;
      turns += 1;
    }
  }
  check(state.tiles.length >= 8, "the land grows", state.tiles.length + " tiles");
  check(state.pawns.length >= 1, "pawns settle on the land", state.pawns.length + " pawns");
  check(typeof state.status === "string" && state.status.length > 0, "anarchess status line");

  // and a finished game scores
  let scored = bridge("anarchess_new", 2, null, 99);
  let guard = 0;
  while (!scored.finished && guard < 200) {
    guard += 1;
    const answer = bridge("anarchess_bot", JSON.stringify(scored), 1, null);
    if (!answer.actions || !answer.actions.length) break;
    for (const action of answer.actions) {
      const res = bridge("anarchess_apply", JSON.stringify(scored), JSON.stringify(action));
      if (!res.ok) break;
      scored = res.state;
    }
  }
  check(scored.finished === true, "a game against itself reaches the end", guard + " turns");
  check(scored.final !== null && scored.final.length === 2, "final scores exist",
    JSON.stringify(scored.final));
}

/* -------------------------------------------------------------------- main */

async function main() {
  console.log("TALOS - browser edition smoke test\n");
  if (!existsSync(WEB)) {
    console.log("  FAIL  no web/ directory - run tools/build_web.py first");
    process.exit(1);
  }
  staticChecks();
  await pythonChecks();
  console.log("\n" + passed + " passed, " + failed + " failed");
  process.exit(failed ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
