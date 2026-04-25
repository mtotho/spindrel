import { useCallback, useEffect, useMemo, useState } from "react";
import { sessionResumeDismissKey } from "@/src/lib/sessionResume";

const GLOBAL_DISABLED_KEY = "spindrel.sessionResume.globalDisabled";
const CHANNEL_DISABLED_PREFIX = "spindrel.sessionResume.channelDisabled.";
const DISMISSED_PREFIX = "spindrel.sessionResume.dismissed.";
const STORAGE_EVENT = "spindrel:sessionResumePrefsChanged";

function readBool(key: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeBool(key: string, value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    if (value) window.localStorage.setItem(key, "1");
    else window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures; this is a local preference only.
  }
}

function readString(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeString(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage failures.
  }
}

function dispatchPrefsChanged(channelId?: string | null, sessionId?: string | null) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(STORAGE_EVENT, { detail: { channelId, sessionId } }),
  );
}

export function useSessionResumePrefs(
  channelId: string | null | undefined,
  sessionId: string | null | undefined,
  lastVisibleMessageAt: string | null | undefined,
) {
  const [version, setVersion] = useState(0);
  const channelKey = channelId ? `${CHANNEL_DISABLED_PREFIX}${channelId}` : null;
  const dismissedStorageKey = sessionId ? `${DISMISSED_PREFIX}${sessionId}` : null;
  const dismissKey = sessionResumeDismissKey(sessionId, lastVisibleMessageAt);

  useEffect(() => {
    const handler = () => setVersion((v) => v + 1);
    window.addEventListener(STORAGE_EVENT, handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener(STORAGE_EVENT, handler);
      window.removeEventListener("storage", handler);
    };
  }, []);

  const globalEnabled = !readBool(GLOBAL_DISABLED_KEY);
  const channelEnabled = channelKey ? !readBool(channelKey) : true;
  const dismissed = !!dismissKey && dismissedStorageKey
    ? readString(dismissedStorageKey) === dismissKey
    : false;

  const dismissCurrent = useCallback(() => {
    if (!dismissedStorageKey || !dismissKey) return;
    writeString(dismissedStorageKey, dismissKey);
    dispatchPrefsChanged(channelId, sessionId);
    setVersion((v) => v + 1);
  }, [channelId, dismissKey, dismissedStorageKey, sessionId]);

  const setGlobalEnabled = useCallback((enabled: boolean) => {
    writeBool(GLOBAL_DISABLED_KEY, !enabled);
    dispatchPrefsChanged(channelId, sessionId);
    setVersion((v) => v + 1);
  }, [channelId, sessionId]);

  const setChannelEnabled = useCallback((enabled: boolean) => {
    if (!channelKey) return;
    writeBool(channelKey, !enabled);
    dispatchPrefsChanged(channelId, sessionId);
    setVersion((v) => v + 1);
  }, [channelId, channelKey, sessionId]);

  return useMemo(
    () => ({
      enabled: globalEnabled && channelEnabled,
      dismissed,
      globalEnabled,
      channelEnabled,
      dismissCurrent,
      hideGlobal: () => setGlobalEnabled(false),
      hideChannel: () => setChannelEnabled(false),
      setGlobalEnabled,
      setChannelEnabled,
      version,
    }),
    [
      channelEnabled,
      dismissCurrent,
      dismissed,
      globalEnabled,
      setChannelEnabled,
      setGlobalEnabled,
      version,
    ],
  );
}
