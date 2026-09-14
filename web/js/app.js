/*
 * TALOS — browser edition application shell.
 *
 * Python runs in js/worker.js. This file restores settings, owns navigation,
 * and wires the chess, training, Anarchess, SOLO and Anarcheckers views.
 */

import { Engine } from "./engine.js";
import { PlayView } from "./play.js";
import { TrainView } from "./train.js";
import { AnarchessView } from "./anarchess.js";
import { escapeHtml } from "./play.js";

const SETTINGS_KEY = "talos.settings";

const DEFAULTS = {
  level: "Club",
  side: "w",
  variant: "standard",
  think: "balanced",
  flip: false,
  rules: null,           // filled from the curated Anarchchess preset on boot
  anarchessPlayers: 2,
  anarchessLevel: 2,
  anarchessTiles: 32,
  soloTiles: 32,
  anarcheckersPlayers: 2,
  anarcheckersLevel: 2,
  anarcheckersTiles: 32,
};

class App {
  constructor() {
    const saved = loadSettings();
    this.settings = migrateSettings(Object.assign({}, DEFAULTS, saved), saved);
    this.engine = new Engine();
    this.views = {};
    this.active = "play";
    this.deferredInstall = null;
  }

  set(key, value) {
    this.settings[key] = value;
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings));
    } catch (_err) {
      /* private mode: the app still works, it just forgets */
    }
  }

  loader(text, sub) {
    const box = document.getElementById("loader");
    const line = document.getElementById("loader-text");
    if (text) line.textContent = text;
    if (sub !== undefined) document.getElementById("loader-sub").textContent = sub;
    if (box) box.classList.toggle("hidden", !text);
  }

  async boot() {
    this._tabs();
    this.engine.onstate = (engine) => {
      const pct = Math.round((engine.progress || 0) * 100);
      this.loader(engine.detail + (pct ? " — " + pct + "%" : ""),
        "About 10 MB of Python, cached after the first visit.");
    };
    this.engine.onerror = (err) => {
      this.loader("The engine could not start",
        err.message + " — reload, or check your connection on the first visit.");
      const state = document.getElementById("engine-state");
      if (state) state.textContent = "engine failed";
    };

    try {
      this.info = await this.engine.ready();
    } catch (_err) {
      return;                                     // onerror already explained
    }

    this.views.play = new PlayView(this);
    this.views.train = new TrainView(this);
    this.views.anarchess = new AnarchessView(this, "anarchess");
    this.views.solo = new AnarchessView(this, "solo");
    this.views.anarcheckers = new AnarchessView(this, "anarcheckers");

    await this.views.play.start();
    await Promise.all([
      this.views.anarchess.start(),
      this.views.solo.start(),
      this.views.anarcheckers.start(),
    ]);
    await this._rules();

    const info = this.info;
    document.getElementById("version-line").textContent =
      "TALOS " + info.version + " · Python " + info.python + " · python-chess " +
      info.chess + " · " + info.levels + " chess-engine levels · " + info.rules +
      " Anarchchess rules";
    document.getElementById("engine-state").textContent =
      "Python " + info.python + " · engine ready";

    this.loader(null);
    this._serviceWorker();
    this._install();
  }

  // -------------------------------------------------------------- chrome --

  _tabs() {
    const tabs = Array.from(document.querySelectorAll(".tab[data-view]"));
    for (const tab of tabs) {
      tab.addEventListener("click", () => this.show(tab.dataset.view));
    }
  }

  async show(name) {
    if (!name) return;
    this.active = name;
    for (const tab of document.querySelectorAll(".tab[data-view]")) {
      const active = tab.dataset.view === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    }
    for (const view of document.querySelectorAll(".view")) {
      view.classList.toggle("active", view.id === "view-" + name);
    }
    if (name === "train" && this.views.train) await this.views.train.activate();
    if (["anarchess", "solo", "anarcheckers"].includes(name) && this.views[name]) {
      await this.views[name].activate();
    }
  }

  async _rules() {
    const data = await this.engine.json("anarch_rules");
    this.ruleBook = data.rules;
    this.presets = data.presets;
    if (!this.settings.rules) {
      this.settings.rules = Object.assign({}, this.presets.anarchchess);
    }
    const list = document.getElementById("rule-list");
    list.innerHTML = this.ruleBook.map((rule) =>
      '<label class="rule"><input type="checkbox" data-key="' + rule.key + '">' +
      "<b>" + escapeHtml(rule.title) + "</b><span>" + escapeHtml(rule.tip) +
      "</span></label>").join("");
    list.addEventListener("change", (event) => {
      const key = event.target.dataset.key;
      if (!key) return;
      this.settings.rules[key] = event.target.checked;
      this.set("rules", this.settings.rules);
      if (this.views.play) this.views.play.refresh();
    });
    this.syncRules();

    const applyPreset = (values) => {
      this.settings.rules = Object.assign(allOff(this.ruleBook), values || {});
      this.set("rules", this.settings.rules);
      this.syncRules();
      if (this.views.play) this.views.play.refresh();
    };
    document.getElementById("preset-curated").addEventListener(
      "click", () => applyPreset(this.presets.anarchchess));
    document.getElementById("preset-anarchy").addEventListener(
      "click", () => applyPreset(this.presets.anarchy));
    document.getElementById("preset-off").addEventListener("click", () => applyPreset({}));
    for (const button of document.querySelectorAll("[data-open-land]")) {
      button.addEventListener("click", () => this.show(button.dataset.openLand));
    }
  }

  syncRules() {
    for (const box of document.querySelectorAll("#rule-list input[data-key]")) {
      box.checked = !!this.settings.rules[box.dataset.key];
    }
  }

  _serviceWorker() {
    if (!("serviceWorker" in navigator)) return;
    if (location.protocol !== "https:" && location.hostname !== "localhost") return;
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("sw.js").catch(() => { /* older browser */ });
    });
  }

  _install() {
    const button = document.createElement("button");
    button.className = "tab install";
    button.id = "btn-install";
    button.textContent = "Install";
    button.style.display = "none";
    document.querySelector(".tabs").appendChild(button);
    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      this.deferredInstall = event;
      button.style.display = "";
    });
    button.addEventListener("click", async () => {
      if (!this.deferredInstall) {
        button.textContent = "Add to Home Screen";
        return;
      }
      this.deferredInstall.prompt();
      this.deferredInstall = null;
      button.style.display = "none";
    });
    window.addEventListener("appinstalled", () => { button.style.display = "none"; });
  }
}

// -------------------------------------------------------------- helpers --

function allOff(rules) {
  const off = {};
  for (const rule of rules || []) off[rule.key] = false;
  return off;
}

function migrateSettings(settings, saved) {
  // v2.1 stored all land modes behind one ``anMode`` selector. Preserve its
  // useful choices while giving every dedicated game independent controls.
  const legacy = saved || {};
  const defaults = {
    anarchessPlayers: legacy.anPlayers,
    anarchessLevel: legacy.anLevel,
    anarchessTiles: legacy.anTiles,
    soloTiles: legacy.anTiles,
    anarcheckersPlayers: legacy.anPlayers,
    anarcheckersLevel: legacy.anLevel,
    anarcheckersTiles: legacy.anTiles,
  };
  for (const [key, value] of Object.entries(defaults)) {
    if (!Object.prototype.hasOwnProperty.call(legacy, key) && value !== undefined) {
      settings[key] = value;
    }
  }
  return settings;
}

function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") || {};
  } catch (_err) {
    return {};
  }
}

const app = new App();
window.talos = app;
app.boot();
