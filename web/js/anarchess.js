/*
 * TALOS - browser edition: the Anarchess tab.
 *
 * Anarchess grows on an implicit grid - there is no board edge - so this is a
 * canvas with a viewport that follows the land, not a fixed 8x8 widget.
 *
 * The rules live in Python (lc/anarchess/rules.py) and are the same file the
 * desktop app uses; this view only draws the snapshot it is handed and sends
 * back the action the player clicked.
 */

const TRIBE_COLOURS = ["#f2ede1", "#3a3550", "#4cc2ff", "#f0b429"];
const LIGHT_TILE = "#eee3cc";
const DARK_TILE = "#8d6a48";

export class AnarchessView {
  constructor(app) {
    this.app = app;
    this.canvas = document.getElementById("an-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.el = {
      status: document.getElementById("an-status"),
      hint: document.getElementById("an-hint"),
      players: document.getElementById("an-players"),
      list: document.getElementById("an-players-list"),
      level: document.getElementById("an-level"),
      mode: document.getElementById("an-mode"),
      tiles: document.getElementById("an-tiles"),
      pass: document.getElementById("btn-anpass"),
    };
    this.state = null;
    this.legal = { tiles: [], pawns: [], can_pass: false };
    this.source = null;
    this.busy = false;
    this.hover = null;

    this.canvas.addEventListener("click", (e) => this._click(e));
    this.canvas.addEventListener("mousemove", (e) => {
      const cell = this._cellAt(e);
      if (cell && (!this.hover || this.hover.x !== cell.cx || this.hover.y !== cell.cy)) {
        this.hover = cell;
        this.draw();
      }
    });
    window.addEventListener("resize", () => this.draw());

    document.getElementById("btn-annew").addEventListener("click", () => this.newGame());
    document.getElementById("btn-anpass").addEventListener("click", () => this.pass());
    this.el.players.addEventListener("change", () => {
      this.app.set("anPlayers", Number(this.el.players.value));
      this.newGame();
    });
    this.el.level.addEventListener("change", () => this.app.set("anLevel", Number(this.el.level.value)));
    for (const key of ["mode", "tiles"]) {
      this.el[key].addEventListener("change", () => {
        this.app.set(key === "mode" ? "anMode" : "anTiles", this.el[key].value);
        if (key === "mode") this._syncMode();
        this.newGame();
      });
    }
    this.el.players.value = String(this.app.settings.anPlayers || 2);
    this.el.level.value = String(this.app.settings.anLevel || 2);
    this.el.mode.value = String(this.app.settings.anMode || "standard");
    this.el.tiles.value = String(this.app.settings.anTiles || 32);
    this._syncMode();
  }

  /** The die decides the tile colour, so all the client sets is the
   *  variant and how big the land is. */
  rules() {
    return { mode: this.el.mode.value,
             tiles_per_colour: Number(this.el.tiles.value) };
  }

  _solo() {
    return this.el.mode.value === "solo";
  }

  _syncMode() {
    const solo = this._solo();
    // SOLO is one person playing two tribes. Keep the normal table size in
    // saved settings, but show and submit the only valid two-tribe setup.
    this.el.players.disabled = solo;
    this.el.level.disabled = solo;
    this.el.players.value = String(solo ? 2 : (this.app.settings.anPlayers || 2));
  }

  _pawnPlayer() {
    return Number.isInteger(this.state && this.state.pawn_player)
      ? this.state.pawn_player : this.state.current;
  }

  async newGame() {
    if (this.busy) return;
    this._syncMode();
    this.source = null;
    const players = this._solo() ? 2 : Number(this.el.players.value);
    const seed = Math.floor(Math.random() * 1e9);
    this.state = await this.app.engine.json(
      "anarchess_new", [players, JSON.stringify(this.rules()), seed]);
    await this.refresh();
    await this.runBots();
  }

  async refresh() {
    if (!this.state) return;
    this.legal = await this.app.engine.json(
      "anarchess_legal", [JSON.stringify(this.state)]);
    this._panel();
    this.draw();
  }

  async apply(action) {
    const res = await this.app.engine.json(
      "anarchess_apply", [JSON.stringify(this.state), JSON.stringify(action)]);
    if (!res || !res.ok) return false;
    this.state = res.state;
    this.source = null;
    await this.refresh();
    return true;
  }

  async pass() {
    if (this.busy || !this.state || this.state.finished) return;
    if (!this.phase() || !this.legal.can_pass) return;
    await this.apply({ kind: "pass" });
    await this.runBots();
  }

