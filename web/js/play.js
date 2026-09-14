/*
 * TALOS - browser edition: the Play tab.
 *
 * Owns one game against the engine.  The engine is the same Python LCEngine
 * the desktop app uses, so the levels and their Elo numbers match exactly.
 */

import { Board } from "./board.js";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

export class PlayView {
  constructor(app) {
    this.app = app;
    this.el = {
      board: document.getElementById("board"),
      ranks: document.getElementById("ranks"),
      files: document.getElementById("files"),
      turn: document.getElementById("turn-chip"),
      status: document.getElementById("status-text"),
      matW: document.getElementById("mat-w"),
      matB: document.getElementById("mat-b"),
      variant: document.getElementById("variant"),
      level: document.getElementById("level"),
      think: document.getElementById("think-time"),
      side: document.getElementById("side"),
      list: document.getElementById("movelist"),
    };
    this.history = [START];
    this.san = [];
    this.busy = false;
    this.lastMove = null;

    this.board = new Board(this.el.board, {
      onMove: (uci) => this.humanMove(uci),
    });
    this._coordinates();
    this._wire();
  }

  _coordinates() {
    const ranks = "87654321".split("");
    const files = "abcdefgh".split("");
    this.el.ranks.innerHTML = ranks.map((r) => "<span>" + r + "</span>").join("");
    this.el.files.innerHTML = files.map((f) => "<span>" + f + "</span>").join("");
  }

  _wire() {
    this.el.variant.addEventListener("change", () => {
      this.app.set("variant", this.el.variant.value);
      this.newGame();
    });
    this.el.level.addEventListener("change", () => this.app.set("level", this.el.level.value));
    this.el.think.addEventListener("change", () => this.app.set("think", this.el.think.value));
    this.el.side.addEventListener("change", () => {
      this.app.set("side", this.el.side.value);
      this.maybeEngineMove();
    });
    document.getElementById("btn-new").addEventListener("click", () => this.newGame());
    document.getElementById("btn-undo").addEventListener("click", () => this.undo());
    document.getElementById("btn-flip").addEventListener("click", () => {
      this.app.set("flip", !this.board.flipped);
      this.board.setFlipped(this.board.flipped);
    });
    document.getElementById("btn-hint").addEventListener("click", () => this.hint());
  }

  /** Called once the engine is up. */
  async start() {
    const levels = await this.app.engine.json("levels");
    this.levels = levels;
    this.el.level.innerHTML = levels
      .map((lv) => '<option value="' + escapeHtml(lv.name) + '" title="Depth ' +
        lv.depth + ", up to " + formatSeconds(lv.movetime) + '">' +
        escapeHtml(lv.name) + " — " + lv.elo + " · d" + lv.depth + "</option>")
      .join("");
    const settings = this.app.settings;
    this.el.variant.value = settings.variant;
    this.el.side.value = settings.side;
    this.el.think.value = ["quick", "balanced", "deep"].includes(settings.think)
      ? settings.think : "balanced";
    this.el.level.value = levels.some((lv) => lv.name === settings.level)
      ? settings.level
      : levels[Math.min(6, levels.length - 1)].name;
    this.app.set("level", this.el.level.value);
    this.app.set("think", this.el.think.value);
    this.board.setFlipped(!!settings.flip);
    await this.refresh();
  }

  rules() {
    return this.app.settings.rules;
  }

  get variant() {
    return this.el.variant.value;
  }

  get fen() {
    return this.history[this.history.length - 1];
  }

  thinkBudget(forHint = false) {
    const selected = (this.levels || []).find((level) => level.name === this.el.level.value);
    const nominal = Number(selected && selected.movetime) || 900;
    const mode = this.el.think.value;
    let budget = nominal;
    if (mode === "quick") budget = Math.min(nominal, 700);
    else if (mode === "balanced") budget = Math.min(nominal, 2000);
    // A hint should be useful at beginner levels too, while the deep option
    // remains a deliberate opt-in for a Grandmaster search in Pyodide.
    if (forHint) budget = Math.max(900, Math.min(mode === "deep" ? nominal : budget, 2500));
    return Math.max(80, Math.min(15_000, Math.round(budget)));
  }

  async refresh(options) {
    const opts = options || {};
    const pos = await this.app.engine.json(
      "position", [this.fen, this.variant, JSON.stringify(this.rules())]);
    this.board.setPosition(pos, { last: this.lastMove, keepSelection: opts.keepSelection });
    this.el.turn.textContent = pos.over
      ? "Game over"
      : (pos.turn === "white" ? "White" : "Black") + " to move";
    this.el.matW.textContent = pos.material.white;
    this.el.matB.textContent = pos.material.black;
    const materialGap = pos.material.white - pos.material.black;
    this.el.status.textContent = pos.over
      ? describeResult(pos.result)
      : describe(pos, materialGap);
    this._movelist(pos);
    this.board.interactive = !pos.over && !this.busy;
    return pos;
  }

