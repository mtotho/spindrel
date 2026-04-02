import { useState, useEffect, useCallback } from "react";
import { Platform } from "react-native";

/**
 * Drop-in replacement for `useState` that syncs active tab with `window.location.hash`.
 * Falls back to plain state on non-web platforms.
 *
 * @param defaultTab  - tab to use when no hash is present
 * @param validTabs   - optional allowlist; invalid hashes fall back to defaultTab
 */
export function useHashTab<T extends string>(
  defaultTab: T,
  validTabs?: readonly T[],
): [T, (tab: T) => void] {
  const isWeb = Platform.OS === "web";

  const readHash = useCallback((): T => {
    if (!isWeb) return defaultTab;
    const raw = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (!raw) return defaultTab;
    if (validTabs && !validTabs.includes(raw as T)) return defaultTab;
    return raw as T;
  }, [isWeb, defaultTab, validTabs]);

  const [tab, setTabState] = useState<T>(readHash);

  // Re-evaluate when validTabs changes (handles async data loading)
  useEffect(() => {
    setTabState(readHash());
  }, [readHash]);

  // Listen for browser back/forward
  useEffect(() => {
    if (!isWeb) return;
    const onPopState = () => setTabState(readHash());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [isWeb, readHash]);

  const setTab = useCallback(
    (next: T) => {
      setTabState(next);
      if (isWeb) {
        const encoded = encodeURIComponent(next);
        window.history.pushState(null, "", `#${encoded}`);
      }
    },
    [isWeb],
  );

  return [tab, setTab];
}
