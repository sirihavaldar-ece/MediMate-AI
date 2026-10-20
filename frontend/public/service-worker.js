// MediMate intentionally keeps no runtime cache. In particular, API responses,
// sessions, medication history, and confirmations are never stored offline.
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