  /** false = lay a tile, true = the optional pawn action. */
  phase() {
    return !!(this.legal && (this.legal.tiles || []).length === 0);
  }

  async _click(event) {
    if (this.busy || !this.state || this.state.finished) return;
    const solo = !!(this.state.rules && this.state.rules.solo);
    if (this.state.current !== 0 && !solo) return;   // in solo you play both
    const spot = this._cellAt(event);
    if (!spot) return;
    const cx = spot.cx;
    const cy = spot.cy;

    if (!this.phase()) {
      const cell = (this.legal.tiles || []).find((t) => t.x === cx && t.y === cy);
      if (!cell) return;
      // The die named the colour before the turn began; the client sends
      // back the colour the server offered rather than picking one.
      await this.apply({ kind: "tile", x: cx, y: cy, colour: cell.colour });
      if (this.state.placed && this.state.finished) return;
      await this.runBots();
      return;
    }

    const pawns = this.legal.pawns || [];
    if (this.source) {
      const hit = pawns.find((a) => a.fx === this.source[0] && a.fy === this.source[1]
        && a.x === cx && a.y === cy);
      if (hit) {
        await this.apply({ kind: hit.kind, x: hit.x, y: hit.y, fx: hit.fx, fy: hit.fy });
        await this.runBots();
        return;
      }
      this.source = null;
      this.draw();
      return;
    }
    const settle = pawns.find((a) => a.kind === "settle" && a.x === cx && a.y === cy);
    if (settle) {
      await this.apply({ kind: "settle", x: settle.x, y: settle.y });
      await this.runBots();
      return;
    }
    const mine = this.state.pawns.find((p) => p[0] === cx && p[1] === cy
      && p[2] === this._pawnPlayer());
    if (mine && pawns.some((a) => a.fx === cx && a.fy === cy)) {
      this.source = [cx, cy];
      this.draw();
    }
  }

  async runBots() {
    if (this.busy) return;
    // SOLO is one human playing both tribes: there is nobody else to ask.
    if (this.state && this.state.rules && this.state.rules.solo) return;
    this.busy = true;
    try {
      let guard = 0;
      while (this.state && !this.state.finished && this.state.current !== 0 && guard < 40) {
        guard += 1;
        const answer = await this.app.engine.json(
          "anarchess_bot", [JSON.stringify(this.state), Number(this.el.level.value), null]);
        const actions = (answer && answer.actions) || [];
        if (!actions.length) break;
        for (const action of actions) {
          await this.apply(action);
          await wait(this.state.finished ? 0 : 220);
          if (this.state.finished) break;
        }
      }
    } finally {
      this.busy = false;
      this._panel();
      this.draw();
    }
  }

  /* ------------------------------------------------------------- drawing -- */

  _cellAt(event) {
    const rect = this.canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const cx = Math.floor((px - this.ox) / this.cell);
    const cy = Math.floor((py - this.oy) / this.cell);
    const u = (px - this.ox) / this.cell - cx;
    const v = (py - this.oy) / this.cell - cy;
    return { cx, cy, u, v };
  }

  bounds() {
    let minX = 0;
    let maxX = 7;
    let minY = 0;
    let maxY = 7;
    const cells = [];
    for (const t of this.state.tiles) cells.push([t[0], t[1]]);
    for (const t of this.legal.tiles || []) cells.push([t.x, t.y]);
    if (cells.length) {
      minX = Math.min.apply(null, cells.map((c) => c[0]));
      maxX = Math.max.apply(null, cells.map((c) => c[0]));
      minY = Math.min.apply(null, cells.map((c) => c[1]));
      maxY = Math.max.apply(null, cells.map((c) => c[1]));
    }
    return { minX: minX - 1, maxX: maxX + 1, minY: minY - 1, maxY: maxY + 1 };
  }

