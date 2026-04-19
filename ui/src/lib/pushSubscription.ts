/* Web Push subscription management.
 *
 * Flow:
 *   1. Check browser support (`Notification`, `PushManager`, SW registered).
 *   2. Fetch the server's VAPID public key.
 *   3. Prompt for Notification permission.
 *   4. Ask the SW's PushManager to subscribe with that key.
 *   5. POST the subscription JSON to /api/v1/push/subscribe.
 *
 * iOS gotcha: Notification/Push APIs only exist inside an installed PWA
 * (display-mode: standalone) on iOS 16.4+. In Safari tabs they are
 * permanently absent. `isPushSupported` accounts for that. */
import { apiFetch } from "../api/client";

function isStandaloneOniOS(): boolean {
  // iOS Safari in standalone mode exposes `navigator.standalone`; the
  // display-mode media query catches everyone else (desktop, Android).
  const nav = navigator as Navigator & { standalone?: boolean };
  return nav.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
}

function isIOS(): boolean {
  // Legacy UA sniff — iOS doesn't expose a cleaner signal.
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
}

export function isPushSupported(): boolean {
  if (typeof window === "undefined") return false;
  if (!("serviceWorker" in navigator)) return false;
  if (!("PushManager" in window)) return false;
  if (!("Notification" in window)) return false;
  // iOS requires the PWA to be installed. We could offer push-setup UI
  // in a browser tab but the subscribe() call would throw. Better to
  // gate the UI up front and tell the user to install first.
  if (isIOS() && !isStandaloneOniOS()) return false;
  return true;
}

export function notificationPermission(): NotificationPermission {
  return typeof Notification !== "undefined" ? Notification.permission : "denied";
}

/** URL-safe base64 → Uint8Array (backed by a fresh ArrayBuffer — the DOM
 *  typings for `BufferSource` in some lib.dom.d.ts versions reject
 *  Uint8Array instances whose backing buffer could be SharedArrayBuffer,
 *  even though it isn't). PushManager.subscribe wants raw bytes. */
function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const buf = new ArrayBuffer(raw.length);
  const out = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function getRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  // `ready` resolves once the SW from /sw.js is activated.
  return await navigator.serviceWorker.ready;
}

export async function getExistingSubscription(): Promise<PushSubscription | null> {
  const reg = await getRegistration();
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

/** Request permission + subscribe + POST to backend. Idempotent — if a
 *  subscription already exists for this device, it's re-posted so the
 *  backend upserts on endpoint. */
export async function enablePush(): Promise<
  | { ok: true }
  | { ok: false; reason: "unsupported" | "denied" | "server-disabled" | "error"; message?: string }
> {
  if (!isPushSupported()) return { ok: false, reason: "unsupported" };
  const reg = await getRegistration();
  if (!reg) return { ok: false, reason: "unsupported" };

  if (Notification.permission !== "granted") {
    const p = await Notification.requestPermission();
    if (p !== "granted") return { ok: false, reason: "denied" };
  }

  // Fetch VAPID public key from the backend.
  let publicKey: string;
  try {
    const r = await apiFetch<{ publicKey: string }>("/api/v1/push/vapid-public-key");
    publicKey = r.publicKey;
  } catch (err) {
    return { ok: false, reason: "server-disabled", message: String(err) };
  }

  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    try {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
      });
    } catch (err) {
      return { ok: false, reason: "error", message: String(err) };
    }
  }

  // POST to backend. We send the JSON shape the PushManager hands us,
  // plus a UA string for debugging on the admin side.
  const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } };
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    return { ok: false, reason: "error", message: "Incomplete subscription payload" };
  }
  try {
    await apiFetch("/api/v1/push/subscribe", {
      method: "POST",
      body: JSON.stringify({
        endpoint: json.endpoint,
        keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
        userAgent: navigator.userAgent,
      }),
    });
  } catch (err) {
    return { ok: false, reason: "error", message: String(err) };
  }
  return { ok: true };
}

export async function disablePush(): Promise<void> {
  const sub = await getExistingSubscription();
  if (!sub) return;
  try {
    await apiFetch("/api/v1/push/unsubscribe", {
      method: "POST",
      body: JSON.stringify({ endpoint: sub.endpoint }),
    });
  } catch {
    // Best-effort backend cleanup; local unsubscribe proceeds regardless
    // so the device stops receiving.
  }
  try { await sub.unsubscribe(); } catch { /* ignore */ }
}
