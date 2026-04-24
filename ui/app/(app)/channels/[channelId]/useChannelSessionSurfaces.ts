import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/src/api/client";
import { useUIStore } from "@/src/stores/ui";
import {
  addChannelSessionPanel,
  buildChannelSessionRoute,
  removeChannelSessionPanel,
  type ChannelSessionActivationIntent,
  type ChannelSessionPanel,
  type ChannelSessionSurface,
} from "@/src/lib/channelSessionSurfaces";

interface UseChannelSessionSurfacesOptions {
  channelId: string | undefined;
  onLeaveScratchSurface?: () => void;
}

export function useChannelSessionSurfaces({
  channelId,
  onLeaveScratchSurface,
}: UseChannelSessionSurfacesOptions) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const patchChannelPanelPrefs = useUIStore((s) => s.patchChannelPanelPrefs);

  const activateSurface = useCallback((
    surface: ChannelSessionSurface,
    intent: ChannelSessionActivationIntent,
  ) => {
    if (!channelId) return;
    if (intent === "split" && (surface.kind === "scratch" || surface.kind === "channel")) {
      patchChannelPanelPrefs(channelId, (current) => ({
        sessionPanels: addChannelSessionPanel(current.sessionPanels, surface),
      }));
      return;
    }

    onLeaveScratchSurface?.();

    if (surface.kind === "channel") {
      void apiFetch(`/api/v1/channels/${channelId}/switch-session`, {
        method: "POST",
        body: JSON.stringify({ session_id: surface.sessionId }),
      }).then(() => {
        queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
        queryClient.invalidateQueries({ queryKey: ["channels"] });
        queryClient.invalidateQueries({ queryKey: ["channel-session-catalog", channelId] });
        queryClient.invalidateQueries({ queryKey: ["channel-sessions", channelId] });
        queryClient.invalidateQueries({ queryKey: ["session-messages"] });
        navigate(buildChannelSessionRoute(channelId, surface));
      }).catch((err) => {
        console.error("Failed to switch channel session", err);
      });
      return;
    }

    navigate(buildChannelSessionRoute(channelId, surface));
  }, [channelId, navigate, onLeaveScratchSurface, patchChannelPanelPrefs, queryClient]);

  const removePanel = useCallback((panel: ChannelSessionPanel | string) => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      sessionPanels: removeChannelSessionPanel(current.sessionPanels, panel),
    }));
  }, [channelId, patchChannelPanelPrefs]);

  return {
    activateSurface,
    removePanel,
  };
}
