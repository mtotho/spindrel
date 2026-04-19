import { useEffect } from "react";
import { useDashboardPinsStore } from "../../stores/dashboardPins";

/** Hydrate the dashboard-pins store for a given slug and return its pins.
 *  The store holds state for a single "current" dashboard — rehydrates
 *  when `slug` changes. */
export function useDashboardPins(slug: string = "default") {
  const pins = useDashboardPinsStore((s) => s.pins);
  const currentSlug = useDashboardPinsStore((s) => s.currentSlug);
  const hasHydrated = useDashboardPinsStore((s) => s.hasHydrated);
  const loadError = useDashboardPinsStore((s) => s.loadError);
  const hydrate = useDashboardPinsStore((s) => s.hydrate);

  useEffect(() => {
    // Load on first mount, or whenever the requested slug differs from the
    // one we last hydrated for.
    if (!hasHydrated || currentSlug !== slug) {
      void hydrate(slug);
    }
  }, [hasHydrated, currentSlug, slug, hydrate]);

  // When slug doesn't match what's loaded yet, treat as loading so callers
  // don't flash stale pins from the previous dashboard.
  const loaded = hasHydrated && currentSlug === slug;

  return {
    pins: loaded ? pins : [],
    isLoading: !loaded,
    error: loadError,
    refetch: () => hydrate(slug),
  };
}
