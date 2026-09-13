/*
 * TALOS - browser edition: the Train tab.
 *
 * Lucas Chess' puzzle sets (tactics, mates, endgames, STS, GM games) exported
 * to web/data by tools/build_web.py.  The 2 MB puzzle file is only fetched the
 * first time you actually open a set, so Play stays instant.
 *
 * On top of the sets there is a small spaced-repetition coach: every puzzle you
 * touch gets a box, and boxes you keep getting right drift further apart.
 */

import { Board } from "./board.js";
import { escapeHtml } from "./play.js";

const STORE_KEY = "talos.learn";
const BOX_DAYS = [0.02, 0.5, 2, 6, 16, 40, 90];

export class TrainView {
  constructor(app) {
    this.app = app;
    this.el = {
      board: document.getElementById("tboard"),
      search: document.getElementById("set-search"),
      picker: document.getElementById("set-picker"),
      info: document.getElementById("set-info"),
      solved: document.getElementById("t-solved"),
      failed: document.getElementById("t-failed"),
      streak: document.getElementById("t-streak"),
      feedback: document.getElementById("t-feedback"),
      learn: document.getElementById("learn-summary"),
    };
    this.board = new Board(this.el.board, { onMove: (uci) => this.answer(uci) });
    this.sets = [];
    this.puzzles = null;
    this.puzzle = null;
    this.line = [];
    this.step = 0;
    this.position = null;
    this.locked = false;
    this.session = { solved: 0, failed: 0, streak: 0 };
    this.cards = loadCards();
    this._wire();
    this._scoreboard();
    this._learnSummary();
  }

  _wire() {
    this.el.search.addEventListener("input", () => this._fillPicker());
    this.el.picker.addEventListener("change", () => this.openSet(this.el.picker.value));
    document.getElementById("btn-tnext").addEventListener("click", () => this.next(true));
    document.getElementById("btn-thint").addEventListener("click", () => this.hint());
    document.getElementById("btn-tshow").addEventListener("click", () => this.show());
  }

  /** Lazy: only runs when the Train tab is first shown. */
  async activate() {
    if (this.sets.length) return;
    const data = await fetchJSON("data/sets.json");
    this.sets = data.sets || [];
    this._fillPicker();
    this.el.info.textContent = this.sets.length + " sets · " +
      (this.puzzles ? "puzzles loaded" : "puzzles load on demand");
  }

  _fillPicker() {
    const needle = this.el.search.value.trim().toLowerCase();
    const shown = this.sets.filter((s) => s.name.toLowerCase().includes(needle));
    const groups = new Map();
    for (const set of shown) {
      if (!groups.has(set.kind)) groups.set(set.kind, []);
      groups.get(set.kind).push(set);
    }
    let html = "";
    for (const [kind, items] of groups) {
      html += '<optgroup label="' + escapeHtml(kind) + '">';
      for (const set of items.slice(0, 80)) {
        html += '<option value="' + set.id + '">' + escapeHtml(set.name) + "</option>";
      }
      if (items.length > 80) {
        html += '<option disabled>… ' + (items.length - 80) + " more, narrow the search</option>";
      }
      html += "</optgroup>";
    }
    this.el.picker.innerHTML = html || '<option disabled>No match</option>';
    this.el.info.textContent = shown.length + " of " + this.sets.length + " sets";
  }

  async openSet(id) {
    this.setId = id;
    if (!this.puzzles) {
      this.el.info.textContent = "Loading the puzzle database…";
      const data = await fetchJSON("data/puzzles.json");
      this.puzzles = data.puzzles || {};
    }
    const list = this.puzzles[id] || [];
    if (!list.length) {
      this.el.feedback.textContent = "That set has no usable puzzles.";
      return;
    }
    this.queue = orderPuzzles(list, this.cards);
    this.queueAt = 0;
    this.el.feedback.textContent = "Set loaded — " + list.length + " puzzles.";
    await this.next(false);
  }

  async next(skipped) {
    if (!this.queue || !this.queue.length) {
      this.el.feedback.textContent = "Pick a training set on the left to begin.";
      return;
    }
    if (skipped) this.queueAt = (this.queueAt + 1) % this.queue.length;
    this.puzzle = this.queue[this.queueAt];
    this.line = this.puzzle.m.slice();
    this.step = 0;
    this.locked = false;
    this.board.hint = null;
    this.position = await this.app.engine.json("position", [this.puzzle.f, "standard", "{}"]);
    this.board.setPosition(this.position);
    this.board.interactive = true;
    const card = this.cards[this.puzzle.i];
    this.el.feedback.textContent = "Your move" +
      (card && card.box ? " · review " + (card.box + 1) : "") +
      (this.puzzle.d ? " · difficulty " + this.puzzle.d : "");
    this.el.feedback.className = "feedback";
  }

  async answer(uci) {
    if (this.locked || !this.puzzle) return;
    const expected = this.line[this.step];
    if (!expected) return;
    const ok = uci === expected || uci.slice(0, 4) === expected.slice(0, 4);
    if (!ok) return this.wrong(expected);
    await this.right(expected);
  }

