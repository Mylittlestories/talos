/*
 * TALOS - browser edition: promise wrapper around the Pyodide worker.
 */

const DEFAULT_TIMEOUT = 180000; // a slow phone running a deep search

export class Engine {
  constructor() {
    this.worker = new Worker(new URL("./worker.js", import.meta.url));
    this.pending = new Map();
    this.seq = 0;
    this.state = "booting";
    this.detail = "";
    this.progress = 0;
    this.onerror = null;
    this.onstate = null;
    this._ready = null;
    this._info = null;

    this.worker.onmessage = (event) => this._message(event.data || {});
    this.worker.onerror = (event) => {
      const text = event.message || "the worker died";
      this._fail(new Error(text));
    };
  }

  _message(msg) {
    if (msg.type === "progress") {
      this.state = "loading";
      this.detail = msg.text;
      this.progress = msg.pct || 0;
      if (this.onstate) this.onstate(this);
      return;
    }
    if (msg.type === "fatal") {
      this._fail(new Error(msg.error));
      return;
    }
    if (msg.type !== "result") return;
    const slot = this.pending.get(msg.id);
    if (!slot) return;
    this.pending.delete(msg.id);
    clearTimeout(slot.timer);
    if (msg.ok) slot.resolve(msg.value);
    else slot.reject(new Error(msg.error || "the engine call failed"));
  }

  _fail(err) {
    this.state = "error";
    this.detail = err.message;
    if (this.onerror) this.onerror(err);
    for (const slot of this.pending.values()) {
      clearTimeout(slot.timer);
      slot.reject(err);
    }
    this.pending.clear();
  }

  /** Resolves with {version} once Python is up. Safe to call repeatedly. */
  ready() {
    if (this._ready) return this._ready;
    this._ready = this.call("about", [], DEFAULT_TIMEOUT).then((raw) => {
      const info = JSON.parse(raw);
      this.state = "ready";
      this.detail = "";
      this.progress = 1;
      this._info = info;
      if (this.onstate) this.onstate(this);
      return info;
    });
    return this._ready;
  }

  /**
   * Call a bridge function. Complex arguments must be passed as JSON strings;
   * the bridge parses them itself.
   */
  call(fn, args, timeout) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(fn + " timed out"));
      }, timeout || DEFAULT_TIMEOUT);
      this.pending.set(id, { resolve, reject, timer });
      this.worker.postMessage({ type: "call", id, fn, args: args || [] });
    });
  }

  /** Call a bridge function and parse its JSON answer. */
  async json(fn, args, timeout) {
    return JSON.parse(await this.call(fn, args, timeout));
  }

  terminate() {
    this.worker.terminate();
  }
}
