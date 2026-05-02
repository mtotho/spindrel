import { useEffect, useMemo } from "react";
import { channelSlug, useDashboardsStore } from "./dashboards";
import { useDashboardPins } from "../api/hooks/useDashboardPins";
import type { WidgetDashboardPin } from "../types/api";

export interface ChannelChatZones {
  rail: WidgetDashboardPin[];
  header: WidgetDashboardPin[];
  dock: WidgetDashboardPin[];
}

export function isChatShelfPin(pin: WidgetDashboardPin): boolean {
  if (pin.widget_config?.show_in_chat_shelf === true) return true;
  const legacyZone = pin.zone ?? "grid";
  return legacyZone === "rail" || legacyZone === "header" || legacyZone === "dock";
}

/** Derive chat-shelf pins for a channel from the dashboard-pins store.
 *
 *  No separate network call — subscribes to the same store that OmniPanel /
 *  WidgetsDashboardPage already hydrate. The current model is explicit:
 *  ``widget_config.show_in_chat_shelf === true`` means the artifact appears
 *  near chat. Legacy ``rail/header/dock`` zones are still treated as shelf
 *  pins until the workbench canvas normalizes them to ``grid``.
 *
 *  Header/dock buckets are kept for old call sites, but new UI renders one
 *  chat shelf from the rail bucket only.
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
      if (isChatShelfPin(pin)) buckets.rail.push(pin);
    }
    const gl = (p: WidgetDashboardPin) =>
      (p.grid_layout as { x?: number; y?: number } | undefined) ?? {};
    buckets.rail.sort((a, b) => (gl(a).y ?? 0) - (gl(b).y ?? 0) || a.position - b.position);
    buckets.dock.sort((a, b) => (gl(a).y ?? 0) - (gl(b).y ?? 0) || a.position - b.position);
    buckets.header.sort((a, b) => (gl(a).x ?? 0) - (gl(b).x ?? 0));
    return buckets;
  }, [pins, slug]);
}
