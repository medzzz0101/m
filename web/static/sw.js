/* ==========================================================================
   sw.js — the service worker. Makes the app installable + makes the STATIC
   SHELL load offline (a PWA requirement from the brief).

   Strategy:
     * On install: pre-cache the app shell (html/css/js/manifest/icons).
     * Fetch handler:
         - navigation/static assets -> "cache-first, then network" so the UI
           opens instantly and works with no connection.
         - /api/* and external OSINT calls -> always go to the network (live
           data must never be served stale from cache).
   Bump CACHE_VERSION whenever shell assets change to invalidate old caches.
   ========================================================================== */

// Bump this whenever shell assets change — it invalidates old caches so phones
// pick up the new UI instead of a stale one.
const CACHE_VERSION = "osint-shell-v9";
const SHELL = [
  "/",
  "/static/css/tokens.css",
  "/static/css/layout.css",
  "/static/css/components.css",
  "/static/js/util.js",
  "/static/js/graph.js",
  "/static/js/app.js",
  "/static/vendor/leaflet/leaflet.css",
  "/static/vendor/leaflet/leaflet.js",
  "/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  // Pre-cache the shell, then activate immediately.
  event.waitUntil(
    caches.open(CACHE_VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  // Drop old shell caches.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never touch API or cross-origin data calls — always live, no caching.
  if (url.pathname.startsWith("/api/") || url.origin !== self.location.origin) {
    return; // default network behaviour
  }

  // NETWORK-FIRST for the shell. When online we always render the freshest UI
  // (this avoids the "stale/half-styled cached page" trap that a cache-first
  // worker can fall into if it ever caches a bad response). The cache is only a
  // fallback for offline. We also refuse to cache anything that isn't a clean
  // 200 same-type response, so a proxy interstitial can never poison the cache.
  event.respondWith(
    fetch(event.request).then((resp) => {
      if (resp.ok && resp.type === "basic" && event.request.method === "GET") {
        const copy = resp.clone();
        caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
      }
      return resp;
    }).catch(() => caches.match(event.request))
  );
});
