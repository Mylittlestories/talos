/*
 * TALOS — the three dedicated land-game views.
 *
 * Anarchess, Anarchess SOLO and Anarcheckers share an unbounded tiled land,
 * but they are separate first-class entries in the browser.  The Python model
 * remains authoritative for rules and legal actions; this module owns only
 * presentation, camera controls and pointer interaction.
 */

const TRIBE_COLOURS = ["#f2ede1", "#3a3550", "#4cc2ff", "#f0b429"];
const LIGHT_TILE = "#eee3cc";
const DARK_TILE = "#8d6a48";
const MIN_ZOOM = 0.58;
const MAX_ZOOM = 2.4;

export class AnarchessView {
  constructor(app, name = "anarchess") {
    this.app = app;
    this.name = name;
    this.root = document.getElementById("view-" + name);
    if (!this.root) throw new Error("missing land-game view: " + name);
    this.mode = this.root.dataset.landMode || "standard";
    this.settingsKey = this.root.dataset.landSettings || name;
    this.canvas = this.root.querySelector("[data-land-canvas]");
    this.ctx = this.canvas.getContext("2d");
    this.el = {
      status: this.root.querySelector("[data-land-status]"),
      hint: this.root.querySelector("[data-land-hint]"),
      players: this.root.querySelector("[data-land-players]"),
      list: this.root.querySelector("[data-land-list]"),
      level: this.root.querySelector("[data-land-level]"),
      opponentNote: this.root.querySelector("[data-land-opponent-note]"),
      tiles: this.root.querySelector("[data-land-tiles]"),
      pass: this.root.querySelector("[data-land-pass]"),
      fresh: this.root.querySelector("[data-land-new]"),
      centre: this.root.querySelector("[data-land-center]"),
      zoom: Array.from(this.root.querySelectorAll("[data-land-zoom]")),
    };
    this.state = null;
    this.legal = { tiles: [], pawns: [], can_pass: false };
    this.source = null;
    this.busy = false;
    this.hover = null;
    this.drag = null;
    this.camera = { x: 0.5, y: 0.5, zoom: 1 };
    this.metrics = { width: 0, height: 0, cell: 0 };
    this.ox = 0;
    this.oy = 0;
    this.cell = 0;
    this.levels = [];

    this._wireCanvas();
    this._wireControls();
    this._restoreControls();
  }

  /** Populate the opponent selector from the same source as the desktop UI. */
  async start() {
    if (!this.el.level) return;
    this.levels = await this.app.engine.json("anarchess_levels");
    this.el.level.innerHTML = this.levels.map((level) =>
      '<option value="' + level.level + '" title="' + escapeAttr(level.tip) + '">' +
      escapeText(level.name) + "</option>").join("");
    const requested = String(this._setting("level", 2));
    this.el.level.value = this.levels.some((level) => String(level.level) === requested)
      ? requested : String(Math.min(2, this.levels.length));
    this._updateOpponentNote();
  }

  // ---------------------------------------------------------------- setup --

  _setting(field, fallback) {
    const key = this.settingsKey + field[0].toUpperCase() + field.slice(1);
    const value = this.app.settings[key];
    return value === undefined || value === null ? fallback : value;
  }

  _save(field, value) {
    const key = this.settingsKey + field[0].toUpperCase() + field.slice(1);
    this.app.set(key, value);
  }

  _restoreControls() {
    if (this.el.players) this.el.players.value = String(this._setting("players", 2));
    if (this.el.tiles) this.el.tiles.value = String(this._setting("tiles", 32));
  }