  async right(uci) {
    this.locked = true;
    this.board.interactive = false;
    await this._push(uci);
    this.step += 1;
    if (this.step >= this.line.length) return this.finish(true);

    // the other side answers by itself - it is a puzzle, not a game
    await wait(420);
    const reply = this.line[this.step];
    if (reply) {
      await this._push(reply);
      this.step += 1;
    }
    if (this.step >= this.line.length) return this.finish(true);
    this.locked = false;
    this.board.interactive = true;
    this.el.feedback.textContent = "Good — the reply is forced. Keep going.";
    this.el.feedback.className = "feedback good";
  }

  wrong(expected) {
    this.session.failed += 1;
    this.session.streak = 0;
    this._scoreboard();
    const san = this.position.san[expected] || expected;
    this.el.feedback.textContent = "No — " + san + " was the move.";
    this.el.feedback.className = "feedback bad";
    this.grade(false);
    this.locked = true;
    this.board.interactive = false;
    setTimeout(() => { this.queueAt = (this.queueAt + 1) % this.queue.length; this.next(false); },
      1500);
  }

  async finish(solved) {
    this.session.solved += 1;
    this.session.streak += 1;
    this._scoreboard();
    this.grade(true);
    const line = this.puzzle.s || this.line.join(" ");
    this.el.feedback.textContent = "Solved. " + escapeHtml(line);
    this.el.feedback.className = "feedback good";
    this.board.interactive = false;
    await wait(1200);
    this.queueAt = (this.queueAt + 1) % this.queue.length;
    await this.next(false);
  }

  async _push(uci) {
    const pos = await this.app.engine.json("push", [this.position.fen, uci, "standard", "{}"]);
    if (!pos.ok) return;
    this.position = pos;
    this.board.setPosition(pos, { last: uci });
  }

  hint() {
    if (!this.puzzle) return;
    const uci = this.line[this.step];
    if (!uci) return;
    this.board.hint = uci.slice(2, 4);
    this.board.render();
    this.el.feedback.textContent = "Look at " + (this.position.san[uci] || uci) + ".";
    this.el.feedback.className = "feedback";
  }

  async show() {
    if (!this.puzzle) return;
    this.locked = true;
    this.board.interactive = false;
    while (this.step < this.line.length) {
      await this._push(this.line[this.step]);
      this.step += 1;
    }
    this.el.feedback.textContent = "The line: " + escapeHtml(this.puzzle.s || "");
    this.el.feedback.className = "feedback";
    await wait(1600);
    this.queueAt = (this.queueAt + 1) % this.queue.length;
    await this.next(false);
  }

  grade(correct) {
    const card = this.cards[this.puzzle.i] || { box: 0, right: 0, wrong: 0, seen: 0 };
    card.seen = (card.seen || 0) + 1;
    if (correct) {
      card.right = (card.right || 0) + 1;
      card.box = Math.min(BOX_DAYS.length - 1, (card.box || 0) + 1);
    } else {
      card.wrong = (card.wrong || 0) + 1;
      card.box = 0;
    }
    card.due = Date.now() + BOX_DAYS[card.box] * 86400000;
    this.cards[this.puzzle.i] = card;
    saveCards(this.cards);
    this._learnSummary();
  }

  _scoreboard() {
    this.el.solved.textContent = this.session.solved;
    this.el.failed.textContent = this.session.failed;
    this.el.streak.textContent = this.session.streak;
  }

  _learnSummary() {
    const cards = Object.values(this.cards);
    if (!cards.length) return;
    const now = Date.now();
    const due = cards.filter((c) => (c.due || 0) <= now).length;
    const right = cards.reduce((n, c) => n + (c.right || 0), 0);
    const wrong = cards.reduce((n, c) => n + (c.wrong || 0), 0);
    const pct = right + wrong ? Math.round((100 * right) / (right + wrong)) : 0;
    document.getElementById("learn-card").style.display = "";
    this.el.learn.innerHTML =
      "<b>" + cards.length + "</b> puzzles in the coach · <b>" + due +
      "</b> due now<br>Accuracy <b>" + pct + "%</b> (" + right + " correct, " +
      wrong + " missed)";
  }
}

/* ------------------------------------------------------------- helpers --- */

function orderPuzzles(list, cards) {
  const now = Date.now();
  const score = (p) => {
    const card = cards[p.i];
    if (!card) return -1;                       // unseen first, after the dues
    if ((card.due || 0) <= now) return 1e6 - (card.due || 0);
    return (card.due || 0) / 1e9;
  };
  return list.slice().sort((a, b) => score(b) - score(a));
}

function loadCards() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
  } catch (err) {
    return {};
  }
}

function saveCards(cards) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(cards));
  } catch (err) {
    /* private mode: the coach simply forgets between visits */
  }
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("cannot load " + url);
  return res.json();
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
