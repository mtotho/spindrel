/* Spindrel service worker.
 *
 * Responsibilities:
 *   1. Install / activate lifecycle — take control fast, clean old caches.
 *   2. Web Push — receive `push` events, render a system notification.
 *   3. Notification clicks — focus an existing window or open a target URL.
 *   4. Minimal runtime cache for static /assets/* (network-first falls back
 *      to cache on flaky mobile connections).
 *
 * Deliberately NOT doing:
 *   - Precaching the build manifest (hashed assets + nginx long-cache
 *     already make this a wash, and precaching fights our existing
 *     Cache-Control: immutable headers).
 *   - Offline mode for API calls. Auth + live SSE preclude useful offline
 *     behavior; we fail fast to surface the connection issue.
 */
const CACHE_NAME = "spindrel-assets-v1";
const ASSET_ORIGIN_MATCHER = /\/assets\//;

self.addEventListener("install", (event) => {
  // Activate as soon as install finishes, so first load gets push support.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Drop any stale caches from earlier SW versions.
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

// Minimal fetch strategy: cache-first for /assets/* with background revalidate;
// pass-through for everything else. Keeps the SW lightweight and avoids
// shadowing API behavior.
self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!ASSET_ORIGIN_MATCHER.test(url.pathname)) return;
  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(request);
      const networkPromise = fetch(request)
        .then((resp) => {
          if (resp && resp.ok) cache.put(request, resp.clone());
          return resp;
        })
        .catch(() => null);
      return cached || (await networkPromise) || fetch(request);
    })(),
  );
});

// --- Web Push -------------------------------------------------------------

self.addEventListener("push", (event) => {
  // Accept JSON payloads shaped as:
  //   { title, body, url?, tag?, icon?, badge?, data? }
  let payload = {};
  if (event.data) {
    try { payload = event.data.json(); }
    catch { payload = { title: "Spindrel", body: event.data.text() }; }
  }
  const title = payload.title || "Spindrel";
  const options = {
    body: payload.body || "",
    icon: payload.icon || "/assets/images/icon-192.png",
    badge: payload.badge || "/assets/images/icon-192.png",
    tag: payload.tag,                    // collapses repeat notifications
    renotify: !!payload.tag,
    data: { url: payload.url || "/", ...(payload.data || {}) },
    timestamp: Date.now(),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      // Prefer focusing an already-open Spindrel window. If one exists,
      // navigate it to the target URL — this is what users expect when
      // they tap a notification from the app they already had open.
      for (const client of all) {
        const sameOrigin = new URL(client.url).origin === self.location.origin;
        if (sameOrigin) {
          await client.focus();
          if ("navigate" in client) {
            try { await client.navigate(target); } catch { /* cross-origin or frozen */ }
          }
          return;
        }
      }
      await self.clients.openWindow(target);
    })(),
  );
});

// Optional: allow the page to trigger SW updates manually.
self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});
