import { useState, useEffect, useCallback, useRef } from "react";
import { useLocation } from "react-router-dom";
import { writeHashTabHistory } from "./useHashTabHistory";

/**
 * Drop-in replacement for `useState` that syncs active tab with `window.location.hash`.
 *
 * @param defaultTab  - tab to use when no hash is present
 * @param validTabs   - optional allowlist; invalid hashes fall back to defaultTab
 *
 * Note: `validTabs` is read via ref so callers can pass a freshly-allocated
 * array each render (e.g. `ALL_TABS.map(t => t.key)`) without thrashing the
 * `parseHash` identity — otherwise the sync effect re-fires on every render
 * and overwrites the user's click with the stale react-router hash value.
 */
export function useHashTab<T extends string>(
  defaultTab: T,
  validTabs?: readonly T[],
): [T, (tab: T) => void] {
  const location = useLocation();

  const validTabsRef = useRef(validTabs);
  validTabsRef.current = validTabs;

  const parseHash = useCallback(
    (hash: string): T => {
      const raw = decodeURIComponent(hash.replace(/^#/, ""));
      if (!raw) return defaultTab;
      const allowlist = validTabsRef.current;
      if (allowlist && !allowlist.includes(raw as T)) return defaultTab;
      return raw as T;
    },
    [defaultTab],
  );

  const [tab, setTabState] = useState<T>(() => parseHash(window.location.hash));

  // Re-read whenever react-router's location hash changes (covers both
  // programmatic navigate(...) and validTabs becoming available async).
  useEffect(() => {
    setTabState(parseHash(location.hash));
  }, [location.hash, parseHash]);

  const setTab = useCallback((next: T) => {
    setTabState(next);
    writeHashTabHistory(window.history, window.location.pathname, window.location.search, next, "replace");
  }, []);

  return [tab, setTab];
}
