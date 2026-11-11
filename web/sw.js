/* Huxley's phone app helper. It only does one thing: when the laptop can't be
   reached, show Huxley's own "offline" screen instead of Chrome's error page.
   Nothing else is cached, so the HUD is always the laptop's latest version. */
const CACHE = "huxley-offline-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/offline", "/static/icons/huxley-192.png"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match("/offline")));
});