  draw() {
    const canvas = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 480;
    const h = canvas.clientHeight || 480;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#12151c";
    ctx.fillRect(0, 0, w, h);
    if (!this.state) return;

    const b = this.bounds();
    const cols = b.maxX - b.minX + 1;
    const rows = b.maxY - b.minY + 1;
    const cell = Math.min((w - 24) / cols, (h - 24) / rows);
    this.cell = cell;
    this.ox = (w - cols * cell) / 2 - b.minX * cell;
    this.oy = (h - rows * cell) / 2 - b.minY * cell;
    const px = (x) => this.ox + x * cell;
    const py = (y) => this.oy + y * cell;
    const pad = Math.max(1, cell * 0.05);

    // The empty land, drawn faintly. The land is unbounded, so the dark part
    // of the canvas is not "off the board" - it is somewhere a tile can still
    // go. Without this the view reads as fog rather than as a board.
    const filled = new Set(this.state.tiles.map((t) => t[0] + "," + t[1]));
    const growX = Math.ceil((w / cell - cols) / 2) + 1;
    const growY = Math.ceil((h / cell - rows) / 2) + 1;
    ctx.strokeStyle = "rgba(86, 95, 116, 0.30)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let gx = b.minX - growX; gx <= b.maxX + growX; gx += 1) {
      for (let gy = b.minY - growY; gy <= b.maxY + growY; gy += 1) {
        if (filled.has(gx + "," + gy)) continue;
        ctx.rect(px(gx) + pad, py(gy) + pad, cell - pad * 2, cell - pad * 2);
      }
    }
    ctx.stroke();

    // the land
    for (const tile of this.state.tiles) {
      ctx.fillStyle = tile[2] ? LIGHT_TILE : DARK_TILE;
      roundRect(ctx, px(tile[0]) + pad, py(tile[1]) + pad, cell - pad * 2, cell - pad * 2,
        Math.max(2, cell * 0.08));
      ctx.fill();
    }

