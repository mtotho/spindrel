import { useCallback, useEffect, useMemo, useState, type ReactNode, type Dispatch, type SetStateAction } from "react";
import type { NavigateFunction, SetURLSearchParams } from "react-router-dom";
import {
  Cog,
  FolderOpen,
  LayoutDashboard as LayoutDashboardIcon,
  Layers,
  MessageCircle,
  NotebookText,
  PanelLeft as PanelLeftIcon,
  Search,
  Settings as SettingsIcon,
  StickyNote,
  Terminal as TerminalIcon,
} from "lucide-react";

import {
  getChatShortcutLabel,
  isEditableKeyboardTarget,
  isKeyboardHelpShortcut,
  isSwitchSessionsShortcut,
} from "@/src/components/chat/chatKeyboard";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useChannelChatZones } from "@/src/stores/channelChatZones";
import { usePaletteActions, type PaletteAction } from "@/src/stores/paletteActions";
import { defaultChannelPanelPrefs, useUIStore, type OmniPanelTab } from "@/src/stores/ui";
import type { Channel } from "@/src/types/api";
import {
  CHANNEL_CHAT_MIN_WIDTH,
  CHANNEL_PANEL_DEFAULT_WIDTH,
  CHANNEL_PANEL_MAX_WIDTH,
  CHANNEL_PANEL_MIN_WIDTH,
  clampChannelPanelWidth,
  resolveChannelPanelLayout,
} from "@/src/lib/channelPanelLayout";

export type PanelSpineAction = {
  id: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  disabledReason?: string;
};

function readLegacyRightDockWidth(): number {
  if (typeof window === "undefined") return CHANNEL_PANEL_DEFAULT_WIDTH;
  const raw = window.localStorage.getItem("chat-dock-right-width");
  const parsed = raw ? parseInt(raw, 10) : NaN;
  return clampChannelPanelWidth(Number.isFinite(parsed) ? parsed : CHANNEL_PANEL_DEFAULT_WIDTH);
}

type UseChannelWorkbenchControllerArgs = {
  channelId?: string;
  channel?: Channel;
  searchParams: URLSearchParams;
  setSearchParams: SetURLSearchParams;
  navigate: NavigateFunction;
  isMobile: boolean;
  isSystemChannel: boolean;
  viewportWidth: number;
  layoutMode: "full" | "rail-header-chat" | "rail-chat" | "dashboard-only";
  channelDashboardHref: string;
  findingsCount: number;
  openSessionsOverlay: () => void;
  openSplitOverlay: () => void;
  toggleSessionsOverlay: () => void;
  openKeyboardShortcuts: () => void;
  setBotInfoBotId: Dispatch<SetStateAction<string | null>>;
  setFindingsPanelOpen: Dispatch<SetStateAction<boolean>>;
};

