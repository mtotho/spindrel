import { useEffect } from "react";
import { useDashboardPinsStore } from "../../stores/dashboardPins";

/** Hydrate the dashboard-pins store on mount. Reads from the zustand store,
 *  so caller components stay reactive to optimistic pin/unpin/config changes. */
export function useDashboardPins() {
  const pins = useDashboardPinsStore((s) => s.pins);
  const hasHydrated = useDashboardPinsStore((s) => s.hasHydrated);
  const loadError = useDashboardPinsStore((s) => s.loadError);
  const hydrate = useDashboardPinsStore((s) => s.hydrate);

  useEffect(() => {
    if (!hasHydrated) void hydrate();
  }, [hasHydrated, hydrate]);

  return {
    pins,
    isLoading: !hasHydrated,
    error: loadError,
    refetch: hydrate,
  };
}
