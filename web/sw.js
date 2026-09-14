/*
 * TALOS - browser edition: the service worker.
 *
 * The point of this file is the promise on the tin: after the very first visit
 * the whole studio - Python runtime, engine, rules, puzzles you have opened -
 * is on the device.  Airplane mode, no network, still plays.
 *
 * Cache first, network as a fallback, and everything the page touches gets
 * remembered for next time (except the 2 MB puzzle file, which is cached the
 * first time you actually open a training set).
 */

const VERSION = "talos-2.1.1";          // bump with every release
const SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./css/style.css",
  "./js/app.js",
  "./js/board.js",
  "./js/engine.js",
  "./js/play.js",
  "./js/train.js",
  "./js/anarchess.js",
  "./js/worker.js",
  "./data/sets.json",
  "./icons/favicon.ico",
  "./icons/talos.svg",
  "./icons/talos-192.png",
  "./icons/talos-512.png",
  "./icons/talos-maskable-512.png",
  "./icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    await cache.addAll(SHELL);
    // the Python core: small (about 1 MB) and needed before anything works
    try {
      const res = await fetch("python/files.json");
      const files = await res.json();
      await cache.add("python/files.json");
      await cache.addAll(files.map((rel) => "python/" + rel));
    } catch (err) {
      /* not fatal - the runtime caches them on demand */
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n !== VERSION).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin && url.hostname !== "cdn.jsdelivr.net") return;

  event.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const hit = await cache.match(request, { ignoreSearch: false });
    if (hit) {
      // refresh in the background so a new release does not need two visits
      fetch(request).then((res) => {
        if (res && res.ok) cache.put(request, res.clone());
      }).catch(() => {});
      return hit;
    }
    try {
      const res = await fetch(request);
      if (res && res.ok && (res.type === "basic" || res.type === "cors")) {
        cache.put(request, res.clone());
      }
      return res;
    } catch (err) {
      if (request.mode === "navigate") {
        const fallback = await cache.match("./index.html");
        if (fallback) return fallback;
      }
      throw err;
    }
  })());
});
