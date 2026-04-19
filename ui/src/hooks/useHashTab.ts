import { useState, useEffect, useCallback } from "react";
import { useLocation } from "react-router-dom";

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
  const location = useLocation();

  const parseHash = useCallback(
    (hash: string): T => {
      const raw = decodeURIComponent(hash.replace(/^#/, ""));
      if (!raw) return defaultTab;
      if (validTabs && !validTabs.includes(raw as T)) return defaultTab;
      return raw as T;
    },
    [defaultTab, validTabs],
  );

  const [tab, setTabState] = useState<T>(() => parseHash(window.location.hash));

  // Re-read whenever react-router's location hash changes (covers both
  // programmatic navigate(...) and validTabs becoming available async).
  useEffect(() => {
    setTabState(parseHash(location.hash));
  }, [location.hash, parseHash]);

  const setTab = useCallback((next: T) => {
    setTabState(next);
    const encoded = encodeURIComponent(next);
    // Preserve current pathname + search so we don't clobber query params.
    const { pathname, search } = window.location;
    window.history.pushState(null, "", `${pathname}${search}#${encoded}`);
  }, []);

  return [tab, setTab];
}