export function useChannelWorkbenchController({
  channelId,
  channel,
  searchParams,
  setSearchParams,
  navigate,
  isMobile,
  isSystemChannel,
  viewportWidth,
  layoutMode,
  channelDashboardHref,
  findingsCount,
  openSessionsOverlay,
  openSplitOverlay,
  toggleSessionsOverlay,
  openKeyboardShortcuts,
  setBotInfoBotId,
  setFindingsPanelOpen,
}: UseChannelWorkbenchControllerArgs) {
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const workspaceId = channel?.resolved_workspace_id;
  const projectPath = typeof channel?.project?.root_path === "string"
    ? channel.project.root_path.replace(/^\/+|\/+$/g, "")
    : "";
  const projectWorkspaceId = typeof channel?.project?.workspace_id === "string"
    ? channel.project.workspace_id
    : undefined;
  const fileWorkspaceId = projectWorkspaceId || workspaceId;
  const fileRootPath = projectPath ? `/${projectPath}` : undefined;
  const [terminalRequest, setTerminalRequest] = useState<{ cwd: string; label: string } | null>(null);

  const buildWorkspaceTerminalCwd = useCallback((workspaceRelativePath?: string | null) => {
    if (!fileWorkspaceId) return null;
    const trimmed = (workspaceRelativePath || fileRootPath || `/channels/${channelId}`).replace(/^\/+|\/+$/g, "");
    return `workspace://${fileWorkspaceId}${trimmed ? `/${trimmed}` : ""}`;
  }, [channelId, fileRootPath, fileWorkspaceId]);

  const openTerminalAtPath = useCallback((workspaceRelativePath?: string | null) => {
    const cwd = buildWorkspaceTerminalCwd(workspaceRelativePath);
    if (!cwd) return;
    const labelRaw = workspaceRelativePath || fileRootPath || `/channels/${channelId}`;
    const labelPath = labelRaw.startsWith("/") ? labelRaw : `/${labelRaw}`;
    setTerminalRequest({
      cwd,
      label: labelPath || "/",
    });
  }, [buildWorkspaceTerminalCwd, channelId, fileRootPath]);

  const explorerWidth = useFileBrowserStore((s) => s.channelExplorerWidth);
  const setRememberedChannelPath = useFileBrowserStore((s) => s.setChannelExplorerPath);
  const legacyExplorerOpen = useUIStore((s) => s.fileExplorerOpen);
  const legacyOmniPanelTab = useUIStore((s) => s.omniPanelTab);
  const ensureChannelPanelPrefs = useUIStore((s) => s.ensureChannelPanelPrefs);
  const patchChannelPanelPrefs = useUIStore((s) => s.patchChannelPanelPrefs);
  const setChannelPanelTab = useUIStore((s) => s.setChannelPanelTab);
  const requestChannelFilesFocus = useUIStore((s) => s.requestChannelFilesFocus);
  const setMobileDrawerOpen = useUIStore((s) => s.setMobileDrawerOpen);
  const setMobileExpandedWidget = useUIStore((s) => s.setMobileExpandedWidget);
  const channelPanelPrefs = useUIStore((s) =>
    channelId ? s.channelPanelPrefs[channelId] : undefined,
  );
  const recentPages = useUIStore((s) => s.recentPages);
  const splitMode = useUIStore((s) => s.fileExplorerSplit);
  const setSplitMode = useUIStore((s) => s.setFileExplorerSplit);
  const toggleSplit = useUIStore((s) => s.toggleFileExplorerSplit);
  const legacyRightDockHidden = useUIStore((s) => s.rightDockHidden);

  const channelPanelDefaults = useMemo(() => ({
    ...defaultChannelPanelPrefs(),
    leftOpen: legacyExplorerOpen,
    rightOpen: !legacyRightDockHidden,
    leftWidth: explorerWidth,
    rightWidth: readLegacyRightDockWidth(),
    leftTab: legacyOmniPanelTab,
  }), [explorerWidth, legacyExplorerOpen, legacyOmniPanelTab, legacyRightDockHidden]);

  useEffect(() => {
    if (!channelId) return;
    ensureChannelPanelPrefs(channelId, channelPanelDefaults);
  }, [channelId, channelPanelDefaults, ensureChannelPanelPrefs]);

  // The OmniPanel's open-state and active tab are user-level intent, not
  // per-channel detail. Overlay the global `fileExplorerOpen`/`omniPanelTab`
  // on top of the channel's stored prefs so jumping between channels
  // preserves "I had Sessions open" instead of resetting to whatever each
  // channel happened to remember.
  const basePrefs = channelPanelPrefs ?? channelPanelDefaults;
  const panelPrefs = useMemo(
    () => ({
      ...basePrefs,
      leftOpen: legacyExplorerOpen,
      leftTab: legacyOmniPanelTab,
    }),
    [basePrefs, legacyExplorerOpen, legacyOmniPanelTab],
  );

  const { rail: railPins } = useChannelChatZones(channelId ?? "");
  const headerChipPins = useMemo(() => [], []);
  const dockPins = useMemo(() => [], []);
  const hasHeaderChips = false;
  const workbenchWidgetCount = railPins.length;
  const switchSessionsShortcut = getChatShortcutLabel("switchSessions");
  const focusLayoutShortcut = getChatShortcutLabel("focusLayout");
  const browseFilesShortcut = getChatShortcutLabel("browseFiles");
  const toggleWorkbenchShortcut = getChatShortcutLabel("toggleWorkbench");

  const openLeftPanelTab = useCallback((tab: OmniPanelTab) => {
    if (!channelId) return;
    if (tab === "files") {
      requestChannelFilesFocus(channelId);
      return;
    }
    patchChannelPanelPrefs(channelId, {
      leftOpen: true,
      mobileDrawerOpen: isMobile,
      leftTab: tab,
      focusModePrior: null,
    });
  }, [channelId, isMobile, patchChannelPanelPrefs, requestChannelFilesFocus]);

  const toggleExplorer = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => current.leftOpen
      ? { leftOpen: false }
      : { leftOpen: true, leftTab: current.leftTab, focusModePrior: null });
  }, [channelId, patchChannelPanelPrefs]);

  const openBrowseFiles = useCallback(() => {
    if (!channelId) return;
    requestChannelFilesFocus(channelId);
  }, [channelId, requestChannelFilesFocus]);

  const toggleRightDockPanel = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      rightOpen: !current.rightOpen,
      focusModePrior: null,
    }));
  }, [channelId, patchChannelPanelPrefs]);

  const focusOrRestorePanels = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => {
      if (current.leftOpen || current.rightOpen || !current.topChromeCollapsed) {
        return {
          focusModePrior: {
            leftOpen: current.leftOpen,
            rightOpen: false,
            topChromeCollapsed: current.topChromeCollapsed,
          },
          leftOpen: false,
          rightOpen: current.rightOpen,
          topChromeCollapsed: true,
        };
      }
      return {
        leftOpen: current.focusModePrior?.leftOpen ?? true,
        rightOpen: current.rightOpen,
        topChromeCollapsed: current.focusModePrior?.topChromeCollapsed ?? false,
        focusModePrior: null,
      };
    });
  }, [channelId, patchChannelPanelPrefs]);

  useEffect(() => {
    const handler = () => focusOrRestorePanels();
    window.addEventListener("spindrel:channel-focus-layout", handler);
    return () => window.removeEventListener("spindrel:channel-focus-layout", handler);
  }, [focusOrRestorePanels]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!isSystemChannel && isSwitchSessionsShortcut(e)) {
        e.preventDefault();
        toggleSessionsOverlay();
        return;
      }
      if (!isEditableKeyboardTarget(e.target) && isKeyboardHelpShortcut(e)) {
        e.preventDefault();
        openKeyboardShortcuts();
        return;
      }
      if (isEditableKeyboardTarget(e.target)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.altKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        focusOrRestorePanels();
        return;
      }
      if (mod && e.shiftKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        if (channelId) requestChannelFilesFocus(channelId);
        return;
      }
      if (mod && !e.shiftKey && e.key === "b") {
        e.preventDefault();
        toggleExplorer();
        return;
      }
      if (e.key === "Escape" && activeFile) {
        setActiveFile(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    activeFile,
    channelId,
    focusOrRestorePanels,
    isSystemChannel,
    openKeyboardShortcuts,
    requestChannelFilesFocus,
    toggleExplorer,
    toggleSessionsOverlay,
  ]);

  const showFileViewer = activeFile !== null;
  const showRailZone = layoutMode !== "dashboard-only";
  const showHeaderChips = false;
  const showDockZone = false;
  const dashboardOnly = layoutMode === "dashboard-only";
  const dockBlockedByFileViewer = showFileViewer && !splitMode;
  const panelLayout = resolveChannelPanelLayout({
    availableWidth: viewportWidth || 0,
    isMobile,
    layoutMode,
    hasLeftPanel: !!channelId && !isSystemChannel && showRailZone,
    hasRightPanel: false,
    leftOpen: panelPrefs.leftOpen,
    rightOpen: panelPrefs.rightOpen,
    leftPinned: panelPrefs.leftPinned,
    rightPinned: panelPrefs.rightPinned,
    leftWidth: panelPrefs.leftWidth,
    rightWidth: panelPrefs.rightWidth,
  });
  const showExplorer = isMobile
    ? panelPrefs.mobileDrawerOpen
    : panelLayout.left.mode !== "closed";
  const showRightDock = false;
  const overlayPanelOpen = panelLayout.left.mode === "overlay" || panelLayout.right.mode === "overlay";

  const panelResizeMax = useCallback((side: "left" | "right") => {
    const panelMode = side === "left" ? panelLayout.left.mode : panelLayout.right.mode;
    if (panelMode !== "push") return CHANNEL_PANEL_MAX_WIDTH;
    const viewport = viewportWidth || CHANNEL_CHAT_MIN_WIDTH + CHANNEL_PANEL_MAX_WIDTH;
    const otherPushedWidth =
      side === "left"
        ? (panelLayout.right.mode === "push" ? panelLayout.right.width : 0)
        : (panelLayout.left.mode === "push" ? panelLayout.left.width : 0);
    const safeWidth = viewport - CHANNEL_CHAT_MIN_WIDTH - otherPushedWidth - 40;
    return Math.max(
      CHANNEL_PANEL_MIN_WIDTH,
      Math.min(CHANNEL_PANEL_MAX_WIDTH, safeWidth),
    );
  }, [panelLayout.left.mode, panelLayout.left.width, panelLayout.right.mode, panelLayout.right.width, viewportWidth]);
  const leftPanelResizeMax = panelResizeMax("left");
  const rightPanelResizeMax = panelResizeMax("right");

  const closeOverlayPanels = useCallback(() => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, {
      ...(panelLayout.left.mode === "overlay" ? { leftOpen: false } : {}),
      ...(panelLayout.right.mode === "overlay" ? { rightOpen: false } : {}),
    });
  }, [channelId, panelLayout.left.mode, panelLayout.right.mode, patchChannelPanelPrefs]);

  useEffect(() => {
    if (!overlayPanelOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (isEditableKeyboardTarget(e.target)) return;
      closeOverlayPanels();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [closeOverlayPanels, overlayPanelOpen]);

  const leftSpineActions = useMemo<PanelSpineAction[]>(() => {
    const actions: PanelSpineAction[] = [
      {
        id: "sessions",
        label: "Sessions",
        icon: <MessageCircle size={15} />,
        onSelect: () => openLeftPanelTab("sessions"),
      },
      ...(fileWorkspaceId ? [{
        id: "notes",
        label: "Notes",
        icon: <NotebookText size={15} />,
        onSelect: () => openLeftPanelTab("notes"),
      }] : []),
      {
        id: "widgets",
        label: "Widgets",
        hint: workbenchWidgetCount > 0 ? String(workbenchWidgetCount) : undefined,
        icon: <Layers size={15} />,
        onSelect: () => openLeftPanelTab("widgets"),
      },
    ];
    if (fileWorkspaceId) {
      actions.push({
        id: "files",
        label: "Files",
        icon: <FolderOpen size={15} />,
        onSelect: () => openLeftPanelTab("files"),
      });
    }
    return actions;
  }, [fileWorkspaceId, openLeftPanelTab, workbenchWidgetCount]);

  const rightSpineActions = useMemo<PanelSpineAction[]>(() => [], []);

  const displayName = channel?.display_name || channel?.name || channel?.client_id || "Chat";

  const registerPaletteActions = usePaletteActions((s) => s.register);
  useEffect(() => {
    if (!channelId) return;
    const channelLabel = displayName ? `#${displayName}` : undefined;
    const actions: PaletteAction[] = [];

    if (fileWorkspaceId && !isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:browse-files`,
        label: "Browse workspace files",
        hint: channelLabel,
        icon: FolderOpen,
        category: "This Channel",
        onSelect: () => openBrowseFiles(),
      });
      actions.push({
        id: `channel:${channelId}:open-terminal`,
        label: projectPath ? "Open terminal in project" : "Open terminal in channel workspace",
        hint: projectPath ? `/${projectPath}` : channelLabel,
        icon: TerminalIcon,
        category: "This Channel",
        onSelect: () => openTerminalAtPath(fileRootPath || `/channels/${channelId}`),
      });
    }

    if (!isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:switch-sessions`,
        label: "Switch sessions",
        hint: switchSessionsShortcut,
        icon: MessageCircle,
        category: "This Channel",
        onSelect: () => openSessionsOverlay(),
      });
      actions.push({
        id: `channel:${channelId}:new-session`,
        label: "New session",
        hint: channelLabel,
        icon: StickyNote,
        category: "This Channel",
        onSelect: () => openSessionsOverlay(),
      });
      actions.push({
        id: `channel:${channelId}:add-session-split`,
        label: "Add session split",
        hint: "Picker: Cmd/Ctrl+Enter",
        icon: Layers,
        category: "This Channel",
        onSelect: () => openSplitOverlay(),
      });
      actions.push({
        id: `channel:${channelId}:open-widgets`,
        label: "Open widgets",
        hint: workbenchWidgetCount > 0 ? `${workbenchWidgetCount} widget${workbenchWidgetCount === 1 ? "" : "s"}` : channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => openLeftPanelTab("widgets"),
      });
      if (fileWorkspaceId) {
        actions.push({
          id: `channel:${channelId}:open-notes`,
          label: "Open notes",
          hint: channelLabel,
          icon: NotebookText,
          category: "This Channel",
          onSelect: () => openLeftPanelTab("notes"),
        });
        actions.push({
          id: `channel:${channelId}:open-files`,
          label: "Browse files",
          hint: browseFilesShortcut,
          icon: FolderOpen,
          category: "This Channel",
          onSelect: () => openLeftPanelTab("files"),
        });
      }
      actions.push({
        id: `channel:${channelId}:toggle-left-panel`,
        label: panelPrefs.leftOpen ? "Hide workbench" : "Show workbench",
        hint: toggleWorkbenchShortcut,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => patchChannelPanelPrefs(channelId, { leftOpen: !panelPrefs.leftOpen }),
      });
      actions.push({
        id: `channel:${channelId}:pin-left-panel`,
        label: panelPrefs.leftPinned ? "Unpin workbench" : "Pin workbench open",
        hint: channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => patchChannelPanelPrefs(channelId, { leftPinned: !panelPrefs.leftPinned, leftOpen: true }),
      });
      actions.push({
        id: `channel:${channelId}:focus-mode`,
        label: panelPrefs.leftOpen ? "Focus chat panes" : "Restore workbench",
        hint: focusLayoutShortcut,
        icon: LayoutDashboardIcon,
        category: "This Channel",
        onSelect: () => focusOrRestorePanels(),
      });
      actions.push({
        id: `channel:${channelId}:bot-context`,
        label: "View bot context",
        hint: channelLabel,
        icon: Cog,
        category: "This Channel",
        onSelect: () => setBotInfoBotId(channel?.bot_id || null),
      });
      actions.push({
        id: `channel:${channelId}:dashboard`,
        label: "Channel workbench",
        hint: channelLabel,
        icon: LayoutDashboardIcon,
        category: "This Channel",
        onSelect: () => navigate(channelDashboardHref),
      });
    }

    actions.push({
      id: `channel:${channelId}:keyboard-shortcuts`,
      label: "Keyboard shortcuts",
      hint: getChatShortcutLabel("showKeyboardHelp"),
      icon: Search,
      category: "This Channel",
      onSelect: () => openKeyboardShortcuts(),
    });

    actions.push({
      id: `channel:${channelId}:settings`,
      label: "Channel settings",
      hint: channelLabel,
      icon: SettingsIcon,
      category: "This Channel",
      onSelect: () => navigate(`/channels/${channelId}/settings`),
    });

    if (isSystemChannel) {
      actions.push({
        id: `channel:${channelId}:findings`,
        label: "Findings",
        hint: findingsCount > 0 ? `${findingsCount} pending` : channelLabel,
        icon: PanelLeftIcon,
        category: "This Channel",
        onSelect: () => setFindingsPanelOpen((p) => !p),
      });
    }

    return registerPaletteActions(`channel:${channelId}`, actions);
  }, [
    channelId,
    displayName,
    fileWorkspaceId,
    isSystemChannel,
    findingsCount,
    channel?.bot_id,
    channelDashboardHref,
    focusOrRestorePanels,
    focusLayoutShortcut,
    browseFilesShortcut,
    fileRootPath,
    navigate,
    openKeyboardShortcuts,
    openBrowseFiles,
    openLeftPanelTab,
    openSessionsOverlay,
    openSplitOverlay,
    openTerminalAtPath,
    panelPrefs.leftOpen,
    panelPrefs.topChromeCollapsed,
    panelPrefs.leftPinned,
    workbenchWidgetCount,
    patchChannelPanelPrefs,
    projectPath,
    registerPaletteActions,
    setBotInfoBotId,
    setFindingsPanelOpen,
    toggleRightDockPanel,
    switchSessionsShortcut,
    toggleWorkbenchShortcut,
  ]);

  const [enteringFromDock] = useState(() => searchParams.get("from") === "dock");
  useEffect(() => {
    if (searchParams.get("from") === "dock") {
      const next = new URLSearchParams(searchParams);
      next.delete("from");
      setSearchParams(next, { replace: true });
    }
    // Mount-only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [entranceClassActive, setEntranceClassActive] = useState(enteringFromDock);
  useEffect(() => {
    if (!enteringFromDock) return;
    const timer = window.setTimeout(() => setEntranceClassActive(false), 360);
    return () => window.clearTimeout(timer);
  }, [enteringFromDock]);

  return {
    activeFile,
    setActiveFile,
    workspaceId,
    projectPath,
    projectWorkspaceId,
    fileWorkspaceId,
    fileRootPath,
    terminalRequest,
    setTerminalRequest,
    openTerminalAtPath,
    setRememberedChannelPath,
    patchChannelPanelPrefs,
    setChannelPanelTab,
    requestChannelFilesFocus,
    setMobileDrawerOpen,
    setMobileExpandedWidget,
    recentPages,
    splitMode,
    setSplitMode,
    toggleSplit,
    panelPrefs,
    railPins,
    headerChipPins,
    dockPins,
    hasHeaderChips,
    openLeftPanelTab,
    toggleExplorer,
    openBrowseFiles,
    toggleRightDockPanel,
    focusOrRestorePanels,
    closeOverlayPanels,
    showFileViewer,
    showRailZone,
    showHeaderChips,
    showDockZone,
    dashboardOnly,
    dockBlockedByFileViewer,
    panelLayout,
    showExplorer,
    showRightDock,
    overlayPanelOpen,
    leftPanelResizeMax,
    rightPanelResizeMax,
    leftSpineActions,
    rightSpineActions,
    displayName,
    entranceClassActive,
  };
}
