import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";
import { useRenameSession } from "@/src/api/hooks/useChannelSessions";
import type { ChannelPanelPrefs, ChannelPanelPrefsPatch, RecentPage } from "@/src/stores/ui";
import {
  CHANNEL_FILE_LINK_OPEN_EVENT,
  CHANNEL_FILES_PATH_PARAM,
  CHANNEL_OPEN_FILE_PARAM,
  directoryForWorkspaceFile,
  normalizeWorkspaceNavigationPath,
  readChannelFileIntent,
  type ChannelFileLinkOpenDetail,
} from "@/src/lib/channelFileNavigation";
import {
  addChannelChatPane,
  addChannelSessionTabLayout,
  buildChannelSessionTabItems,
  paneIdForSurface,
  replaceFocusedChannelChatPane,
  removeChannelSessionTabLayout,
  sessionTabKeyForChatPaneLayout,
  snapshotChannelSessionTabLayout,
  splitChannelChatPaneLayout,
  surfaceKey,
  type ChannelChatPane,
  type ChannelChatPaneLayout,
  type ChannelSessionActivationIntent,
  type ChannelSessionCatalogItem,
  type ChannelSessionSurface,
  type ChannelSessionUnreadLike,
} from "@/src/lib/channelSessionSurfaces";
import type { ChannelFileTabItem, ChannelTopTabItem } from "./ChannelSessionTabs";

type ChannelLike = {
  active_session_id?: string | null;
  bot_id?: string | null;
};

type SetSearchParams = (
  nextInit: URLSearchParams,
  navigateOptions?: { replace?: boolean },
) => void;

type DirtyAction =
  | { type: "select"; path: string; split?: boolean }
  | { type: "selectSession"; tab: ChannelTopTabItem }
  | { type: "close" }
  | { type: "closeFileTab"; path: string }
  | { type: "closePanel" };

interface UseChannelTopTabsControllerArgs {
  channelId?: string;
  channel?: ChannelLike | null;
  projectPath: string;
  currentRouteHref: string;
  recentPages: RecentPage[];
  channelSessionCatalog?: readonly ChannelSessionCatalogItem[] | null;
  unreadStates?: readonly ChannelSessionUnreadLike[] | null;
  panelPrefs: ChannelPanelPrefs;
  patchChannelPanelPrefs: (channelId: string, patch: ChannelPanelPrefsPatch) => void;
  routeSessionSurface: ChannelSessionSurface | null;
  canvasActive: boolean;
  activeFile: string | null;
  setActiveFile: Dispatch<SetStateAction<string | null>>;
  splitMode: boolean;
  setSplitMode: (split: boolean) => void;
  isMobile: boolean;
  setMobileDrawerOpen: (channelId: string, open: boolean) => void;
  setRememberedChannelPath: (channelId: string, path: string) => void;
  searchParams: URLSearchParams;
  setSearchParams: SetSearchParams;
  navigate: NavigateFunction;
  activateChannelSessionSurface: (
    surface: ChannelSessionSurface,
    intent: ChannelSessionActivationIntent,
  ) => void;
  focusPane: (paneId: string) => void;
  makePanePrimary: (pane: ChannelChatPane) => void;
}

function fileTabKey(path: string): string {
  return `file:${path}`;
}

function fileTabLabel(path: string): string {
  return path.split("/").pop() || path || "Untitled";
}

function fileTabMeta(path: string): string | null {
  const directory = directoryForWorkspaceFile(path);
  return directory || null;
}

function moveTabKeyToFront(keys: string[], key: string, limit = 40): string[] {
  return [key, ...keys.filter((candidate) => candidate !== key)].slice(0, limit);
}

function isWorkspaceScopedPath(path: string): boolean {
  return /^(bots|channels|common|projects|workspaces)\//.test(path);
}

