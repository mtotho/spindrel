import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

/** URL param that drives kiosk mode. Single source of truth so the state
 *  survives refresh, can be shared as a URL, and can be read from anywhere
 *  (e.g. AppShell) without a context provider. */
export const KIOSK_PARAM = "kiosk";
const IDLE_HIDE_CURSOR_MS = 3000;

interface WakeLockSentinel {
  release: () => Promise<void>;
  released: boolean;
  addEventListener?: (event: "release", handler: () => void) => void;
}

interface NavigatorWithWakeLock {
  wakeLock?: { request: (type: "screen") => Promise<WakeLockSentinel> };
}

export interface UseKioskModeResult {
  /** True when `?kiosk=1` is present in the current URL. */
  kiosk: boolean;
  /** Enter kiosk. Safe to call from a user-gesture handler; requests
   *  Browser Fullscreen + Wake Lock (both best-effort, fails silently on
   *  unsupported platforms). */
  enterKiosk: () => void;
  /** Exit kiosk — clears the URL param, exits fullscreen, releases wake
   *  lock. No-op if not currently kiosked. */
  exitKiosk: () => void;
  /** True when the pointer has been idle for `IDLE_HIDE_CURSOR_MS` inside
   *  kiosk mode. Consumer uses this to toggle `cursor-none` and fade any
   *  exit chrome. Always false when `kiosk` is false. */
  idle: boolean;
}

/** Kiosk mode primitive — read/write `?kiosk=1`, manage the optional
 *  Fullscreen / Wake Lock / idle-cursor layers.
 *
 *  All browser-API effects are best-effort so this hook is safe to use on
 *  older browsers, in iframes, or where the user denied the relevant
 *  permission. The URL param alone is sufficient to hide chrome via
 *  `AppShell`.
 *
 *  Esc-to-exit-fullscreen also exits kiosk — matches the user expectation
 *  that "Esc gets me out."
 */
export function useKioskMode(): UseKioskModeResult {
  const [params, setParams] = useSearchParams();
  const kiosk = params.get(KIOSK_PARAM) === "1";

  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const [idle, setIdle] = useState(false);

  const releaseWakeLock = useCallback(() => {
    const lock = wakeLockRef.current;
    wakeLockRef.current = null;
    if (lock && !lock.released) {
      lock.release().catch(() => {
        /* ignore — lock may already be releasing */
      });
    }
  }, []);

  const acquireWakeLock = useCallback(() => {
    const nav = navigator as unknown as NavigatorWithWakeLock;
    if (!nav.wakeLock?.request) return;
    nav.wakeLock
      .request("screen")
      .then((lock) => {
        wakeLockRef.current = lock;
        lock.addEventListener?.("release", () => {
          if (wakeLockRef.current === lock) wakeLockRef.current = null;
        });
      })
      .catch(() => {
        /* ignore — permission denied / feature-policy / http, etc */
      });
  }, []);

  const enterKiosk = useCallback(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set(KIOSK_PARAM, "1");
        return next;
      },
      { replace: false },
    );

    // Best-effort Fullscreen. The user click that triggered this call is
    // the fresh gesture the API requires.
    if (
      typeof document !== "undefined"
      && document.documentElement?.requestFullscreen
      && !document.fullscreenElement
    ) {
      document.documentElement.requestFullscreen().catch(() => {
        /* ignore */
      });
    }

    acquireWakeLock();
  }, [setParams, acquireWakeLock]);

  const exitKiosk = useCallback(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete(KIOSK_PARAM);
        return next;
      },
      { replace: false },
    );
    if (
      typeof document !== "undefined"
      && document.fullscreenElement
      && document.exitFullscreen
    ) {
      document.exitFullscreen().catch(() => {
        /* ignore */
      });
    }
    releaseWakeLock();
  }, [setParams, releaseWakeLock]);

  // Esc (or any external fullscreen exit) → exit kiosk. Only armed while
  // kiosked so normal-mode fullscreen usage is unaffected.
  useEffect(() => {
    if (!kiosk) return;
    const onFsChange = () => {
      if (!document.fullscreenElement) {
        setParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.delete(KIOSK_PARAM);
            return next;
          },
          { replace: false },
        );
        releaseWakeLock();
      }
    };
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, [kiosk, setParams, releaseWakeLock]);

  // Wake Lock auto-releases when the tab is hidden — re-acquire on return.
  useEffect(() => {
    if (!kiosk) return;
    const onVisibility = () => {
      if (document.visibilityState === "visible" && !wakeLockRef.current) {
        acquireWakeLock();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [kiosk, acquireWakeLock]);

  // Ensure wake lock is released whenever kiosk turns off for any reason.
  useEffect(() => {
    if (!kiosk) releaseWakeLock();
  }, [kiosk, releaseWakeLock]);

  // Idle cursor tracking. Reset timer on pointer / key / touch activity.
  useEffect(() => {
    if (!kiosk) {
      setIdle(false);
      return;
    }
    let timer: number | null = null;
    const reset = () => {
      setIdle(false);
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => setIdle(true), IDLE_HIDE_CURSOR_MS);
    };
    reset();
    window.addEventListener("mousemove", reset);
    window.addEventListener("keydown", reset);
    window.addEventListener("touchstart", reset, { passive: true });
    return () => {
      if (timer !== null) window.clearTimeout(timer);
      window.removeEventListener("mousemove", reset);
      window.removeEventListener("keydown", reset);
      window.removeEventListener("touchstart", reset);
    };
  }, [kiosk]);

  // Release wake lock on unmount.
  useEffect(() => () => releaseWakeLock(), [releaseWakeLock]);

  return { kiosk, enterKiosk, exitKiosk, idle };
}
