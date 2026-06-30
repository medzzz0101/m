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

const CACHE_VERSION = "osint-shell-v1";
const SHELL = [
  "/",
  "/static/css/tokens.css",
  "/static/css/layout.css",
  "/static/css/components.css",
  "/static/js/util.js",
  "/static/js/graph.js",
  "/static/js/app.js",
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

  // Never cache API or cross-origin data calls — always live.
  if (url.pathname.startsWith("/api/") || url.origin !== self.location.origin) {
    return; // default network behaviour
  }

  // Shell + static assets: cache-first, fall back to network, then update cache.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request).then((resp) => {
        // Stash a copy of successful GETs for next time (offline shell).
        if (resp.ok && event.request.method === "GET") {
          const copy = resp.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
        }
        return resp;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
