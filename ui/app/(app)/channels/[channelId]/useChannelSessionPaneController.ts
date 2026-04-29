import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { useMatch, useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import {
  channelSessionCatalogKey,
  useChannelSessionCatalog,
  usePromoteScratchSession,
} from "@/src/api/hooks/useChannelSessions";
import {
  requestScrollToMessage,
  type ScrollToMessageDetail,
} from "@/src/components/chat/renderers/FindResultsRenderer";
import {
  addChannelChatPane,
  buildChannelSessionChatSource,
  buildChannelSessionRoute,
  buildScratchChatSource,
  defaultChannelChatPaneLayout,
  maximizeChannelChatPane,
  moveChannelChatPane,
  paneIdForSurface,
  removeChannelChatPane,
  removeChannelSessionTabLayout,
  restoreChannelChatPanes,
  restoreMiniChannelChatPane,
  splitChannelChatPaneLayout,
  type ChannelChatPane,
  type ChannelSessionCatalogItem,
  type ChannelSessionSurface,
} from "@/src/lib/channelSessionSurfaces";
import { useScratchReturnStore } from "@/src/stores/scratchReturn";
import {
  useUIStore,
  type ChannelPanelPrefs,
  type ChannelPanelPrefsPatch,
} from "@/src/stores/ui";
import type { Channel } from "@/src/types/api";

type PatchChannelPanelPrefs = (channelId: string, patch: ChannelPanelPrefsPatch) => void;
type ChannelHeaderChromeMode = "canvas" | "session" | "primary";

export interface ChannelRouteSessionState {
  routeSessionId: string | null;
  isChannelSessionRoute: boolean;
  isScratchRoute: boolean;
  routeSessionSurface: ChannelSessionSurface | null;
  scratchUrlSessionId: string | null;
}

export function useChannelRouteSessionSurface(): ChannelRouteSessionState {
  const sessionMatch = useMatch("/channels/:channelId/session/:sessionId");
  const [scratchSearch] = useSearchParams();
  const routeSessionId = sessionMatch?.params.sessionId ?? null;
  const isChannelSessionRoute = !!sessionMatch && scratchSearch.get("surface") === "channel";
  const isScratchRoute = !!sessionMatch && !isChannelSessionRoute;
  const routeSessionSurface: ChannelSessionSurface | null = routeSessionId
    ? isScratchRoute
      ? { kind: "scratch", sessionId: routeSessionId }
      : { kind: "channel", sessionId: routeSessionId }
    : null;

  return {
    routeSessionId,
    isChannelSessionRoute,
    isScratchRoute,
    routeSessionSurface,
    scratchUrlSessionId: isScratchRoute ? routeSessionId : null,
  };
}

function labelMiniChatPane(
  pane: ChannelChatPane | null,
  catalog: ChannelSessionCatalogItem[] | undefined,
): { title: string; subtitle: string } {
  if (!pane) return { title: "Session", subtitle: "Mini chat" };
  if (pane.surface.kind === "primary") {
    const row = catalog?.find((item) => item.is_active) ?? null;
    return {
      title: row?.label?.trim() || row?.summary?.trim() || row?.preview?.trim() || "Primary session",
      subtitle: "Primary session",
    };
  }
  const surface = pane.surface;
  const row = catalog?.find((item) => item.session_id === surface.sessionId) ?? null;
  return {
    title: row?.label?.trim() || row?.summary?.trim() || row?.preview?.trim() || "Untitled session",
    subtitle: surface.kind === "scratch" ? "Scratch session" : row?.is_active ? "Primary session" : "Previous chat",
  };
}

interface UseChannelSessionPaneControllerArgs {
  channelId?: string;
  channel?: Channel | null;
  routeSession: ChannelRouteSessionState;
  overlay: ChannelSessionOverlayController;
  panelPrefs: ChannelPanelPrefs;
  patchChannelPanelPrefs: PatchChannelPanelPrefs;
  isMobile: boolean;
  setActiveFile: Dispatch<SetStateAction<string | null>>;
}

export interface ChannelSessionOverlayController {
  sessionsOverlayOpen: boolean;
  setSessionsOverlayOpen: Dispatch<SetStateAction<boolean>>;
  sessionsOverlayMode: "switch" | "split";
  pendingSplitSurface: ChannelSessionSurface | null;
  setPendingSplitSurface: Dispatch<SetStateAction<ChannelSessionSurface | null>>;
  openSessionsOverlay: () => void;
  openSplitOverlay: () => void;
}

export function useChannelSessionOverlayController(): ChannelSessionOverlayController {
  const [sessionsOverlayOpen, setSessionsOverlayOpen] = useState(false);
  const [sessionsOverlayMode, setSessionsOverlayMode] = useState<"switch" | "split">("switch");
  const [pendingSplitSurface, setPendingSplitSurface] = useState<ChannelSessionSurface | null>(null);
  const openSessionsOverlay = useCallback(() => {
    setSessionsOverlayMode("switch");
    setSessionsOverlayOpen(true);
  }, []);
  const openSplitOverlay = useCallback(() => {
    setSessionsOverlayMode("split");
    setSessionsOverlayOpen(true);
  }, []);

  return {
    sessionsOverlayOpen,
    setSessionsOverlayOpen,
    sessionsOverlayMode,
    pendingSplitSurface,
    setPendingSplitSurface,
    openSessionsOverlay,
    openSplitOverlay,
  };
}

export function useChannelSessionPaneController({
  channelId,
  channel,
  routeSession,
  overlay,
  panelPrefs,
  patchChannelPanelPrefs,
  isMobile,
  setActiveFile,
}: UseChannelSessionPaneControllerArgs) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const promoteScratch = usePromoteScratchSession();
  const setScratchReturn = useScratchReturnStore((s) => s.setScratchReturn);
  const clearScratchReturn = useScratchReturnStore((s) => s.clearScratchReturn);
  const { data: channelSessionCatalog } = useChannelSessionCatalog(channelId);
  const {
    routeSessionId,
    isScratchRoute,
    routeSessionSurface,
    scratchUrlSessionId,
  } = routeSession;
  const {
    sessionsOverlayOpen,
    setSessionsOverlayOpen,
    sessionsOverlayMode,
    pendingSplitSurface,
    setPendingSplitSurface,
    openSessionsOverlay,
    openSplitOverlay,
  } = overlay;
  const scratchLayoutRestoreRef = useRef<{
    explorerOpen: boolean;
    rightDockHidden: boolean;
    activeFile: string | null;
    splitMode: boolean;
  } | null>(null);
  const [scratchOpen, setScratchOpen] = useState(false);
  const [scratchPinnedSessionId, setScratchPinnedSessionId] = useState<string | null>(null);
  const [pendingFindJump, setPendingFindJump] = useState<ScrollToMessageDetail | null>(null);

  const currentBudgetSessionId = routeSessionId ?? channel?.active_session_id ?? null;

  const handleExitSessionRoute = useCallback(() => {
    if (!channelId) return;
    clearScratchReturn(channelId);
    setScratchPinnedSessionId(null);
    setScratchOpen(false);
    const restore = scratchLayoutRestoreRef.current;
    if (restore) {
      const uiState = useUIStore.getState();
      uiState.setFileExplorerOpen(restore.explorerOpen);
      uiState.setRightDockHidden(restore.rightDockHidden);
      setActiveFile(restore.activeFile);
      if (restore.splitMode !== uiState.fileExplorerSplit) {
        uiState.toggleFileExplorerSplit();
      }
      scratchLayoutRestoreRef.current = null;
    }
    navigate(`/channels/${channelId}`);
  }, [channelId, clearScratchReturn, navigate, setActiveFile]);

  useEffect(() => {
    if (isScratchRoute && scratchUrlSessionId && channelId) {
      setScratchReturn(channelId, scratchUrlSessionId);
    }
  }, [channelId, isScratchRoute, scratchUrlSessionId, setScratchReturn]);

  const scratchSource = useMemo(
    () =>
      channelId
        ? ({
            kind: "ephemeral" as const,
            sessionStorageKey: `channel:${channelId}:scratch`,
            parentChannelId: channelId,
            defaultBotId: channel?.bot_id,
            context: {
              page_name: "channel_scratch",
              payload: { channel_id: channelId },
            },
            scratchBoundChannelId: channelId,
            pinnedSessionId: scratchPinnedSessionId ?? undefined,
          })
        : null,
    [channelId, channel?.bot_id, scratchPinnedSessionId],
  );

  const handleScratchClose = useCallback(() => {
    setScratchOpen(false);
    setScratchPinnedSessionId(null);
  }, []);

  const miniPane = panelPrefs.chatPaneLayout.miniPane;
  const miniPaneSource = useMemo(() => {
    if (!channelId || !miniPane) return null;
    if (miniPane.surface.kind === "primary") {
      return { kind: "channel" as const, channelId };
    }
    if (miniPane.surface.kind === "scratch") {
      return buildScratchChatSource({
        channelId,
        botId: channel?.bot_id,
        sessionId: miniPane.surface.sessionId,
      });
    }
    return buildChannelSessionChatSource({
      channelId,
      botId: channel?.bot_id,
      sessionId: miniPane.surface.sessionId,
    });
  }, [channel?.bot_id, channelId, miniPane]);
  const miniPaneLabel = useMemo(
    () => labelMiniChatPane(miniPane, channelSessionCatalog),
    [channelSessionCatalog, miniPane],
  );
  const handleCloseMiniPane = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: {
        ...current.chatPaneLayout,
        miniPane: null,
      },
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const restoreMiniPane = useCallback(() => {
    if (!channelId || !miniPane) return;
    const currentSurface: ChannelSessionSurface = routeSessionSurface ?? { kind: "primary" };
    const shouldStartSplitFromRoute = !!routeSessionSurface || panelPrefs.chatPaneLayout.panes.length <= 1;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: shouldStartSplitFromRoute
        ? splitChannelChatPaneLayout(currentSurface, miniPane.surface)
        : restoreMiniChannelChatPane(current.chatPaneLayout),
    }));
    if (shouldStartSplitFromRoute) {
      navigate(`/channels/${channelId}`);
    }
  }, [channelId, miniPane, navigate, panelPrefs.chatPaneLayout.panes.length, patchChannelPanelPrefs, routeSessionSurface]);

  const visibleChatPanes = useMemo(() => {
    const layout = panelPrefs.chatPaneLayout;
    return layout.maximizedPaneId
      ? layout.panes.filter((pane) => pane.id === layout.maximizedPaneId)
      : layout.panes;
  }, [panelPrefs.chatPaneLayout]);
  const canvasActive = !routeSessionSurface && panelPrefs.chatPaneLayout.panes.length > 1;
  const headerPane = routeSessionSurface
    ? { id: paneIdForSurface(routeSessionSurface), surface: routeSessionSurface }
    : canvasActive && visibleChatPanes.length === 1
      ? visibleChatPanes[0] ?? null
      : { id: "primary", surface: { kind: "primary" } as ChannelSessionSurface };
  const headerPaneSessionId = headerPane?.surface.kind === "primary"
    ? channel?.active_session_id ?? null
    : headerPane?.surface.sessionId ?? null;
  const headerPaneCatalogRow = headerPaneSessionId
    ? channelSessionCatalog?.find((item) => item.session_id === headerPaneSessionId) ?? null
    : null;
  const headerPaneMeta = headerPane
    ? headerPane.surface.kind === "primary"
      ? "Primary"
      : headerPane.surface.kind === "scratch"
        ? "Scratch"
        : headerPaneCatalogRow?.is_active
          ? "Primary"
          : "Previous"
    : null;
  const channelHeaderChromeMode: ChannelHeaderChromeMode = canvasActive && visibleChatPanes.length > 1
    ? "canvas"
    : routeSessionSurface || canvasActive
      ? "session"
      : "primary";
  const headerBudgetSessionId = channelHeaderChromeMode === "canvas" ? null : headerPaneSessionId;

  const selectedPickerSessionId = useMemo(() => {
    if (routeSessionId) return routeSessionId;
    const layout = panelPrefs.chatPaneLayout;
    const focusedPane = layout.panes.find((pane) => pane.id === layout.focusedPaneId) ?? layout.panes[0] ?? null;
    if (!focusedPane || focusedPane.surface.kind === "primary") return null;
    return focusedPane.surface.sessionId;
  }, [panelPrefs.chatPaneLayout, routeSessionId]);
  const pickerHiddenSurfaces = useMemo(() => {
    const visibleSurfaces = routeSessionSurface
      ? [routeSessionSurface]
      : canvasActive
        ? panelPrefs.chatPaneLayout.panes.map((pane) => pane.surface)
        : [{ kind: "primary" } as ChannelSessionSurface];
    return [
      ...visibleSurfaces,
      ...(miniPane ? [miniPane.surface] : []),
    ];
  }, [canvasActive, miniPane, panelPrefs.chatPaneLayout.panes, routeSessionSurface]);

  const leaveScratchSurface = useCallback(() => {
    setScratchPinnedSessionId(null);
    setScratchOpen(false);
  }, []);
  const focusPane = useCallback((paneId: string) => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: { ...current.chatPaneLayout, focusedPaneId: paneId },
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const closePane = useCallback((paneId: string) => {
    if (!channelId) return;
    let remainingSurface: ChannelSessionSurface | null = null;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: (() => {
        const next = removeChannelChatPane(current.chatPaneLayout, paneId);
        if (next.panes.length === 1) {
          remainingSurface = next.panes[0]?.surface ?? { kind: "primary" };
          return {
            ...defaultChannelChatPaneLayout(),
            miniPane: next.miniPane,
          };
        }
        return next;
      })(),
    }));
    if (remainingSurface) {
      navigate(buildChannelSessionRoute(channelId, remainingSurface));
    }
  }, [channelId, navigate, patchChannelPanelPrefs]);
  const maximizePane = useCallback((paneId: string) => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: maximizeChannelChatPane(current.chatPaneLayout, paneId),
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const restorePanes = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: restoreChannelChatPanes(current.chatPaneLayout),
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const unsplitPane = useCallback((paneId: string) => {
    if (!channelId) return;
    let selectedSurface: ChannelSessionSurface | null = null;
    patchChannelPanelPrefs(channelId, (current) => ({
      sessionTabLayouts: removeChannelSessionTabLayout(current.sessionTabLayouts, current.chatPaneLayout),
      chatPaneLayout: (() => {
        const pane = current.chatPaneLayout.panes.find((candidate) => candidate.id === paneId) ?? null;
        if (!pane) return current.chatPaneLayout;
        selectedSurface = pane.surface;
        return {
          ...defaultChannelChatPaneLayout(),
          miniPane: current.chatPaneLayout.miniPane,
        };
      })(),
    }));
    if (selectedSurface) {
      navigate(buildChannelSessionRoute(channelId, selectedSurface));
    }
  }, [channelId, navigate, patchChannelPanelPrefs]);
  const movePane = useCallback((paneId: string, direction: "left" | "right") => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: moveChannelChatPane(current.chatPaneLayout, paneId, direction),
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const commitPaneWidths = useCallback((widths: Record<string, number>) => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: {
        ...current.chatPaneLayout,
        widths,
      },
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const activateChannelSessionSurface = useCallback((surface: ChannelSessionSurface, intent: "switch" | "split") => {
    if (!channelId) return;
    leaveScratchSurface();
    if (intent === "switch") {
      patchChannelPanelPrefs(channelId, (current) => ({
        chatPaneLayout: {
          ...defaultChannelChatPaneLayout(),
          miniPane: current.chatPaneLayout.miniPane,
        },
      }));
      navigate(buildChannelSessionRoute(channelId, surface));
      return;
    }
    const currentSurface: ChannelSessionSurface = routeSessionSurface ?? { kind: "primary" };
    const currentLayout = panelPrefs.chatPaneLayout;
    const shouldStartSplitFromRoute = !!routeSessionSurface || currentLayout.panes.length <= 1;
    if (intent === "split") {
      const id = paneIdForSurface(surface);
      const alreadyOpen = currentLayout.panes.some((pane) => pane.id === id);
      if (!shouldStartSplitFromRoute && !alreadyOpen && currentLayout.panes.length >= 3) {
        setPendingSplitSurface(surface);
        return;
      }
    }
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: shouldStartSplitFromRoute
        ? splitChannelChatPaneLayout(currentSurface, surface)
        : addChannelChatPane(current.chatPaneLayout, surface),
    }));
    navigate(`/channels/${channelId}`);
  }, [channelId, leaveScratchSurface, navigate, panelPrefs.chatPaneLayout, patchChannelPanelPrefs, routeSessionSurface]);
  const handleOpenFindResultSession = useCallback((detail: ScrollToMessageDetail) => {
    if (!channelId || !detail.sessionId) return;
    setPendingFindJump(detail);
    if (isMobile) {
      navigate(buildChannelSessionRoute(channelId, { kind: "channel", sessionId: detail.sessionId }));
      return;
    }
    activateChannelSessionSurface({ kind: "channel", sessionId: detail.sessionId }, "split");
  }, [activateChannelSessionSurface, channelId, isMobile, navigate]);
  useEffect(() => {
    if (!pendingFindJump?.sessionId) return;
    const routeReady = routeSessionId === pendingFindJump.sessionId;
    const paneReady = panelPrefs.chatPaneLayout.panes.some(
      (pane) => pane.surface.kind !== "primary" && pane.surface.sessionId === pendingFindJump.sessionId,
    );
    if (!routeReady && !paneReady) return;
    const timeout = window.setTimeout(() => {
      requestScrollToMessage(pendingFindJump);
      setPendingFindJump(null);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [panelPrefs.chatPaneLayout.panes, pendingFindJump, routeSessionId]);
  const replacePaneWithPendingSplit = useCallback((paneId: string) => {
    if (!channelId || !pendingSplitSurface) return;
    patchChannelPanelPrefs(channelId, (current) => {
      const nextPanes = current.chatPaneLayout.panes.map((pane) =>
        pane.id === paneId ? { id: paneIdForSurface(pendingSplitSurface), surface: pendingSplitSurface } : pane,
      );
      return {
        chatPaneLayout: {
          ...current.chatPaneLayout,
          panes: nextPanes,
          focusedPaneId: paneIdForSurface(pendingSplitSurface),
        },
      };
    });
    setPendingSplitSurface(null);
  }, [channelId, patchChannelPanelPrefs, pendingSplitSurface]);
  const makePanePrimary = useCallback((pane: ChannelChatPane) => {
    if (!channelId || pane.surface.kind === "primary") return;
    if (pane.surface.kind === "scratch") {
      promoteScratch.mutate({
        session_id: pane.surface.sessionId,
        parent_channel_id: channelId,
        bot_id: channel?.bot_id,
      });
      return;
    }
    void apiFetch(`/api/v1/channels/${channelId}/switch-session`, {
      method: "POST",
      body: JSON.stringify({ session_id: pane.surface.sessionId }),
    }).then(() => {
      void queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
      void queryClient.invalidateQueries({ queryKey: channelSessionCatalogKey(channelId) });
    });
  }, [channel?.bot_id, channelId, promoteScratch, queryClient]);

  const routeSessionSource = useMemo(() => {
    if (!routeSessionSurface || !channelId) return null;
    if (routeSessionSurface.kind === "scratch") {
      return buildScratchChatSource({
        channelId,
        botId: channel?.bot_id,
        sessionId: routeSessionSurface.sessionId,
      });
    }
    if (routeSessionSurface.kind === "channel") {
      return buildChannelSessionChatSource({
        channelId,
        botId: channel?.bot_id,
        sessionId: routeSessionSurface.sessionId,
      });
    }
    return null;
  }, [channel?.bot_id, channelId, routeSessionSurface]);

  return {
    currentBudgetSessionId,
    scratchSource,
    scratchOpen,
    handleScratchClose,
    sessionsOverlayOpen,
    setSessionsOverlayOpen,
    sessionsOverlayMode,
    openSessionsOverlay,
    openSplitOverlay,
    pendingSplitSurface,
    setPendingSplitSurface,
    channelSessionCatalog,
    miniPaneSource,
    miniPaneLabel,
    handleCloseMiniPane,
    restoreMiniPane,
    visibleChatPanes,
    canvasActive,
    headerPaneSessionId,
    headerPaneMeta,
    channelHeaderChromeMode,
    headerBudgetSessionId,
    selectedPickerSessionId,
    pickerHiddenSurfaces,
    focusPane,
    closePane,
    maximizePane,
    restorePanes,
    unsplitPane,
    movePane,
    commitPaneWidths,
    activateChannelSessionSurface,
    handleOpenFindResultSession,
    replacePaneWithPendingSplit,
    makePanePrimary,
    handleExitSessionRoute,
    routeSessionSource,
  };
}
