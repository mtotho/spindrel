import { useState, useEffect, useCallback } from "react";

/**
 * Drop-in replacement for `useState` that syncs active tab with `window.location.hash`.
 *
 * @param defaultTab  - tab to use when no hash is present
 * @param validTabs   - optional allowlist; invalid hashes fall back to defaultTab
 */
export function useHashTab<T extends string>(
  defaultTab: T,
  validTabs?: readonly T[],
): [T, (tab: T) => void] {
  const readHash = useCallback((): T => {
    const raw = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (!raw) return defaultTab;
    if (validTabs && !validTabs.includes(raw as T)) return defaultTab;
    return raw as T;
  }, [defaultTab, validTabs]);

  const [tab, setTabState] = useState<T>(readHash);

  // Re-evaluate when validTabs changes (handles async data loading)
  useEffect(() => {
    setTabState(readHash());
  }, [readHash]);

  // Listen for browser back/forward
  useEffect(() => {
    const onPopState = () => setTabState(readHash());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [readHash]);

  const setTab = useCallback(
    (next: T) => {
      setTabState(next);
      const encoded = encodeURIComponent(next);
      window.history.pushState(null, "", `#${encoded}`);
    },
    [],
  );

  return [tab, setTab];
}
