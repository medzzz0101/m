/* sw.js — a minimal, safe service worker for the PWA.
   Strategy: network-first for everything, falling back to cache when offline so
   the shell still opens. API calls are never cached (always live). */
const CACHE = "lattice-v5";
const SHELL = [
  "/", "/static/css/tokens.css", "/static/css/layout.css",
  "/static/css/components.css", "/static/js/app.js", "/static/js/graph.js",
  "/static/vendor/leaflet/leaflet.css", "/static/vendor/leaflet/leaflet.js",
  "/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/") || e.request.method !== "GET") return; // always live
  e.respondWith(
    fetch(e.request).then((res) => {
      const clone = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, clone)).catch(() => {});
      return res;
    }).catch(() => caches.match(e.request))
  );
});
