/* Service-worker registration + update-available signal.
 *
 * Keeps the registration side-effects off the critical render path (idle-
 * callback so first paint isn't blocked) and exposes a single
 * `onUpdateAvailable` hook the app can use to offer a "reload to update"
 * toast. The SW itself lives at /sw.js (hand-rolled — see comments there). */

export interface RegisterSWOptions {
  /** Fired when a new SW has been installed and is waiting to activate.
   *  The app should show a "Reload to update" prompt; when the user
   *  accepts, call `applyUpdate()` — the SW will take over and the page
   *  reloads on the next `controllerchange` tick. */
  onUpdateAvailable?: (applyUpdate: () => void) => void;
}

export function registerServiceWorker(options: RegisterSWOptions = {}) {
  if (typeof window === "undefined") return;
  if (!("serviceWorker" in navigator)) return;
  // Dev: no SW. Vite dev server + SW is a debugging minefield (stale
  // bundles, cached HMR payloads). Register only in production builds.
  if (import.meta.env.DEV) return;

  const schedule =
    (window as Window & { requestIdleCallback?: (cb: () => void) => void }).requestIdleCallback
    ?? ((cb: () => void) => window.setTimeout(cb, 1));

  schedule(async () => {
    try {
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });

      const notifyIfWaiting = () => {
        if (!reg.waiting) return;
        options.onUpdateAvailable?.(() => {
          reg.waiting?.postMessage("skip-waiting");
        });
      };

      reg.addEventListener("updatefound", () => {
        const incoming = reg.installing;
        if (!incoming) return;
        incoming.addEventListener("statechange", () => {
          if (incoming.state === "installed" && navigator.serviceWorker.controller) {
            notifyIfWaiting();
          }
        });
      });

      // Existing waiting worker (previous session left one queued)
      notifyIfWaiting();

      // When the new SW takes control, reload once so the fresh bundle runs.
      let reloading = false;
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (reloading) return;
        reloading = true;
        window.location.reload();
      });
    } catch (err) {
      console.warn("[sw] registration failed", err);
    }
  });
}