    // areas of two or more tiles are what score: outline them
    for (const area of this.state.areas) {
      if (area.size < 2) continue;
      ctx.save();
      ctx.strokeStyle = area.owner === null || area.owner === undefined
        ? "rgba(240, 180, 41, 0.20)"
        : withAlpha(TRIBE_COLOURS[area.owner] || "#f0b429", 0.85);
      if (area.taxed) {
        // the largest area is taxed down to one point a tile: broken outline
        ctx.setLineDash([Math.max(4, cell * 0.14), Math.max(3, cell * 0.10)]);
      }
      ctx.lineWidth = Math.max(1.5, cell * 0.05);
      for (const [x, y] of area.cells) {
        ctx.beginPath();
        for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1]]) {
          if (area.cells.some((c) => c[0] === x + dx && c[1] === y + dy)) continue;
          const x0 = px(x) + pad;
          const y0 = py(y) + pad;
          const size = cell - pad * 2;
          ctx.moveTo(x0 + (dx === -1 ? 0 : dx === 1 ? size : 0),
            y0 + (dy === -1 ? 0 : dy === 1 ? size : 0));
          ctx.lineTo(x0 + (dx === -1 ? 0 : size), y0 + (dy === -1 ? 0 : size));
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    // what each area is worth, so the tax and the bonuses are visible
    if (cell > 24) {
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const area of this.state.areas) {
        if (area.size < 2) continue;
        let mx = 0;
        let my = 0;
        for (const c of area.cells) { mx += c[0]; my += c[1]; }
        mx /= area.cells.length;
        my /= area.cells.length;
        let best = area.cells[0];
        let bd = Infinity;
        for (const c of area.cells) {
          const d = (c[0] - mx) ** 2 + (c[1] - my) ** 2;
          if (d < bd) { bd = d; best = c; }
        }
        const owned = area.owner !== null && area.owner !== undefined;
        const label = owned ? area.size + "x" + area.rate : String(area.size);
        const bw = Math.max(20, cell * 0.62);
        const bh = Math.max(12, cell * 0.27);
        const bx = px(best[0]) + cell / 2 - bw / 2;
        const by = py(best[1]) + cell - bh - Math.max(1.5, cell * 0.07);
        ctx.fillStyle = "rgba(12, 14, 20, 0.80)";
        roundRect(ctx, bx, by, bw, bh, Math.min(4, bh / 3));
        ctx.fill();
        ctx.fillStyle = owned ? (TRIBE_COLOURS[area.owner] || "#f0b429") : "#c8d0e0";
        ctx.font = "600 " + Math.max(8, Math.round(cell * 0.21))
          + "px system-ui, sans-serif";
        ctx.fillText(label, bx + bw / 2, by + bh / 2 + 0.5);
      }
    }

    // where a tile may go: one ghost, in the colour the die named
    const humanTurn = this.state.current === 0
      || !!(this.state.rules && this.state.rules.solo);
    if (humanTurn && !this.state.finished) {
      for (const t of this.legal.tiles || []) {
        const x0 = px(t.x) + pad;
        const y0 = py(t.y) + pad;
        const size = cell - pad * 2;
        ctx.save();
        ctx.globalAlpha = 0.5;
        ctx.fillStyle = this.state.drawn ? LIGHT_TILE : DARK_TILE;
        roundRect(ctx, x0, y0, size, size, Math.max(2, cell * 0.08));
        ctx.fill();
        ctx.restore();
        ctx.save();
        ctx.setLineDash([Math.max(3, cell * 0.12), Math.max(3, cell * 0.09)]);
        ctx.strokeStyle = "#f0b429";
        ctx.lineWidth = Math.max(1.2, cell * 0.035);
        ctx.strokeRect(x0, y0, size, size);
        ctx.restore();
      }
      for (const a of this.legal.pawns || []) {
        const colour = a.kind === "attack" ? "#e05a4f"
          : a.kind === "settle" ? "#4cc2ff" : "#7ee081";
        ctx.save();
        ctx.setLineDash([Math.max(2, cell * 0.09), Math.max(2, cell * 0.07)]);
        ctx.strokeStyle = colour;
        ctx.lineWidth = Math.max(1.2, cell * 0.035);
        ctx.beginPath();
        ctx.arc(px(a.x) + cell / 2, py(a.y) + cell / 2, cell * 0.22, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }

    // the tribes
    for (const pawn of this.state.pawns) {
      const [x, y, owner] = pawn;
      const cx = px(x) + cell / 2;
      const cy = py(y) + cell / 2;
      const r = cell * 0.28;
      ctx.beginPath();
      ctx.arc(cx, cy, r + Math.max(1, cell * 0.03), 0, Math.PI * 2);
      ctx.fillStyle = "rgba(10, 12, 16, 0.55)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = TRIBE_COLOURS[owner] || "#f0b429";
      ctx.fill();
      ctx.lineWidth = Math.max(1, cell * 0.02);
      ctx.strokeStyle = "rgba(0, 0, 0, 0.5)";
      ctx.stroke();
      if (this.source && this.source[0] === x && this.source[1] === y) {
        ctx.beginPath();
        ctx.arc(cx, cy, r * 1.55, 0, Math.PI * 2);
        ctx.strokeStyle = "#f0b429";
        ctx.lineWidth = Math.max(1.5, cell * 0.05);
        ctx.stroke();
      }
    }

    // final scores
    if (this.state.finished && this.state.final) {
      ctx.fillStyle = "rgba(10, 12, 16, 0.78)";
      ctx.fillRect(0, h / 2 - 34, w, 68);
      ctx.fillStyle = "#f2ede1";
      ctx.font = "600 18px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Final scores — " + this.state.names.map(
        (n, i) => n + " " + this.state.final[i]).join("   "), w / 2, h / 2 + 6);
    }
  }

  _panel() {
    const s = this.state;
    if (!s) return;
    this.el.status.textContent = s.status;
    const solo = !!(s.rules && s.rules.solo);
    const canPass = !!(this.legal && this.legal.can_pass);
    this.el.pass.disabled = s.finished || !canPass;
    this.el.pass.textContent = solo && canPass
      ? "Pass (no pawn action)" : "Skip pawn action";
    this.el.hint.textContent = s.finished
      ? (solo ? "Solo: " + s.solo_score + " of " + s.target + " points" : "Game over")
      : s.current === 0 || solo
        ? (this.phase()
            ? (solo ? "Pawn action (required when possible)" : "Pawn action (optional)")
            : "Lay a " + (s.drawn ? "light" : "dark") + " tile")
        : s.names[s.current] + " is thinking…";
    const rows = s.names.map((name, i) => {
      const onLand = s.pawns.filter((p) => p[2] === i).length;
      return '<div class="tribe' + (i === s.current && !s.finished ? " turn" : "") + '">' +
        '<i class="dot" style="background:' + TRIBE_COLOURS[i] + '"></i>' +
        '<span class="who">' + escapeText(name) + "</span>" +
        '<span class="pts">' + (s.final ? s.final[i] : s.scores[i]) + "</span>" +
        '<span class="res">' + onLand + " placed · " + s.reserve[i] + " free</span>" +
        "</div>";
    });
    this.el.list.innerHTML = rows.join("") +
      '<p class="dim small">Supply: ' + s.supply.light + " light, " +
      s.supply.dark + " dark tiles · " + s.left + " left" +
      (solo && s.target ? " · solo target " + s.target : "") + "</p>";
  }
}

/* --------------------------------------------------------------- helpers -- */

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
}

function escapeText(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
