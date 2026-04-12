/**
 * Per-channel preference: collapse rich tool results into badge mode.
 *
 * When `compact === true`, the chat UI ignores `envelope.display="inline"`
 * auto-expansion and renders every tool call as a click-to-expand badge.
 * Storage is per-channel so the user can let one channel be noisy and
 * another stay quiet.
 *
 * Stored in localStorage; no backend persistence by design — this is a
 * UX nudge, not configuration.
 */
import { useCallback, useEffect, useState } from "react";

const STORAGE_PREFIX = "spindrel.toolResultCompact.";

function readPref(channelId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + channelId) === "1";
  } catch {
    return false;
  }
}

function writePref(channelId: string, value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    if (value) {
      window.localStorage.setItem(STORAGE_PREFIX + channelId, "1");
    } else {
      window.localStorage.removeItem(STORAGE_PREFIX + channelId);
    }
  } catch {
    // ignore
  }
}

const STORAGE_EVENT = "spindrel:toolResultCompactChanged";

/**
 * Hook returning `[compact, setCompact]` for a channel. The setter
 * dispatches a browser event so other mounted MessageBubble instances
 * react immediately to the toggle.
 */
export function useToolResultCompact(channelId: string): [boolean, (v: boolean) => void] {
  const [compact, setCompact] = useState<boolean>(() => readPref(channelId));

  useEffect(() => {
    setCompact(readPref(channelId));
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ channelId: string }>).detail;
      if (detail?.channelId === channelId) {
        setCompact(readPref(channelId));
      }
    };
    window.addEventListener(STORAGE_EVENT, handler as EventListener);
    return () => window.removeEventListener(STORAGE_EVENT, handler as EventListener);
  }, [channelId]);

  const set = useCallback(
    (v: boolean) => {
      writePref(channelId, v);
      setCompact(v);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent(STORAGE_EVENT, { detail: { channelId } }),
        );
      }
    },
    [channelId],
  );

  return [compact, set];
}
