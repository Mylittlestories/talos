/*
 * TALOS - browser edition: the chess board widget.
 *
 * A tiny DOM board: 64 divs, unicode pieces, no dependencies.  It knows
 * nothing about the engine; the caller hands it the JSON that bridge.position
 * returns and it calls back with a UCI move.
 */

export const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];

const GLYPH = { k: "\u265A", q: "\u265B", r: "\u265C", b: "\u265D", n: "\u265E", p: "\u265F" };

/** Parse the placement field of a FEN into a Map of square -> {type, white}. */
export function parseFen(fen) {
  const out = new Map();
  const placement = (fen || "").split(" ")[0] || "";
  let rank = 8;
  let file = 0;
  for (const ch of placement) {
    if (ch === "/") {
      rank -= 1;
      file = 0;
    } else if (ch >= "1" && ch <= "8") {
      file += Number(ch);
    } else {
      out.set(FILES[file] + rank, { type: ch.toLowerCase(), white: ch === ch.toUpperCase() });
      file += 1;
    }
  }
  return out;
}

export class Board {
  constructor(el, options) {
    const opts = options || {};
    this.el = el;
    this.flipped = false;
    this.interactive = true;
    this.onMove = opts.onMove || null;
    this.onSelect = opts.onSelect || null;
    this.pos = null;
    this.selected = null;
    this.last = null;
    this.hint = null;

    this.cells = [];
    for (let i = 0; i < 64; i += 1) {
      const cell = document.createElement("div");
      cell.className = "sq";
      cell.dataset.index = String(i);
      el.appendChild(cell);
      this.cells.push(cell);
    }
    el.addEventListener("click", (event) => this._click(event));
  }

  /** Which square does DOM cell `index` show, honouring the flip? */
  squareAt(index) {
    const file = this.flipped ? 7 - (index % 8) : index % 8;
    const rank = this.flipped ? 1 + Math.floor(index / 8) : 8 - Math.floor(index / 8);
    return FILES[file] + rank;
  }

  setPosition(pos, options) {
    const opts = options || {};
    this.pos = pos;
    if ("last" in opts) this.last = opts.last;
    if ("hint" in opts) this.hint = opts.hint;
    if (!opts.keepSelection) this.selected = null;
    this.render();
  }

  setFlipped(value) {
    this.flipped = !!value;
    this.render();
  }

  clearMarks() {
    this.selected = null;
    this.hint = null;
    this.render();
  }

  render() {
    const pos = this.pos;
    if (!pos) return;
    const occupied = parseFen(pos.fen);
    const moves = pos.moves || [];
    const targets = new Map();
    if (this.selected) {
      for (const uci of moves) {
        if (uci.slice(0, 2) === this.selected) targets.set(uci.slice(2, 4), uci);
      }
    }
    for (let i = 0; i < 64; i += 1) {
      const sq = this.squareAt(i);
      const file = FILES.indexOf(sq[0]);
      const rank = Number(sq[1]);
      const cls = ["sq", (file + rank) % 2 === 0 ? "light" : "dark"];
      if (sq === this.selected) cls.push("sel");
      if (this.last) {
        if (sq === this.last.slice(0, 2)) cls.push("from");
        if (sq === this.last.slice(2, 4)) cls.push("last");
      }
      if (this.hint && sq === this.hint) cls.push("hint");
      if (targets.has(sq)) cls.push(occupied.has(sq) ? "capture" : "target");
      if (pos.check_square === sq) cls.push("check");
      const cell = this.cells[i];
      cell.className = cls.join(" ");
      const piece = occupied.get(sq);
      cell.innerHTML = piece
        ? '<span class="piece ' + (piece.white ? "w" : "b") + '">' + GLYPH[piece.type] + "</span>"
        : "";
      cell.title = sq;
    }
  }

  _click(event) {
    if (!this.interactive || !this.pos) return;
    const cell = event.target.closest(".sq");
    if (!cell) return;
    const sq = this.squareAt(Number(cell.dataset.index));
    const moves = this.pos.moves || [];

    if (this.selected) {
      const found = moves.find((m) => m.slice(0, 2) === this.selected && m.slice(2, 4) === sq);
      if (found) {
        const chosen = found.length === 4 ? promote(found, moves) : found;
        this.selected = null;
        if (this.onMove) this.onMove(chosen);
        this.render();
        return;
      }
    }
    const piece = parseFen(this.pos.fen).get(sq);
    if (piece && moves.some((m) => m.slice(0, 2) === sq)) {
      this.selected = sq;
      if (this.onSelect) this.onSelect(sq);
    } else {
      this.selected = null;
    }
    this.render();
  }
}

/** A bare "e7e8" click on a promotion means queen - that is what everyone wants. */
function promote(uci, moves) {
  const exact = moves.find((m) => m.slice(0, 4) === uci.slice(0, 4) && m[4] === "q");
  return exact || uci;
}
