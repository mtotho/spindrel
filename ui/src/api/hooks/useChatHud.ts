import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useActivatableIntegrations } from "./useChannels";
import type { ChatHudWidget, HudData } from "@/src/types/api";

/** Poll a HUD endpoint for data-driven widget content. */
export function useHudData(
  integrationId: string | undefined,
  endpoint: string | undefined,
  pollInterval: number = 60,
  enabled: boolean = true,
) {
  return useQuery<HudData>({
    queryKey: ["hud-data", integrationId, endpoint],
    queryFn: () =>
      apiFetch<HudData>(`/integrations/${integrationId}${endpoint}`),
    enabled: !!integrationId && !!endpoint && enabled,
    refetchInterval: pollInterval * 1000,
    staleTime: (pollInterval * 1000) / 2,
  });
}

export interface ActiveHud {
  key: string;
  integrationId: string;
  widget: ChatHudWidget;
}

/** Resolve which widget IDs are visible for an integration based on its HUD preset. */
function resolveVisibleWidgetIds(ig: { chat_hud?: { id: string }[]; chat_hud_presets?: Record<string, { widgets: string[] }>; activation_config?: Record<string, any> }): Set<string> | null {
  const presets = ig.chat_hud_presets;
  if (!presets || Object.keys(presets).length === 0) return null; // no presets → show all

  const selectedPreset = ig.activation_config?.hud_preset as string | undefined;
  const presetNames = Object.keys(presets);

  // Use selected preset, fall back to first preset if invalid/missing
  const preset = (selectedPreset && presets[selectedPreset]) ? presets[selectedPreset] : presets[presetNames[0]];
  return new Set(preset.widgets);
}

/** Reads activated integrations for a channel and groups their HUD widgets by style. */
export function useIntegrationHuds(channelId: string | undefined) {
  const { data: integrations } = useActivatableIntegrations(channelId);

  return useMemo(() => {
    const statusStrips: ActiveHud[] = [];
    const sidePanels: ActiveHud[] = [];
    const inputBars: ActiveHud[] = [];
    const floatingActions: ActiveHud[] = [];

    if (integrations) {
      for (const ig of integrations) {
        if (!ig.activated) continue;
        const widgets = ig.chat_hud ?? [];
        const visibleIds = resolveVisibleWidgetIds(ig);
        for (const w of widgets) {
          // If presets are defined, filter by active preset's widget list
          if (visibleIds !== null && !visibleIds.has(w.id)) continue;
          const hud: ActiveHud = {
            key: `${ig.integration_type}:${w.id}`,
            integrationId: ig.integration_type,
            widget: w,
          };
          switch (w.style) {
            case "status_strip":
              statusStrips.push(hud);
              break;
            case "side_panel":
              sidePanels.push(hud);
              break;
            case "input_bar":
              inputBars.push(hud);
              break;
            case "floating_action":
              floatingActions.push(hud);
              break;
          }
        }
      }
    }

    return { statusStrips, sidePanels, inputBars, floatingActions };
  }, [integrations]);
}