  _movelist(pos) {
    if (!this.san.length) {
      this.el.list.innerHTML = '<li class="dim">No moves yet.</li>';
      return;
    }
    const rows = [];
    for (let i = 0; i < this.san.length; i += 2) {
      rows.push(
        '<li><span class="n">' + (i / 2 + 1) + ".</span> " +
        escapeHtml(this.san[i]) +
        (this.san[i + 1] ? " " + escapeHtml(this.san[i + 1]) : "") +
        "</li>");
    }
    this.el.list.innerHTML = rows.join("");
    this.el.list.scrollTop = this.el.list.scrollHeight;
  }

  async humanMove(uci) {
    if (this.busy) return;
    const pos = await this.app.engine.json(
      "push", [this.fen, uci, this.variant, JSON.stringify(this.rules())]);
    if (!pos.ok) return;
    this.history.push(pos.fen);
    this.san.push(pos.played_san);
    this.lastMove = pos.played;
    await this.refresh();
    await this.maybeEngineMove();
  }

  async maybeEngineMove() {
    const pos = this.board.pos;
    if (!pos || pos.over) return;
    const side = this.app.settings.side;
    if (side === "none" || (pos.turn === "white" ? "w" : "b") !== side) {
      await this.engineMove();
    }
  }

  async engineMove() {
    if (this.busy) return;
    this.busy = true;
    this.board.interactive = false;
    const budget = this.thinkBudget();
    this.el.status.textContent = "Thinking — up to " + formatSeconds(budget) + "…";
    try {
      for (let guard = 0; guard < 200; guard += 1) {
        const current = this.board.pos;
        if (!current || current.over) break;
        const side = this.app.settings.side;
        if (side !== "none" && (current.turn === "white" ? "w" : "b") === side) break;

        const answer = await this.app.engine.json(
          "analyse",
          [current.fen, this.el.level.value, budget, this.variant, JSON.stringify(this.rules())]);
        if (!answer.bestmove) break;
        const next = await this.app.engine.json(
          "push", [current.fen, answer.bestmove, this.variant, JSON.stringify(this.rules())]);
        if (!next.ok) break;
        this.history.push(next.fen);
        this.san.push(next.played_san);
        this.lastMove = next.played;
        await this.refresh();
      }
    } finally {
      this.busy = false;
      const pos = this.board.pos;
      this.board.interactive = !!(pos && !pos.over);
      await this.refresh({ keepSelection: true });
    }
  }

  async hint() {
    if (this.busy) return;
    this.el.status.textContent = "Looking for a good move…";
    const answer = await this.app.engine.json(
      "analyse", [this.board.pos.fen, this.el.level.value, this.thinkBudget(true),
                  this.variant, JSON.stringify(this.rules())]);
    if (!answer.bestmove) return;
    this.board.hint = answer.bestmove.slice(2, 4);
    this.board.render();
    this.el.status.textContent = "Try " + (answer.san || answer.bestmove) +
      (answer.mate ? " — mate in " + Math.abs(answer.mate) :
        " — score " + Math.round(answer.score / 100) / 10);
  }

  async undo() {
    if (this.busy || this.history.length < 2) return;
    this.history.pop();
    this.san.pop();
    // Step back over the engine's reply too, so it is your move again.
    // After the first pop the top position is the one *your* move created,
    // which means the side to move there is the other one - if it is not you,
    // take your own move back as well.
    if (this.history.length > 1 && this.app.settings.side !== "none") {
      const top = this.history[this.history.length - 1];
      const whose = top.split(" ")[1] === "w" ? "w" : "b";
      if (whose !== this.app.settings.side) {
        this.history.pop();
        this.san.pop();
      }
    }
    this.lastMove = null;
    await this.refresh();
  }

  async newGame() {
    if (this.busy) return;
    this.history = [START];
    this.san = [];
    this.lastMove = null;
    await this.refresh();
    await this.maybeEngineMove();
  }
}

function formatSeconds(milliseconds) {
  const seconds = Number(milliseconds) / 1000;
  return seconds < 1 ? Math.round(Number(milliseconds)) + " ms" :
    (seconds % 1 ? seconds.toFixed(1) : String(seconds)) + " s";
}

function describe(pos, gap) {
  const bits = [];
  if (pos.check) bits.push("Check");
  if (pos.knooks && pos.knooks.length) bits.push(pos.knooks.length + " knook" + (pos.knooks.length > 1 ? "s" : "") + " fused");
  if (gap > 0) bits.push("White is up " + gap);
  if (gap < 0) bits.push("Black is up " + -gap);
  if (pos.status) bits.push(pos.status);
  return bits.length ? bits.join(" · ") : "No captures yet.";
}

function describeResult(result) {
  if (!result || result === "*") return "The game continues.";
  if (result === "1-0") return "White wins.";
  if (result === "0-1") return "Black wins.";
  return "Draw.";
}

export function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}
