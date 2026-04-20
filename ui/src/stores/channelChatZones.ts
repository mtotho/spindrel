import { useEffect, useMemo } from "react";
import { channelSlug, useDashboardsStore } from "./dashboards";
import { useDashboardPins } from "../api/hooks/useDashboardPins";
import { classifyPin, resolvePreset } from "../lib/dashboardGrid";
import type { ChatZone, WidgetDashboardPin } from "../types/api";

export interface ChannelChatZones {
  rail: WidgetDashboardPin[];
  dock_right: WidgetDashboardPin[];
  header_chip: WidgetDashboardPin[];
}

/** Derive chat-side zone buckets for a channel from the dashboard-pins store.
 *
 *  No separate network call — subscribes to the same store that OmniPanel /
 *  WidgetsDashboardPage already hydrate. Zone membership is pure-positional
 *  via `classifyPin`, so any layout change in the dashboard re-buckets
 *  automatically on the next render.
 *
 *  The ``grid`` bucket is intentionally excluded — dashboard-only pins never
 *  appear on chat.
 */
export function useChannelChatZones(channelId: string | undefined): ChannelChatZones {
  const slug = channelId ? channelSlug(channelId) : undefined;
  const { pins } = useDashboardPins(slug ?? "");
  const dashboards = useDashboardsStore((s) => s.list);
  const hydrate = useDashboardsStore((s) => s.hydrate);
  const hasHydrated = useDashboardsStore((s) => s.hasHydrated);

  useEffect(() => {
    if (!hasHydrated) void hydrate();
  }, [hasHydrated, hydrate]);

  const gridConfig = useMemo(() => {
    if (!slug) return null;
    return dashboards.find((d) => d.slug === slug)?.grid_config ?? null;
  }, [dashboards, slug]);

  return useMemo<ChannelChatZones>(() => {
    if (!slug) {
      return { rail: [], dock_right: [], header_chip: [] };
    }
    const preset = resolvePreset(gridConfig);
    const buckets: ChannelChatZones = { rail: [], dock_right: [], header_chip: [] };
    for (const pin of pins) {
      const zone: ChatZone = classifyPin(pin, preset);
      if (zone === "rail") buckets.rail.push(pin);
      else if (zone === "dock_right") buckets.dock_right.push(pin);
      else if (zone === "header_chip") buckets.header_chip.push(pin);
    }
    // Per-zone ordering: rail keeps pin `position` (already the store's
    // natural order); dock_right sorts by y then x; header_chip by x.
    const gl = (p: WidgetDashboardPin) =>
      (p.grid_layout as { x?: number; y?: number } | undefined) ?? {};
    buckets.dock_right.sort((a, b) => {
      const ga = gl(a), gb = gl(b);
      return (ga.y ?? 0) - (gb.y ?? 0) || (ga.x ?? 0) - (gb.x ?? 0);
    });
    buckets.header_chip.sort((a, b) => (gl(a).x ?? 0) - (gl(b).x ?? 0));
    return buckets;
  }, [pins, gridConfig, slug]);
}