  _wireControls() {
    this.el.fresh.addEventListener("click", () => this.newGame());
    this.el.pass.addEventListener("click", () => this.pass());
    if (this.el.players) {
      this.el.players.addEventListener("change", () => {
        this._save("players", Number(this.el.players.value));
        this.newGame();
      });
    }
    if (this.el.level) {
      this.el.level.addEventListener("change", () => {
        this._save("level", Number(this.el.level.value));
        this._updateOpponentNote();
      });
    }
    if (this.el.tiles) {
      this.el.tiles.addEventListener("change", () => {
        this._save("tiles", Number(this.el.tiles.value));
        this.newGame();
      });
    }
    for (const button of this.el.zoom) {
      button.addEventListener("click", () => {
        const kind = button.dataset.landZoom;
        if (kind === "reset") this.resetCamera();
        else this.zoomAt(kind === "in" ? 1.2 : 1 / 1.2);
      });
    }
    this.el.centre.addEventListener("click", () => this.centreLand());
  }

  _wireCanvas() {
    this.canvas.addEventListener("pointerdown", (event) => this._pointerDown(event));
    this.canvas.addEventListener("pointermove", (event) => this._pointerMove(event));
    this.canvas.addEventListener("pointerup", (event) => this._pointerUp(event));
    this.canvas.addEventListener("pointercancel", () => { this.drag = null; });
    this.canvas.addEventListener("pointerleave", () => {
      if (!this.drag && this.hover) {
        this.hover = null;
        this.draw();
      }
    });
    this.canvas.addEventListener("wheel", (event) => this._wheel(event), { passive: false });
    this.canvas.addEventListener("keydown", (event) => this._key(event));

    const redraw = () => this.draw();
    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(redraw);
      this.resizeObserver.observe(this.canvas);
    } else {
      window.addEventListener("resize", redraw, { passive: true });
    }
    if (window.visualViewport) window.visualViewport.addEventListener("resize", redraw, { passive: true });
  }

  _updateOpponentNote() {
    if (!this.el.level || !this.el.opponentNote) return;
    const selected = this.levels.find((level) => String(level.level) === this.el.level.value);
    this.el.opponentNote.textContent = selected ? selected.tip : "";
  }

  /** The die decides the tile colour; the page chooses only game size. */
  rules() {
    return { mode: this.mode, tiles_per_colour: Number(this.el.tiles.value) };
  }

  _solo() {
    return this.mode === "solo";
  }

  _pawnPlayer() {
    return Number.isInteger(this.state && this.state.pawn_player)
      ? this.state.pawn_player : this.state.current;
  }

  async activate() {
    if (!this.state) await this.newGame();
    else this.draw();
  }

  async newGame() {
    if (this.busy) return;
    // A new state crosses the worker boundary. Hold the same small lock used
    // for opponent turns so double-clicks cannot race two game snapshots.
    this.busy = true;
    try {
      this.source = null;
      this.hover = null;
      this.resetCamera(false);
      const players = this._solo() ? 2 : Number(this.el.players.value);
      const seed = Math.floor(Math.random() * 1e9);
      this.state = await this.app.engine.json(
        "anarchess_new", [players, JSON.stringify(this.rules()), seed]);
      await this.refresh();
    } finally {
      this.busy = false;
    }
    await this.runBots();
  }

  async refresh() {
    if (!this.state) return;
    this.legal = await this.app.engine.json(
      "anarchess_legal", [JSON.stringify(this.state)]);
    // A compulsory Anarcheckers chain is not another free pawn choice. Keep
    // its piece visibly selected so the player can click the next landing
    // tile directly, even after a redraw or a restored browser session.
    if (Array.isArray(this.state.chain) && this.state.chain.length === 2) {
      this.source = [this.state.chain[0], this.state.chain[1]];
    } else if (this.source && !(this.legal.pawns || []).some((action) =>
      action.fx === this.source[0] && action.fy === this.source[1])) {
      this.source = null;
    }
    this._panel();
    this.draw();
  }

  async apply(action) {
    const res = await this.app.engine.json(
      "anarchess_apply", [JSON.stringify(this.state), JSON.stringify(action)]);
    if (!res || !res.ok) return false;
    this.state = res.state;
    this.source = null;
    const focus = action && action.cell ? action.cell
      : action && Number.isFinite(action.x) && Number.isFinite(action.y) ? [action.x, action.y] : null;
    if (focus) this._ensureVisible(focus[0], focus[1]);
    await this.refresh();
    return true;
  }

  async pass() {
    if (this.busy || !this.state || this.state.finished) return;
    if (!this.phase() || !this.legal.can_pass) return;
    if (await this.apply({ kind: "pass" })) await this.runBots();
  }

  /** false = lay a tile, true = pawn action (possibly an Anarcheckers chain). */
  phase() {
    return !!(this.state && this.state.placed);
  }

  _humanTurn() {
    return !!(this.state && (this.state.current === 0 || this._solo()));
  }

  // ------------------------------------------------------------- interaction

  _pointerDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    this.drag = {
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      cameraX: this.camera.x,
      cameraY: this.camera.y,
      moved: false,
    };
    try { this.canvas.setPointerCapture(event.pointerId); } catch (_err) { /* older browser */ }
  }

  _pointerMove(event) {
    if (this.drag && event.pointerId === this.drag.id) {
      const dx = event.clientX - this.drag.startX;
      const dy = event.clientY - this.drag.startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) this.drag.moved = true;
      if (this.drag.moved && this.cell > 0) {
        this.camera.x = this.drag.cameraX - dx / this.cell;
        this.camera.y = this.drag.cameraY - dy / this.cell;
        this.draw();
      }
      return;
    }
    const cell = this._cellAt(event);
    if (cell && (!this.hover || this.hover.x !== cell.x || this.hover.y !== cell.y)) {
      this.hover = cell;
      this.draw();
    }
  }

  _pointerUp(event) {
    if (!this.drag || event.pointerId !== this.drag.id) return;
    const wasDrag = this.drag.moved;
    this.drag = null;
    try { this.canvas.releasePointerCapture(event.pointerId); } catch (_err) { /* older browser */ }
    if (!wasDrag) void this._click(event);
  }

  _wheel(event) {
    // Preserve ordinary page scrolling. Ctrl/⌘-wheel is the conventional
    // precision zoom gesture and works with trackpad pinch zoom too.
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    this.zoomAt(Math.pow(1.16, -event.deltaY / 100), event.clientX, event.clientY);
  }

  _key(event) {
    const step = 1.4 / this.camera.zoom;
    if (event.key === "+" || event.key === "=") {
      event.preventDefault(); this.zoomAt(1.2); return;
    }
    if (event.key === "-") {
      event.preventDefault(); this.zoomAt(1 / 1.2); return;
    }
    if (event.key === "0") {
      event.preventDefault(); this.resetCamera(); return;
    }
    const shifts = { ArrowLeft: [-step, 0], ArrowRight: [step, 0],
      ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (shifts[event.key]) {
      event.preventDefault();
      this.camera.x += shifts[event.key][0];
      this.camera.y += shifts[event.key][1];
      this.draw();
    }
  }

  async _click(event) {
    if (this.busy || !this.state || this.state.finished || !this._humanTurn()) return;
    const spot = this._cellAt(event);
    if (!spot) return;
    const x = spot.x;
    const y = spot.y;

    if (!this.phase()) {
      const cell = (this.legal.tiles || []).find((tile) => tile.x === x && tile.y === y);
      if (!cell) return;
      // Send the die-selected colour offered by the model; browser code never
      // gets to choose a convenient colour for itself.
      if (await this.apply({ kind: "tile", x, y, colour: cell.colour })) {
        if (!this.state.finished) await this.runBots();
      }
      return;
    }

    const pawns = this.legal.pawns || [];
    if (this.source) {
      const hit = pawns.find((action) => action.fx === this.source[0] && action.fy === this.source[1]
        && action.x === x && action.y === y);
      if (hit && await this.apply({ kind: hit.kind, x: hit.x, y: hit.y, fx: hit.fx, fy: hit.fy })) {
        await this.runBots();
        return;
      }
      this.source = null;
      this.draw();
      return;
    }
    const settle = pawns.find((action) => action.kind === "settle" && action.x === x && action.y === y);
    if (settle && await this.apply({ kind: "settle", x: settle.x, y: settle.y })) {
      await this.runBots();
      return;
    }
    const mine = (this.state.pawns || []).find((pawn) => pawn[0] === x && pawn[1] === y
      && pawn[2] === this._pawnPlayer());
    if (mine && pawns.some((action) => action.fx === x && action.fy === y)) {
      this.source = [x, y];
      this.draw();
    }
  }

  async runBots() {
    if (this.busy || this._solo()) return;
    this.busy = true;
    try {
      let guard = 0;
      while (this.state && !this.state.finished && this.state.current !== 0 && guard < 80) {
        guard += 1;
        const answer = await this.app.engine.json(
          "anarchess_bot", [JSON.stringify(this.state), Number(this.el.level.value), null]);
        const actions = (answer && answer.actions) || [];
        if (!actions.length) break;
        for (const action of actions) {
          if (!await this.apply(action)) break;
          await wait(this.state.finished ? 0 : 180);
          if (this.state.finished || this.state.current === 0) break;
        }
      }
    } finally {
      this.busy = false;
      this._panel();
      this.draw();
    }
  }

  // --------------------------------------------------------------- camera --

  _canvasSize() {
    const rect = this.canvas.getBoundingClientRect();
    return {
      width: Math.round(rect.width || this.canvas.clientWidth || 0),
      height: Math.round(rect.height || this.canvas.clientHeight || 0),
      left: rect.left || 0,
      top: rect.top || 0,
    };
  }

  _cellSize(width, height, zoom = this.camera.zoom) {
    // Scale only with the actual visible map rectangle. Land growth never
    // shrinks existing art; a player pans or chooses zoom when it spreads.
    const base = clamp(Math.min(width, height) / 8.5, 28, 76);
    return base * zoom;
  }

  resetCamera(redraw = true) {
    this.camera.x = 0.5;
    this.camera.y = 0.5;
    this.camera.zoom = 1;
    if (redraw) this.draw();
  }

  centreLand() {
    const tiles = (this.state && this.state.tiles) || [];
    if (tiles.length) {
      const xs = tiles.map((tile) => tile[0]);
      const ys = tiles.map((tile) => tile[1]);
      this.camera.x = (Math.min(...xs) + Math.max(...xs) + 1) / 2;
      this.camera.y = (Math.min(...ys) + Math.max(...ys) + 1) / 2;
    }
    this.draw();
  }

  zoomAt(factor, clientX, clientY) {
    const size = this._canvasSize();
    const width = size.width || this.metrics.width;
    const height = size.height || this.metrics.height;
    const oldCell = this.cell || this._cellSize(width || 480, height || 480);
    const x = Number.isFinite(clientX) ? clientX - size.left : width / 2;
    const y = Number.isFinite(clientY) ? clientY - size.top : height / 2;
    const worldX = oldCell ? (x - this.ox) / oldCell : this.camera.x;
    const worldY = oldCell ? (y - this.oy) / oldCell : this.camera.y;
    this.camera.zoom = clamp(this.camera.zoom * factor, MIN_ZOOM, MAX_ZOOM);
    const cell = this._cellSize(width || 480, height || 480);
    // Keep the world coordinate under the pointer fixed. The sign matters:
    // when zooming at the right edge, the camera moves left toward that
    // coordinate rather than pushing the land away from the pointer.
    this.camera.x = worldX + (width / 2 - x) / cell;
    this.camera.y = worldY + (height / 2 - y) / cell;
    this.draw();
  }

  _ensureVisible(x, y) {
    const { width, height, cell } = this.metrics;
    if (!width || !height || !cell) return;
    const halfX = width / cell / 2;
    const halfY = height / cell / 2;
    const margin = Math.min(1.5, Math.max(0.8, Math.min(halfX, halfY) / 3));
    const targetX = x + 0.5;
    const targetY = y + 0.5;
    if (targetX < this.camera.x - halfX + margin) this.camera.x = targetX + halfX - margin;
    if (targetX > this.camera.x + halfX - margin) this.camera.x = targetX - halfX + margin;
    if (targetY < this.camera.y - halfY + margin) this.camera.y = targetY + halfY - margin;
    if (targetY > this.camera.y + halfY - margin) this.camera.y = targetY - halfY + margin;
  }

  _cellAt(event) {
    if (!this.cell) return null;
    const rect = this.canvas.getBoundingClientRect();
    const px = event.clientX - (rect.left || 0);
    const py = event.clientY - (rect.top || 0);
    const width = rect.width || this.metrics.width;
    const height = rect.height || this.metrics.height;
    if (width && height && (px < 0 || py < 0 || px > width || py > height)) return null;
    const x = Math.floor((px - this.ox) / this.cell);
    const y = Math.floor((py - this.oy) / this.cell);
    return { x, y, u: (px - this.ox) / this.cell - x, v: (py - this.oy) / this.cell - y };
  }

  // ------------------------------------------------------------- drawing --

  draw() {
    const size = this._canvasSize();
    const width = size.width;
    const height = size.height;
    if (!width || !height) return; // an inactive tab has no drawable rectangle
    const ratio = clamp(window.devicePixelRatio || 1, 1, 3);
    if (this.canvas.width !== Math.round(width * ratio) ||
        this.canvas.height !== Math.round(height * ratio)) {
      this.canvas.width = Math.round(width * ratio);
      this.canvas.height = Math.round(height * ratio);
    }
    const ctx = this.ctx;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#12151c";
    ctx.fillRect(0, 0, width, height);
    if (!this.state) return;

    const cell = this._cellSize(width, height);
    this.metrics = { width, height, cell };
    this.cell = cell;
    this.ox = width / 2 - this.camera.x * cell;
    this.oy = height / 2 - this.camera.y * cell;
    const px = (x) => this.ox + x * cell;
    const py = (y) => this.oy + y * cell;
    const pad = Math.max(1, cell * 0.045);
    const visible = this._visibleBounds(width, height, cell);
    const filled = new Set((this.state.tiles || []).map((tile) => tile[0] + "," + tile[1]));

    // A stable, quiet grid says that the land is unbounded without repeatedly
    // zooming the camera out as the board grows.
    ctx.strokeStyle = "rgba(100, 113, 139, .25)";
    ctx.lineWidth = Math.max(1 / ratio, cell * 0.018);
    for (let x = visible.minX; x <= visible.maxX; x += 1) {
      for (let y = visible.minY; y <= visible.maxY; y += 1) {
        if (filled.has(x + "," + y)) continue;
        ctx.strokeRect(px(x) + pad, py(y) + pad, cell - pad * 2, cell - pad * 2);
      }
    }

    // The laid tiles receive a small bevel and shadow. All dimensions are a
    // ratio of one cell, so high-DPI and zoomed displays stay crisp.
    for (const tile of this.state.tiles || []) {
      const x0 = px(tile[0]) + pad;
      const y0 = py(tile[1]) + pad;
      const sizePx = cell - pad * 2;
      const gradient = ctx.createLinearGradient(x0, y0, x0, y0 + sizePx);
      if (tile[2]) {
        gradient.addColorStop(0, "#fff9e9");
        gradient.addColorStop(1, LIGHT_TILE);
      } else {
        gradient.addColorStop(0, "#aa8359");
        gradient.addColorStop(1, DARK_TILE);
      }
      ctx.save();
      ctx.shadowColor = "rgba(0, 0, 0, .32)";
      ctx.shadowBlur = Math.max(2, cell * 0.08);
      ctx.shadowOffsetY = Math.max(1, cell * 0.035);
      ctx.fillStyle = gradient;
      roundRect(ctx, x0, y0, sizePx, sizePx, Math.max(2, cell * 0.08));
      ctx.fill();
      ctx.restore();
      ctx.strokeStyle = tile[2] ? "rgba(80, 67, 48, .40)" : "rgba(255, 243, 218, .20)";
      ctx.lineWidth = Math.max(1 / ratio, cell * 0.025);
      roundRect(ctx, x0, y0, sizePx, sizePx, Math.max(2, cell * 0.08));
      ctx.stroke();
    }

    this._drawAreas(ctx, px, py, cell, pad, ratio);
    this._drawLegal(ctx, px, py, cell, pad, ratio);
    this._drawPawns(ctx, px, py, cell, ratio);
    this._drawFinal(ctx, width, height, cell);
  }

  _visibleBounds(width, height, cell) {
    return {
      minX: Math.floor((-this.ox) / cell) - 1,
      maxX: Math.ceil((width - this.ox) / cell) + 1,
      minY: Math.floor((-this.oy) / cell) - 1,
      maxY: Math.ceil((height - this.oy) / cell) + 1,
    };
  }

  _drawAreas(ctx, px, py, cell, pad, ratio) {
    for (const area of this.state.areas || []) {
      if (area.size < 2) continue;
      const cells = new Set(area.cells.map((entry) => entry[0] + "," + entry[1]));
      ctx.save();
      ctx.strokeStyle = area.owner === null || area.owner === undefined
        ? "rgba(240, 180, 41, .30)"
        : withAlpha(TRIBE_COLOURS[area.owner] || "#f0b429", .92);
      if (area.taxed) ctx.setLineDash([Math.max(4, cell * .14), Math.max(3, cell * .10)]);
      ctx.lineWidth = Math.max(1.4 / ratio, cell * .052);
      for (const [x, y] of area.cells) {
        const x0 = px(x) + pad;
        const y0 = py(y) + pad;
        const side = cell - pad * 2;
        const has = (dx, dy) => cells.has((x + dx) + "," + (y + dy));
        ctx.beginPath();
        if (!has(0, -1)) { ctx.moveTo(x0, y0); ctx.lineTo(x0 + side, y0); }
        if (!has(1, 0)) { ctx.moveTo(x0 + side, y0); ctx.lineTo(x0 + side, y0 + side); }
        if (!has(0, 1)) { ctx.moveTo(x0 + side, y0 + side); ctx.lineTo(x0, y0 + side); }
        if (!has(-1, 0)) { ctx.moveTo(x0, y0 + side); ctx.lineTo(x0, y0); }
        ctx.stroke();
      }
      ctx.restore();

      if (cell < 29) continue;
      let sumX = 0; let sumY = 0;
      for (const entry of area.cells) { sumX += entry[0]; sumY += entry[1]; }
      const centreX = sumX / area.cells.length;
      const centreY = sumY / area.cells.length;
      let labelCell = area.cells[0];
      let distance = Infinity;
      for (const entry of area.cells) {
        const d = (entry[0] - centreX) ** 2 + (entry[1] - centreY) ** 2;
        if (d < distance) { distance = d; labelCell = entry; }
      }
      const owned = area.owner !== null && area.owner !== undefined;
      const label = owned ? area.size + " × " + area.rate : String(area.size);
      const labelW = Math.max(21, cell * .72);
      const labelH = Math.max(12, cell * .28);
      const x0 = px(labelCell[0]) + cell / 2 - labelW / 2;
      const y0 = py(labelCell[1]) + cell - labelH - Math.max(1.5, cell * .075);
      ctx.fillStyle = "rgba(10, 12, 16, .80)";
      roundRect(ctx, x0, y0, labelW, labelH, Math.min(4, labelH / 3));
      ctx.fill();
      ctx.fillStyle = owned ? (TRIBE_COLOURS[area.owner] || "#f0b429") : "#d3d9e6";
      ctx.font = "700 " + Math.max(8, Math.round(cell * .20)) + "px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, x0 + labelW / 2, y0 + labelH / 2 + .5);
    }
  }

  _drawLegal(ctx, px, py, cell, pad, ratio) {
    if (!this._humanTurn() || this.state.finished) return;
    for (const tile of this.legal.tiles || []) {
      const x0 = px(tile.x) + pad;
      const y0 = py(tile.y) + pad;
      const side = cell - pad * 2;
      ctx.save();
      ctx.globalAlpha = .42;
      ctx.fillStyle = tile.colour ? LIGHT_TILE : DARK_TILE;
      roundRect(ctx, x0, y0, side, side, Math.max(2, cell * .08));
      ctx.fill();
      ctx.setLineDash([Math.max(3, cell * .12), Math.max(3, cell * .09)]);
      ctx.strokeStyle = "#f0b429";
      ctx.lineWidth = Math.max(1.1 / ratio, cell * .036);
      ctx.strokeRect(x0, y0, side, side);
      ctx.restore();
    }
    for (const action of this.legal.pawns || []) {
      const colour = action.kind === "attack" ? "#f26b61"
        : action.kind === "settle" ? "#4cc2ff" : "#7ee081";
      ctx.save();
      ctx.setLineDash([Math.max(2, cell * .09), Math.max(2, cell * .07)]);
      ctx.strokeStyle = colour;
      ctx.lineWidth = Math.max(1.1 / ratio, cell * .038);
      ctx.beginPath();
      ctx.arc(px(action.x) + cell / 2, py(action.y) + cell / 2, cell * .235, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
    if (this.hover && (this.legal.tiles || []).some((tile) => tile.x === this.hover.x && tile.y === this.hover.y)) {
      ctx.strokeStyle = "rgba(255, 255, 255, .85)";
      ctx.lineWidth = Math.max(1 / ratio, cell * .025);
      ctx.strokeRect(px(this.hover.x) + pad * .5, py(this.hover.y) + pad * .5,
        cell - pad, cell - pad);
    }
  }

  _drawPawns(ctx, px, py, cell, ratio) {
    for (const pawn of this.state.pawns || []) {
      const [x, y, owner] = pawn;
      const cx = px(x) + cell / 2;
      const cy = py(y) + cell / 2;
      const radius = cell * .285;
      const colour = TRIBE_COLOURS[owner] || "#f0b429";
      const grad = ctx.createRadialGradient(cx - radius * .32, cy - radius * .36,
        radius * .08, cx, cy, radius);
      grad.addColorStop(0, "#ffffff");
      grad.addColorStop(.16, colour);
      grad.addColorStop(1, shade(colour, .68));
      ctx.save();
      ctx.shadowColor = "rgba(0, 0, 0, .48)";
      ctx.shadowBlur = Math.max(2, cell * .10);
      ctx.shadowOffsetY = Math.max(1, cell * .045);
      ctx.beginPath();
      ctx.arc(cx, cy, radius + Math.max(1, cell * .034), 0, Math.PI * 2);
      ctx.fillStyle = "rgba(9, 11, 15, .80)";
      ctx.fill();
      ctx.restore();
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.lineWidth = Math.max(1 / ratio, cell * .024);
      ctx.strokeStyle = "rgba(0, 0, 0, .62)";
      ctx.stroke();
      if (cell >= 36) {
        ctx.fillStyle = owner === 0 ? "#282521" : "#f5f0e7";
        ctx.font = "800 " + Math.round(cell * .24) + "px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText((this.state.names[owner] || "?")[0].toUpperCase(), cx, cy + .5);
      }
      if (this.source && this.source[0] === x && this.source[1] === y) {
        ctx.beginPath();
        ctx.arc(cx, cy, radius * 1.55, 0, Math.PI * 2);
        ctx.strokeStyle = "#f0b429";
        ctx.lineWidth = Math.max(1.5 / ratio, cell * .052);
        ctx.stroke();
      }
    }
  }

  _drawFinal(ctx, width, height, cell) {
    if (!this.state.finished || !this.state.final) return;
    const solo = !!(this.state.rules && this.state.rules.solo);
    const summary = solo
      ? "SOLO complete — " + this.state.solo_score + " of " + this.state.target + " points"
      : "Final scores — " + this.state.names.map((name, index) =>
        name + " " + this.state.final[index]).join("   ");
    const heightPx = Math.max(58, Math.min(82, cell * 1.2));
    ctx.fillStyle = "rgba(10, 12, 16, .84)";
    ctx.fillRect(0, height / 2 - heightPx / 2, width, heightPx);
    ctx.fillStyle = "#f2ede1";
    ctx.font = "700 " + Math.max(14, Math.min(20, cell * .32)) + "px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(summary, width / 2, height / 2 + 1);
  }

  // --------------------------------------------------------------- panel --

  _panel() {
    const state = this.state;
    if (!state) return;
    if (this.el.status) this.el.status.textContent = state.status || "";
    const solo = !!(state.rules && state.rules.solo);
    const canPass = !!(this.legal && this.legal.can_pass);
    this.el.pass.disabled = !!state.finished || !canPass || !this.phase();
    this.el.pass.textContent = solo && canPass ? "Pass (no pawn action)" : "Skip pawn action";
    if (this.el.hint) {
      this.el.hint.textContent = state.finished
        ? (solo ? "SOLO: " + state.solo_score + " of " + state.target + " points" : "Game complete")
        : this._humanTurn()
          ? (this.phase()
              ? (solo ? "Pawn action — required when possible" :
                state.chain ? "Continue the compulsory jump" : "Pawn action — optional")
              : "Lay a " + (state.drawn ? "light" : "dark") + " tile")
          : (state.names[state.current] || "Opponent") + " is thinking…";
    }
    if (!this.el.list) return;
    const rows = (state.names || []).map((name, index) => {
      const onLand = (state.pawns || []).filter((pawn) => pawn[2] === index).length;
      const score = state.final ? state.final[index] : (state.scores || [])[index];
      return '<div class="tribe' + (index === state.current && !state.finished ? " turn" : "") + '">' +
        '<i class="dot" style="background:' + TRIBE_COLOURS[index] + '"></i>' +
        '<span class="who">' + escapeText(name) + "</span>" +
        '<span class="pts">' + (score === undefined ? 0 : score) + "</span>" +
        '<span class="res">' + onLand + " placed · " + (state.reserve || [])[index] + " free</span>" +
        "</div>";
    });
    const target = solo && state.target ? " · target " + state.target : "";
    this.el.list.innerHTML = rows.join("") +
      '<p class="dim small">Supply: ' + state.supply.light + " light, " +
      state.supply.dark + " dark tiles · " + state.left + " left" + target + "</p>";
  }
}

// ---------------------------------------------------------------- helpers --

function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}

function withAlpha(hex, alpha) {
  const number = parseInt(hex.slice(1), 16);
  return "rgba(" + ((number >> 16) & 255) + "," + ((number >> 8) & 255) + "," +
    (number & 255) + "," + alpha + ")";
}

function shade(hex, factor) {
  const number = parseInt(hex.slice(1), 16);
  const r = Math.round(((number >> 16) & 255) * factor);
  const g = Math.round(((number >> 8) & 255) * factor);
  const b = Math.round((number & 255) * factor);
  return "rgb(" + r + "," + g + "," + b + ")";
}

function escapeText(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function escapeAttr(text) { return escapeText(text).replace(/"/g, "&quot;"); }

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
