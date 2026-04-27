import { create } from "zustand";
import { persist } from "zustand/middleware";
import { migrateRecentPage } from "../lib/recentPages";
import { canonicalizePaletteHref, resolvePaletteRoute } from "../lib/paletteRoutes";
import { CHANNEL_PANEL_DEFAULT_WIDTH, clampChannelPanelWidth, } from "../lib/channelPanelLayout";
import { defaultChannelChatPaneLayout, normalizeChannelChatPaneLayout, normalizeChannelSessionPanels, } from "../lib/channelSessionSurfaces";
export function defaultChannelPanelPrefs() {
    return {
        leftOpen: false,
        rightOpen: true,
        leftPinned: false,
        rightPinned: false,
        leftWidth: CHANNEL_PANEL_DEFAULT_WIDTH,
        rightWidth: CHANNEL_PANEL_DEFAULT_WIDTH,
        leftTab: "widgets",
        mobileDrawerOpen: false,
        mobileExpandedWidgetId: null,
        focusModePrior: null,
        sessionPanels: [],
        chatPaneLayout: defaultChannelChatPaneLayout(),
        topChromeCollapsed: false,
        collapseHintDismissed: false,
    };
}
function normalizeChannelPanelPrefs(prefs) {
    const base = defaultChannelPanelPrefs();
    const rawFocusPrior = prefs?.focusModePrior;
    const focusModePrior = rawFocusPrior
        ? {
            leftOpen: !!rawFocusPrior.leftOpen,
            rightOpen: !!rawFocusPrior.rightOpen,
            topChromeCollapsed: "topChromeCollapsed" in rawFocusPrior
                ? !!rawFocusPrior.topChromeCollapsed
                : base.topChromeCollapsed,
        }
        : null;
    return {
        ...base,
        ...(prefs ?? {}),
        leftWidth: clampChannelPanelWidth(prefs?.leftWidth ?? base.leftWidth),
        rightWidth: clampChannelPanelWidth(prefs?.rightWidth ?? base.rightWidth),
        leftTab: prefs?.leftTab ?? base.leftTab,
        mobileExpandedWidgetId: prefs?.mobileExpandedWidgetId ?? null,
        focusModePrior,
        sessionPanels: normalizeChannelSessionPanels(prefs?.sessionPanels),
        chatPaneLayout: normalizeChannelChatPaneLayout(prefs?.chatPaneLayout, prefs?.sessionPanels),
        topChromeCollapsed: prefs?.topChromeCollapsed ?? base.topChromeCollapsed,
        collapseHintDismissed: prefs?.collapseHintDismissed ?? base.collapseHintDismissed,
    };
}
export const SIDEBAR_MIN_WIDTH = 180;
export const SIDEBAR_MAX_WIDTH = 360;
export const SIDEBAR_DEFAULT_WIDTH = 240;
export const useUIStore = create()(persist((set) => ({
    sidebarCollapsed: false,
    sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
    paletteOpen: false,
    attentionHubOpen: false,
    spatialOverlayOpen: false,
    detailPanel: { type: null, id: null },
    hiddenSidebarSections: [],
    fileExplorerOpen: false,
    fileExplorerSplit: false,
    rightDockHidden: false,
    omniPanelTab: "widgets",
    channelPanelPrefs: {},
    filesFocusTick: 0,
    recentPages: [],
    toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    setSidebarWidth: (width) => set({
        sidebarWidth: Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, width)),
    }),
    openPalette: () => set({ paletteOpen: true }),
    closePalette: () => set({ paletteOpen: false }),
    openAttentionHub: () => set({ attentionHubOpen: true }),
    closeAttentionHub: () => set({ attentionHubOpen: false }),
    openSpatialOverlay: () => set({ spatialOverlayOpen: true }),
    closeSpatialOverlay: () => set({ spatialOverlayOpen: false }),
    toggleSpatialOverlay: () => set((s) => ({ spatialOverlayOpen: !s.spatialOverlayOpen })),
    openMobileSidebar: () => set({ paletteOpen: true }),
    closeMobileSidebar: () => set({ paletteOpen: false }),
    openDetail: (type, id, data) => set({ detailPanel: { type, id, data } }),
    closeDetail: () => set({ detailPanel: { type: null, id: null } }),
    toggleSidebarSection: (sectionId) => set((s) => ({
        hiddenSidebarSections: s.hiddenSidebarSections.includes(sectionId)
            ? s.hiddenSidebarSections.filter((id) => id !== sectionId)
            : [...s.hiddenSidebarSections, sectionId],
    })),
    toggleFileExplorer: () => set((s) => ({ fileExplorerOpen: !s.fileExplorerOpen })),
    setFileExplorerOpen: (open) => set({ fileExplorerOpen: open }),
    toggleFileExplorerSplit: () => set((s) => ({ fileExplorerSplit: !s.fileExplorerSplit })),
    setFileExplorerSplit: (split) => set({ fileExplorerSplit: split }),
    toggleRightDock: () => set((s) => ({ rightDockHidden: !s.rightDockHidden })),
    setRightDockHidden: (hidden) => set({ rightDockHidden: hidden }),
    setOmniPanelTab: (tab) => set({ omniPanelTab: tab }),
    ensureChannelPanelPrefs: (channelId, defaults) => set((s) => {
        if (s.channelPanelPrefs[channelId])
            return s;
        return {
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: normalizeChannelPanelPrefs(defaults),
            },
        };
    }),
    patchChannelPanelPrefs: (channelId, patch) => set((s) => {
        const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
        const patchValue = typeof patch === "function" ? patch(current) : patch;
        return {
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: normalizeChannelPanelPrefs({ ...current, ...patchValue }),
            },
        };
    }),
    setChannelPanelTab: (channelId, tab) => set((s) => {
        const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
        return {
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: { ...current, leftTab: tab },
            },
        };
    }),
    setMobileDrawerOpen: (channelId, open) => set((s) => {
        const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
        return {
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: { ...current, mobileDrawerOpen: open },
            },
        };
    }),
    toggleMobileDrawerToWidgets: (channelId) => set((s) => {
        const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
        return {
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: {
                    ...current,
                    mobileDrawerOpen: current.mobileDrawerOpen && current.leftTab === "widgets" ? false : true,
                    leftTab: "widgets",
                },
            },
        };
    }),
    setMobileExpandedWidget: (channelId, widgetId) => set((s) => {
        const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
        return {
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: { ...current, mobileExpandedWidgetId: widgetId },
            },
        };
    }),
    requestFilesFocus: () => set((s) => ({
        fileExplorerOpen: true,
        omniPanelTab: "files",
        filesFocusTick: s.filesFocusTick + 1,
    })),
    requestChannelFilesFocus: (channelId) => set((s) => {
        const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
        return {
            filesFocusTick: s.filesFocusTick + 1,
            channelPanelPrefs: {
                ...s.channelPanelPrefs,
                [channelId]: {
                    ...current,
                    leftOpen: true,
                    mobileDrawerOpen: true,
                    leftTab: "files",
                },
            },
        };
    }),
    toggleDrawerToWidgets: () => set((s) => {
        if (s.fileExplorerOpen && s.omniPanelTab === "widgets") {
            return { fileExplorerOpen: false };
        }
        return { fileExplorerOpen: true, omniPanelTab: "widgets" };
    }),
    recordPageVisit: (href) => set((s) => {
        const canonicalHref = canonicalizePaletteHref(href);
        const route = resolvePaletteRoute(canonicalHref);
        if (route && !route.recordable)
            return s;
        const base = {
            href: canonicalHref,
            hint: route?.hint,
            category: route?.category,
            routeKind: route?.routeKind,
            pageType: route?.pageType,
            version: 2,
        };
        const existing = s.recentPages.find((p) => p.href === canonicalHref);
        return {
            recentPages: [
                { ...base, ...existing },
                ...s.recentPages.filter((p) => p.href !== canonicalHref),
            ].slice(0, 20),
        };
    }),
    enrichRecentPage: (href, patch) => set((s) => ({
        recentPages: s.recentPages.map((p) => p.href === canonicalizePaletteHref(href)
            ? {
                ...p,
                ...(typeof patch === "string" ? { label: patch } : patch),
                version: 2,
            }
            : p),
    })),
}), {
    name: "spindrel-ui",
    partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        sidebarWidth: state.sidebarWidth,
        hiddenSidebarSections: state.hiddenSidebarSections,
        fileExplorerOpen: state.fileExplorerOpen,
        fileExplorerSplit: state.fileExplorerSplit,
        rightDockHidden: state.rightDockHidden,
        omniPanelTab: state.omniPanelTab,
        channelPanelPrefs: state.channelPanelPrefs,
        recentPages: state.recentPages,
    }),
    // Migrate old string[] format to RecentPage[]
    merge: (persisted, current) => ({
        ...current,
        ...persisted,
        channelPanelPrefs: Object.fromEntries(Object.entries(persisted?.channelPanelPrefs ?? {}).map(([channelId, prefs]) => [channelId, normalizeChannelPanelPrefs(prefs)])),
        recentPages: (persisted?.recentPages ?? []).map((p) => migrateRecentPage((typeof p === "string" ? { href: p } : p))),
    }),
}));
