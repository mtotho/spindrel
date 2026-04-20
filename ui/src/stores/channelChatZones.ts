import { useEffect, useMemo } from "react";
import { channelSlug, useDashboardsStore } from "./dashboards";
import { useDashboardPins } from "../api/hooks/useDashboardPins";
import type { WidgetDashboardPin } from "../types/api";

export interface ChannelChatZones {
  rail: WidgetDashboardPin[];
  header: WidgetDashboardPin[];
  dock: WidgetDashboardPin[];
}

/** Derive chat-side zone buckets for a channel from the dashboard-pins store.
 *
 *  No separate network call — subscribes to the same store that OmniPanel /
 *  WidgetsDashboardPage already hydrate. Zone membership is stored directly
 *  on each pin (`pin.zone`) and authored via the multi-canvas editor, so
 *  grouping is a trivial filter.
 *
 *  The ``grid`` bucket is intentionally excluded — dashboard-only pins never
 *  appear on chat.
 */
export function useChannelChatZones(channelId: string | undefined): ChannelChatZones {
  const slug = channelId ? channelSlug(channelId) : undefined;
  const { pins } = useDashboardPins(slug ?? "");
  const hydrate = useDashboardsStore((s) => s.hydrate);
  const hasHydrated = useDashboardsStore((s) => s.hasHydrated);

  useEffect(() => {
    if (!hasHydrated) void hydrate();
  }, [hasHydrated, hydrate]);

  return useMemo<ChannelChatZones>(() => {
    if (!slug) {
      return { rail: [], header: [], dock: [] };
    }
    const buckets: ChannelChatZones = { rail: [], header: [], dock: [] };
    for (const pin of pins) {
      const zone = pin.zone ?? "grid";
      if (zone === "rail") buckets.rail.push(pin);
      else if (zone === "header") buckets.header.push(pin);
      else if (zone === "dock") buckets.dock.push(pin);
    }
    const gl = (p: WidgetDashboardPin) =>
      (p.grid_layout as { x?: number; y?: number } | undefined) ?? {};
    buckets.rail.sort((a, b) => (gl(a).y ?? 0) - (gl(b).y ?? 0) || a.position - b.position);
    buckets.dock.sort((a, b) => (gl(a).y ?? 0) - (gl(b).y ?? 0) || a.position - b.position);
    buckets.header.sort((a, b) => (gl(a).x ?? 0) - (gl(b).x ?? 0));
    return buckets;
  }, [pins, slug]);
}
