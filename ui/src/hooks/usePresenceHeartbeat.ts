/* Ping /api/v1/presence/heartbeat while the app tab is visible.
 *
 * The backend's push service uses the last-seen timestamp to decide
 * whether to skip a notification when `only_if_inactive=true`. Interval
 * must be comfortably under `INACTIVE_AFTER_SECONDS` on the server
 * (120s). 60s is a good middle ground — one skipped ping (e.g. laptop
 * sleep) still keeps the user "active" for a little longer, and the
 * request rate is negligible. */
import { useEffect } from "react";
import { apiFetch } from "../api/client";
import { useAuthStore } from "../stores/auth";

const INTERVAL_MS = 60_000;

export function usePresenceHeartbeat() {
  const isAuthed = useAuthStore((s) => !!s.accessToken);

  useEffect(() => {
    if (!isAuthed) return;
    if (typeof document === "undefined") return;

    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const ping = () => {
      if (cancelled || document.visibilityState !== "visible") return;
      void apiFetch("/api/v1/presence/heartbeat", { method: "POST" }).catch(() => {
        // Presence is best-effort; a failed ping falls off silently. The
        // backend side treats absence as inactive, which is safe.
      });
    };

    // Fire once on mount, then on an interval, plus whenever visibility
    // flips back to visible (wake from tab switch / screen unlock).
    ping();
    timer = setInterval(ping, INTERVAL_MS);
    const onVis = () => { if (document.visibilityState === "visible") ping(); };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [isAuthed]);
}