export function useChannelTopTabsController({
  channelId,
  channel,
  projectPath,
  currentRouteHref,
  recentPages,
  channelSessionCatalog,
  unreadStates,
  panelPrefs,
  patchChannelPanelPrefs,
  routeSessionSurface,
  canvasActive,
  activeFile,
  setActiveFile,
  splitMode,
  setSplitMode,
  isMobile,
  setMobileDrawerOpen,
  setRememberedChannelPath,
  searchParams,
  setSearchParams,
  navigate,
  activateChannelSessionSurface,
  focusPane,
  makePanePrimary,
}: UseChannelTopTabsControllerArgs) {
  const renameSession = useRenameSession();
  const fileDirtyRef = useRef(false);
  const [pendingDirtyAction, setPendingDirtyAction] = useState<DirtyAction | null>(null);
  const [pendingSessionTabKey, setPendingSessionTabKey] = useState<string | null>(null);

  const resolveChannelOpenFilePath = useCallback((path: string): string => {
    const normalized = normalizeWorkspaceNavigationPath(path) ?? path.replace(/^\/+/, "");
    if (!projectPath || isWorkspaceScopedPath(normalized) || normalized.startsWith(`${projectPath}/`)) {
      return normalized;
    }
    return `${projectPath}/${normalized}`;
  }, [projectPath]);

  const focusedChatPane = useMemo(
    () =>
      panelPrefs.chatPaneLayout.panes.find((pane) => pane.id === panelPrefs.chatPaneLayout.focusedPaneId)
      ?? panelPrefs.chatPaneLayout.panes[0]
      ?? null,
    [panelPrefs.chatPaneLayout.focusedPaneId, panelPrefs.chatPaneLayout.panes],
  );
  const activeSessionTabSurface: ChannelSessionSurface = routeSessionSurface
    ?? (canvasActive && focusedChatPane ? focusedChatPane.surface : { kind: "primary" });
  const activeSplitTabKey = canvasActive ? sessionTabKeyForChatPaneLayout(panelPrefs.chatPaneLayout) : null;
  const activeSessionTabKey = activeSplitTabKey ?? surfaceKey(activeSessionTabSurface);
  const openSessionTabSurfaceKeys = useMemo(() => {
    if (routeSessionSurface) return [surfaceKey(routeSessionSurface)];
    if (canvasActive) return panelPrefs.chatPaneLayout.panes.map((pane) => surfaceKey(pane.surface));
    return ["primary"];
  }, [canvasActive, panelPrefs.chatPaneLayout.panes, routeSessionSurface]);
  const sessionTabs = useMemo(
    () =>
      channelId
        ? buildChannelSessionTabItems({
            channelId,
            recentPages,
            currentHref: currentRouteHref,
            activeSurface: activeSessionTabSurface,
            activeSessionId: channel?.active_session_id,
            catalog: channelSessionCatalog,
            hiddenKeys: panelPrefs.hiddenSessionTabKeys,
            orderKeys: panelPrefs.sessionTabOrderKeys,
            unreadStates,
            savedLayouts: panelPrefs.sessionTabLayouts,
            activeLayout: canvasActive ? panelPrefs.chatPaneLayout : null,
          })
        : [],
    [
      activeSessionTabSurface,
      channel?.active_session_id,
      channelId,
      channelSessionCatalog,
      canvasActive,
      currentRouteHref,
      panelPrefs.chatPaneLayout,
      panelPrefs.hiddenSessionTabKeys,
      panelPrefs.sessionTabLayouts,
      panelPrefs.sessionTabOrderKeys,
      recentPages,
      unreadStates,
    ],
  );
  const fileTabs = useMemo<ChannelFileTabItem[]>(
    () => panelPrefs.fileTabPaths.map((path) => ({
      kind: "file",
      key: fileTabKey(path),
      path,
      label: fileTabLabel(path),
      meta: fileTabMeta(path),
      active: activeFile === path,
      primary: false,
      closeable: true,
      unreadCount: 0,
      splitActive: activeFile === path && splitMode,
    })),
    [activeFile, panelPrefs.fileTabPaths, splitMode],
  );
  const topTabs = useMemo<ChannelTopTabItem[]>(() => {
    const tabByKey = new Map<string, ChannelTopTabItem>();
    const visibleSessionTabs = activeFile
      ? sessionTabs.map((tab) => ({ ...tab, active: false }))
      : sessionTabs;
    for (const tab of [...visibleSessionTabs, ...fileTabs]) tabByKey.set(tab.key, tab);
    const tabs: ChannelTopTabItem[] = [];
    const emitted = new Set<string>();
    for (const key of panelPrefs.sessionTabOrderKeys) {
      const tab = tabByKey.get(key);
      if (!tab || emitted.has(key)) continue;
      tabs.push(tab);
      emitted.add(key);
    }
    for (const tab of [...visibleSessionTabs, ...fileTabs]) {
      if (emitted.has(tab.key)) continue;
      tabs.push(tab);
      emitted.add(tab.key);
    }
    return tabs;
  }, [activeFile, fileTabs, panelPrefs.sessionTabOrderKeys, sessionTabs]);
  const activeSessionTabLayoutSnapshot = useMemo(
    () => (canvasActive ? snapshotChannelSessionTabLayout(panelPrefs.chatPaneLayout) : null),
    [canvasActive, panelPrefs.chatPaneLayout],
  );

  useEffect(() => {
    if (!channelId) return;
    if (panelPrefs.sessionTabOrderKeys.includes(activeSessionTabKey)) return;
    patchChannelPanelPrefs(channelId, (current) => (
      current.sessionTabOrderKeys.includes(activeSessionTabKey)
        ? {}
        : { sessionTabOrderKeys: moveTabKeyToFront(current.sessionTabOrderKeys, activeSessionTabKey) }
    ));
  }, [activeSessionTabKey, channelId, panelPrefs.sessionTabOrderKeys, patchChannelPanelPrefs]);
  useEffect(() => {
    if (!channelId || !activeSessionTabLayoutSnapshot) return;
    const nextLayouts = addChannelSessionTabLayout(panelPrefs.sessionTabLayouts, activeSessionTabLayoutSnapshot.layout);
    const currentSerialized = JSON.stringify(panelPrefs.sessionTabLayouts);
    const nextSerialized = JSON.stringify(nextLayouts);
    if (currentSerialized === nextSerialized) return;
    patchChannelPanelPrefs(channelId, (current) => {
      const latestLayouts = addChannelSessionTabLayout(current.sessionTabLayouts, activeSessionTabLayoutSnapshot.layout);
      return { sessionTabLayouts: latestLayouts };
    });
  }, [activeSessionTabLayoutSnapshot, channelId, panelPrefs.sessionTabLayouts, patchChannelPanelPrefs]);

  const unhideSessionTabSurface = useCallback((surface: ChannelSessionSurface) => {
    if (!channelId) return;
    const key = surfaceKey(surface);
    patchChannelPanelPrefs(channelId, (current) => ({
      hiddenSessionTabKeys: current.hiddenSessionTabKeys.filter((hiddenKey) => hiddenKey !== key),
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const promoteSessionTab = useCallback((tab: ChannelTopTabItem) => {
    if (!channelId) return;
    patchChannelPanelPrefs(channelId, (current) => ({
      sessionTabOrderKeys: moveTabKeyToFront(current.sessionTabOrderKeys, tab.key),
      hiddenSessionTabKeys: current.hiddenSessionTabKeys.filter((hiddenKey) => hiddenKey !== tab.key),
    }));
  }, [channelId, patchChannelPanelPrefs]);

  useEffect(() => {
    if (!pendingSessionTabKey) return;
    if (sessionTabs.some((tab) => tab.key === pendingSessionTabKey && tab.active)) {
      setPendingSessionTabKey(null);
    }
  }, [pendingSessionTabKey, sessionTabs]);
  useEffect(() => {
    if (!pendingSessionTabKey) return;
    const timeout = window.setTimeout(() => setPendingSessionTabKey(null), 4000);
    return () => window.clearTimeout(timeout);
  }, [pendingSessionTabKey]);

  const restoreSessionTabLayout = useCallback((layout: ChannelChatPaneLayout, focusedPaneId?: string | null) => {
    if (!channelId) return;
    const focusedLayout = focusedPaneId
      ? { ...layout, focusedPaneId }
      : layout;
    const splitKey = sessionTabKeyForChatPaneLayout(focusedLayout);
    if (splitKey) setPendingSessionTabKey(splitKey);
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: focusedLayout,
      hiddenSessionTabKeys: splitKey
        ? current.hiddenSessionTabKeys.filter((hiddenKey) => hiddenKey !== splitKey)
        : current.hiddenSessionTabKeys,
      sessionTabLayouts: addChannelSessionTabLayout(current.sessionTabLayouts, focusedLayout),
    }));
    navigate(`/channels/${channelId}`);
  }, [channelId, navigate, patchChannelPanelPrefs]);
  const rememberFileTab = useCallback((path: string) => {
    if (!channelId) return;
    const key = fileTabKey(path);
    patchChannelPanelPrefs(channelId, (current) => ({
      fileTabPaths: current.fileTabPaths.includes(path)
        ? current.fileTabPaths
        : [path, ...current.fileTabPaths].slice(0, 20),
      hiddenSessionTabKeys: current.hiddenSessionTabKeys.filter((hiddenKey) => hiddenKey !== key),
      sessionTabOrderKeys: current.sessionTabOrderKeys.includes(key)
        ? current.sessionTabOrderKeys
        : moveTabKeyToFront(current.sessionTabOrderKeys, key),
    }));
  }, [channelId, patchChannelPanelPrefs]);
  const selectFileTabNow = useCallback((path: string, options?: { split?: boolean }) => {
    rememberFileTab(path);
    setActiveFile(path);
    setSplitMode(options?.split ?? false);
    if (channelId && isMobile) setMobileDrawerOpen(channelId, false);
  }, [channelId, isMobile, rememberFileTab, setActiveFile, setMobileDrawerOpen, setSplitMode]);
  const handleSelectSessionTab = useCallback((tab: ChannelTopTabItem) => {
    if (tab.kind === "file") {
      if (activeFile === tab.path) return;
      if (fileDirtyRef.current) {
        setPendingDirtyAction({ type: "select", path: tab.path });
        return;
      }
      selectFileTabNow(tab.path);
      return;
    }
    if (activeFile && fileDirtyRef.current) {
      setPendingDirtyAction({ type: "selectSession", tab });
      return;
    }
    if (activeFile) {
      setActiveFile(null);
      setSplitMode(false);
      fileDirtyRef.current = false;
    }
    if (tab.active) return;
    setPendingSessionTabKey(tab.key);
    if (tab.kind === "split") {
      restoreSessionTabLayout(tab.layout);
      return;
    }
    unhideSessionTabSurface(tab.surface);
    activateChannelSessionSurface(tab.surface, "switch");
  }, [activateChannelSessionSurface, activeFile, restoreSessionTabLayout, selectFileTabNow, setActiveFile, setSplitMode, unhideSessionTabSurface]);
  const handleFocusSplitSessionTabPane = useCallback((tab: ChannelTopTabItem, paneId: string) => {
    if (tab.kind !== "split") return;
    restoreSessionTabLayout(tab.layout, paneId);
  }, [restoreSessionTabLayout]);
  const handleUnsplitSessionTabPane = useCallback((tab: ChannelTopTabItem, paneId: string) => {
    if (tab.kind !== "split") return;
    const pane = tab.layout.panes.find((candidate) => candidate.id === paneId) ?? null;
    if (!pane) return;
    const selectedKey = surfaceKey(pane.surface);
    if (channelId) {
      patchChannelPanelPrefs(channelId, (current) => {
        const orderWithoutSplit = current.sessionTabOrderKeys.filter((key) => key !== tab.key);
        return {
          sessionTabLayouts: removeChannelSessionTabLayout(current.sessionTabLayouts, tab.key),
          sessionTabOrderKeys: moveTabKeyToFront(orderWithoutSplit, selectedKey),
          hiddenSessionTabKeys: current.hiddenSessionTabKeys.filter((key) => key !== tab.key && key !== selectedKey),
        };
      });
    }
    setPendingSessionTabKey(selectedKey);
    activateChannelSessionSurface(pane.surface, "switch");
  }, [activateChannelSessionSurface, channelId, patchChannelPanelPrefs]);
  const predictedSplitTabKey = useCallback((surface: ChannelSessionSurface) => {
    const currentSurface: ChannelSessionSurface = routeSessionSurface ?? { kind: "primary" };
    const currentLayout = panelPrefs.chatPaneLayout;
    const shouldStartSplitFromRoute = !!routeSessionSurface || currentLayout.panes.length <= 1;
    const nextLayout = shouldStartSplitFromRoute
      ? splitChannelChatPaneLayout(currentSurface, surface)
      : addChannelChatPane(currentLayout, surface);
    return sessionTabKeyForChatPaneLayout(nextLayout) ?? surfaceKey(surface);
  }, [panelPrefs.chatPaneLayout, routeSessionSurface]);
  const handleSplitSessionTab = useCallback((tab: ChannelTopTabItem) => {
    if (tab.kind === "file") {
      if (fileDirtyRef.current && activeFile !== tab.path) {
        setPendingDirtyAction({ type: "select", path: tab.path, split: true });
        return;
      }
      selectFileTabNow(tab.path, { split: true });
      return;
    }
    if (tab.kind !== "surface") return;
    const nextKey = predictedSplitTabKey(tab.surface);
    setPendingSessionTabKey(nextKey);
    if (channelId) {
      patchChannelPanelPrefs(channelId, (current) => ({
        sessionTabOrderKeys: moveTabKeyToFront(current.sessionTabOrderKeys, nextKey),
      }));
    }
    unhideSessionTabSurface(tab.surface);
    activateChannelSessionSurface(tab.surface, "split");
  }, [activateChannelSessionSurface, activeFile, channelId, patchChannelPanelPrefs, predictedSplitTabKey, selectFileTabNow, unhideSessionTabSurface]);
  const handleFocusOpenSessionTabSurface = useCallback((tab: ChannelTopTabItem) => {
    if (!channelId || tab.kind !== "surface") return;
    const paneId = paneIdForSurface(tab.surface);
    if (canvasActive && panelPrefs.chatPaneLayout.panes.some((pane) => pane.id === paneId)) {
      focusPane(paneId);
      navigate(`/channels/${channelId}`);
    }
  }, [canvasActive, channelId, focusPane, navigate, panelPrefs.chatPaneLayout.panes]);
  const handleReplaceFocusedSessionTab = useCallback((tab: ChannelTopTabItem) => {
    if (!channelId || tab.kind !== "surface") return;
    unhideSessionTabSurface(tab.surface);
    if (!canvasActive) {
      handleSplitSessionTab(tab);
      return;
    }
    const nextLayout = replaceFocusedChannelChatPane(panelPrefs.chatPaneLayout, tab.surface);
    setPendingSessionTabKey(sessionTabKeyForChatPaneLayout(nextLayout) ?? tab.key);
    patchChannelPanelPrefs(channelId, (current) => ({
      chatPaneLayout: nextLayout,
      hiddenSessionTabKeys: current.hiddenSessionTabKeys.filter((hiddenKey) => hiddenKey !== tab.key),
      sessionTabLayouts: addChannelSessionTabLayout(current.sessionTabLayouts, nextLayout),
    }));
    navigate(`/channels/${channelId}`);
  }, [canvasActive, channelId, handleSplitSessionTab, navigate, panelPrefs.chatPaneLayout, patchChannelPanelPrefs, unhideSessionTabSurface]);
  const handleMakePrimarySessionTab = useCallback((tab: ChannelTopTabItem) => {
    if (tab.kind !== "surface" || tab.surface.kind === "primary") return;
    makePanePrimary({ id: paneIdForSurface(tab.surface), surface: tab.surface });
  }, [makePanePrimary]);
  const sessionIdForTopTab = useCallback((tab: ChannelTopTabItem): string | null => {
    if (tab.kind !== "surface") return null;
    if (tab.surface.kind === "primary") return channel?.active_session_id ?? null;
    return tab.surface.sessionId;
  }, [channel?.active_session_id]);
  const canRenameSessionTab = useCallback((tab: ChannelTopTabItem) => (
    tab.kind === "surface" && !!sessionIdForTopTab(tab)
  ), [sessionIdForTopTab]);
  const handleRenameSessionTab = useCallback((tab: ChannelTopTabItem, title: string) => {
    if (!channelId) return;
    const sessionId = sessionIdForTopTab(tab);
    const trimmed = title.trim();
    if (!sessionId || !trimmed) return;
    renameSession.mutate({
      session_id: sessionId,
      title: trimmed,
      parent_channel_id: channelId,
      bot_id: channel?.bot_id ?? undefined,
    });
  }, [channel?.bot_id, channelId, renameSession, sessionIdForTopTab]);
  const closeFileTabNow = useCallback((path: string) => {
    if (!channelId) return;
    const key = fileTabKey(path);
    const remainingFileTabs = panelPrefs.fileTabPaths.filter((item) => item !== path);
    patchChannelPanelPrefs(channelId, (current) => ({
      fileTabPaths: current.fileTabPaths.filter((item) => item !== path),
      sessionTabOrderKeys: current.sessionTabOrderKeys.filter((item) => item !== key),
    }));
    if (activeFile !== path) return;
    const nextFile = remainingFileTabs[0] ?? null;
    if (nextFile) {
      setActiveFile(nextFile);
      setSplitMode(false);
      return;
    }
    setActiveFile(null);
    setSplitMode(false);
    fileDirtyRef.current = false;
  }, [activeFile, channelId, panelPrefs.fileTabPaths, patchChannelPanelPrefs, setActiveFile, setSplitMode]);
  const handleCloseSessionTab = useCallback((tab: ChannelTopTabItem) => {
    if (!channelId) return;
    if (tab.kind === "file") {
      if (tab.path === activeFile && fileDirtyRef.current) {
        setPendingDirtyAction({ type: "closeFileTab", path: tab.path });
        return;
      }
      closeFileTabNow(tab.path);
      return;
    }
    const nextTab = tab.active ? sessionTabs.find((candidate) => candidate.key !== tab.key) ?? null : null;
    patchChannelPanelPrefs(channelId, (current) => ({
      hiddenSessionTabKeys: Array.from(new Set([...current.hiddenSessionTabKeys, tab.key])).slice(-40),
    }));
    if (nextTab) {
      handleSelectSessionTab(nextTab);
    }
  }, [activeFile, channelId, closeFileTabNow, handleSelectSessionTab, patchChannelPanelPrefs, sessionTabs]);
  const handleReorderSessionTabs = useCallback((dragKey: string, targetKey: string) => {
    if (!channelId || dragKey === targetKey) return;
    patchChannelPanelPrefs(channelId, (current) => {
      const visibleKeys = topTabs.map((tab) => tab.key);
      const base = current.sessionTabOrderKeys.length > 0
        ? current.sessionTabOrderKeys
        : visibleKeys;
      const ordered = [
        ...base.filter((key) => visibleKeys.includes(key)),
        ...visibleKeys.filter((key) => !base.includes(key)),
      ];
      const fromIndex = ordered.indexOf(dragKey);
      const toIndex = ordered.indexOf(targetKey);
      if (fromIndex < 0 || toIndex < 0) return {};
      const nextVisible = [...ordered];
      const [dragged] = nextVisible.splice(fromIndex, 1);
      nextVisible.splice(toIndex, 0, dragged!);
      const next = [
        ...base.filter((key) => !visibleKeys.includes(key)),
        ...nextVisible,
      ];
      for (const key of visibleKeys) {
        if (!next.includes(key)) next.push(key);
      }
      return { sessionTabOrderKeys: next.slice(0, 40) };
    });
  }, [channelId, patchChannelPanelPrefs, topTabs]);
  const handleOverlayActivateSessionSurface = useCallback((surface: ChannelSessionSurface, intent: ChannelSessionActivationIntent) => {
    if (channelId) {
      const key = intent === "split" ? predictedSplitTabKey(surface) : surfaceKey(surface);
      patchChannelPanelPrefs(channelId, (current) => ({
        sessionTabOrderKeys: moveTabKeyToFront(current.sessionTabOrderKeys, key),
      }));
    }
    unhideSessionTabSurface(surface);
    activateChannelSessionSurface(surface, intent);
  }, [activateChannelSessionSurface, channelId, patchChannelPanelPrefs, predictedSplitTabKey, unhideSessionTabSurface]);

  const executeDirtyAction = useCallback((action: DirtyAction) => {
    switch (action.type) {
      case "select":
        selectFileTabNow(action.path, { split: action.split });
        break;
      case "selectSession":
        fileDirtyRef.current = false;
        setActiveFile(null);
        setSplitMode(false);
        handleSelectSessionTab(action.tab);
        break;
      case "close":
        setActiveFile(null);
        setSplitMode(false);
        fileDirtyRef.current = false;
        break;
      case "closeFileTab":
        closeFileTabNow(action.path);
        break;
      case "closePanel":
        if (channelId) {
          if (isMobile) setMobileDrawerOpen(channelId, false);
          else patchChannelPanelPrefs(channelId, { leftOpen: false });
        }
        break;
    }
  }, [channelId, closeFileTabNow, handleSelectSessionTab, isMobile, patchChannelPanelPrefs, selectFileTabNow, setActiveFile, setMobileDrawerOpen, setSplitMode]);

  const handleDirtyChange = useCallback((dirty: boolean) => {
    fileDirtyRef.current = dirty;
  }, []);

  const handleSelectFile = useCallback((path: string, options?: { split?: boolean }) => {
    const resolvedPath = resolveChannelOpenFilePath(path);
    if (resolvedPath === activeFile) {
      if (options?.split && !splitMode) setSplitMode(true);
      return;
    }
    const action: DirtyAction = { type: "select", path: resolvedPath, split: options?.split };
    if (!fileDirtyRef.current) { selectFileTabNow(resolvedPath, { split: options?.split }); return; }
    setPendingDirtyAction(action);
  }, [activeFile, resolveChannelOpenFilePath, selectFileTabNow, setSplitMode, splitMode]);

  useEffect(() => {
    if (!channelId) return;
    const handleChannelFileLink = (event: Event) => {
      const detail = (event as CustomEvent<ChannelFileLinkOpenDetail>).detail;
      if (!detail || detail.channelId !== channelId) return;
      event.preventDefault();
      handleSelectFile(detail.path, { split: detail.split });
    };
    window.addEventListener(CHANNEL_FILE_LINK_OPEN_EVENT, handleChannelFileLink);
    return () => window.removeEventListener(CHANNEL_FILE_LINK_OPEN_EVENT, handleChannelFileLink);
  }, [channelId, handleSelectFile]);

  useEffect(() => {
    if (!channelId) return;
    const intent = readChannelFileIntent(searchParams, channelId);
    if (!intent) return;
    patchChannelPanelPrefs(channelId, {
      leftOpen: true,
      mobileDrawerOpen: true,
      leftTab: "files",
    });
    setRememberedChannelPath(channelId, `/${intent.directoryPath}`);
    if (intent.openFile) {
      handleSelectFile(intent.openFile);
    }
    const next = new URLSearchParams(searchParams);
    next.delete(CHANNEL_FILES_PATH_PARAM);
    next.delete(CHANNEL_OPEN_FILE_PARAM);
    setSearchParams(next, { replace: true });
  }, [
    channelId,
    handleSelectFile,
    patchChannelPanelPrefs,
    searchParams,
    setRememberedChannelPath,
    setSearchParams,
  ]);

  useEffect(() => {
    setActiveFile(null);
    fileDirtyRef.current = false;
    setSplitMode(false);
  }, [channelId, setActiveFile, setSplitMode]);

  const handleCloseFile = useCallback(() => {
    const action: DirtyAction = activeFile
      ? { type: "closeFileTab", path: activeFile }
      : { type: "close" };
    if (!fileDirtyRef.current) { executeDirtyAction(action); return; }
    setPendingDirtyAction(action);
  }, [activeFile, executeDirtyAction]);

  const handleCloseExplorer = useCallback(() => {
    const action: DirtyAction = { type: "closePanel" };
    executeDirtyAction(action);
  }, [executeDirtyAction]);

  const handleMobileBack = useCallback(() => {
    if (activeFile) {
      setActiveFile(null);
    } else if (channelId) {
      setMobileDrawerOpen(channelId, false);
    }
  }, [activeFile, channelId, setActiveFile, setMobileDrawerOpen]);

  const confirmPendingDirtyAction = useCallback(() => {
    if (!pendingDirtyAction) return;
    executeDirtyAction(pendingDirtyAction);
    setPendingDirtyAction(null);
  }, [executeDirtyAction, pendingDirtyAction]);

  const cancelPendingDirtyAction = useCallback(() => {
    setPendingDirtyAction(null);
  }, []);

  return {
    topTabs,
    openSessionTabSurfaceKeys,
    pendingSessionTabKey,
    pendingDirtyAction,
    unhideSessionTabSurface,
    promoteSessionTab,
    handleSelectSessionTab,
    handleFocusSplitSessionTabPane,
    handleCloseSessionTab,
    handleReorderSessionTabs,
    handleSplitSessionTab,
    handleUnsplitSessionTabPane,
    handleFocusOpenSessionTabSurface,
    handleReplaceFocusedSessionTab,
    handleMakePrimarySessionTab,
    canRenameSessionTab,
    handleRenameSessionTab,
    handleOverlayActivateSessionSurface,
    handleDirtyChange,
    handleSelectFile,
    handleCloseFile,
    handleCloseExplorer,
    handleMobileBack,
    confirmPendingDirtyAction,
    cancelPendingDirtyAction,
  };
}
