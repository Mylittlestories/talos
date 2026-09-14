/*
 * TALOS - browser edition: the responsive chess board widget.
 *
 * The grid knows nothing about the engine; callers hand it the JSON returned
 * by bridge.position and it calls back with a UCI move.  Pieces are inline
 * vector silhouettes rather than font glyphs, so every browser has the same
 * artwork and the graphics always scale with their square—not the viewport.
 */

export const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];

/* The desktop app draws its own procedural silhouettes. These compact SVG
 * paths are their browser counterpart: self-contained, resolution-independent
 * and free from OS emoji/chess-font substitutions. */
const SHAPES = {
  p: [
    '<circle cx="50" cy="23" r="11"/>',
    '<path d="M39 77 43 43h14l4 34Z"/>',
    '<ellipse cx="50" cy="43" rx="16" ry="5"/>',
    '<path d="M25 86q3-8 13-8h24q10 0 13 8Z"/>',
    '<ellipse cx="50" cy="88" rx="27" ry="7"/>',
  ],
  r: [
    '<path d="M26 15h11v8h7v-8h12v8h7v-8h11v22H67l-4 41H37l-4-41h-7Z"/>',
    '<ellipse cx="50" cy="80" rx="19" ry="5"/>',
    '<path d="M21 89q4-9 15-9h28q11 0 15 9Z"/>',
    '<ellipse cx="50" cy="91" rx="29" ry="7"/>',
  ],
  n: [
    '<path d="M30 80q0-19 6-29-7-15 1-27l5 9q7-12 14-17l5 13q13 7 12 18-1 9-12 10l-4 22Z"/>',
    '<path d="M39 48q9 5 20 0M58 36h1" class="detail"/>',
    '<ellipse cx="50" cy="81" rx="21" ry="5"/>',
    '<path d="M22 90q4-9 15-9h26q11 0 15 9Z"/>',
    '<ellipse cx="50" cy="92" rx="29" ry="7"/>',
  ],
  b: [
    '<path d="M39 78 43 47h14l4 31Z"/>',
    '<ellipse cx="50" cy="47" rx="16" ry="5"/>',
    '<path d="M50 12q17 16 12 32H38Q33 28 50 12Z"/>',
    '<path d="m55 19-10 17" class="detail"/>',
    '<circle cx="50" cy="10" r="4"/>',
    '<ellipse cx="50" cy="80" rx="20" ry="5"/>',
    '<path d="M22 89q4-9 15-9h26q11 0 15 9Z"/>',
    '<ellipse cx="50" cy="91" rx="29" ry="7"/>',
  ],
  q: [
    '<path d="M36 79 40 43h20l4 36Z"/>',
    '<ellipse cx="50" cy="43" rx="18" ry="5"/>',
    '<path d="M32 40 26 18l14 12 10-20 10 20 14-12-6 22Z"/>',
    '<circle cx="26" cy="16" r="4"/><circle cx="40" cy="28" r="4"/>',
    '<circle cx="50" cy="8" r="4"/><circle cx="60" cy="28" r="4"/><circle cx="74" cy="16" r="4"/>',
    '<ellipse cx="50" cy="81" rx="22" ry="5"/>',
    '<path d="M20 90q5-9 16-9h28q11 0 16 9Z"/>',
    '<ellipse cx="50" cy="92" rx="31" ry="7"/>',
  ],
  k: [
    '<path d="M36 79 40 45h20l4 34Z"/>',
    '<ellipse cx="50" cy="45" rx="18" ry="5"/>',
    '<path d="M33 42q2-17 10-20 7 5 7 11 0-6 7-11 8 3 10 20Z"/>',
    '<path d="M50 5v16M42 12h16" class="detail"/>',
    '<ellipse cx="50" cy="81" rx="22" ry="5"/>',
    '<path d="M20 90q5-9 16-9h28q11 0 16 9Z"/>',
    '<ellipse cx="50" cy="92" rx="31" ry="7"/>',
  ],
};

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

function pieceSvg(piece) {
  const fill = piece.white ? "#fdfbf5" : "#252a35";
  const stroke = piece.white ? "#2b2a27" : "#d8d0c0";
  const detail = piece.white ? "#786f62" : "#f0e8dc";
  const shape = (SHAPES[piece.type] || SHAPES.p).join("");
  return '<svg class="piece ' + (piece.white ? "w" : "b") +
    '" viewBox="0 0 100 100" aria-hidden="true" focusable="false">' +
    '<g fill="' + fill + '" stroke="' + stroke + '" stroke-width="3" ' +
    'stroke-linejoin="round" stroke-linecap="round">' + shape + "</g>" +
    '<style>.detail{fill:none;stroke:' + detail + ';stroke-width:3.2}</style></svg>';
}

export class Board {
  constructor(el, options) {
    const opts = options || {};
    this.el = el;
    this.frame = el.closest(".boardwrap") || el.parentElement;
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

    // A square's actual rendered width is the only reliable source for the
    // surrounding coordinate gutter. ResizeObserver also catches flex/grid
    // changes which do not emit window.resize (side panels, rotation, zoom).
    this._syncScale = () => {
      const rect = this.el.getBoundingClientRect();
      const width = rect.width || this.el.clientWidth || 0;
      if (!width || !this.frame) return;
      const square = width / 8;
      this.frame.style.setProperty("--board-square", square.toFixed(3) + "px");
      this.frame.style.setProperty("--coordinate-size", Math.max(9, Math.min(13, square * 0.20)).toFixed(2) + "px");
      this.frame.style.setProperty("--coordinate-gutter", Math.max(15, Math.min(22, square * 0.38)).toFixed(2) + "px");
      this.frame.style.setProperty("--capture-ring", Math.max(2, Math.min(5, square * 0.065)).toFixed(2) + "px");
    };
    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(() => this._syncScale());
      this.resizeObserver.observe(el);
    } else {
      window.addEventListener("resize", this._syncScale, { passive: true });
    }
    this._syncScale();
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
      cell.innerHTML = piece ? pieceSvg(piece) : "";
      cell.title = sq;
      cell.setAttribute("aria-label", piece
        ? sq + ", " + (piece.white ? "White " : "Black ") + pieceName(piece.type)
        : sq + ", empty");
    }
    this._syncScale();
  }

  _click(event) {
    if (!this.interactive || !this.pos) return;
    const cell = event.target.closest(".sq");
    if (!cell || !this.el.contains(cell)) return;
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

function pieceName(type) {
  return ({ p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" })[type] || "piece";
}

/** A bare "e7e8" click on a promotion means queen - that is what everyone wants. */
function promote(uci, moves) {
  const exact = moves.find((m) => m.slice(0, 4) === uci.slice(0, 4) && m[4] === "q");
  return exact || uci;
}
