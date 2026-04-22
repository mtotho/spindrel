import { create } from "zustand";
import { persist } from "zustand/middleware";
import { migrateRecentPage } from "../lib/recentPages";
export const SIDEBAR_MIN_WIDTH = 180;
export const SIDEBAR_MAX_WIDTH = 360;
export const SIDEBAR_DEFAULT_WIDTH = 240;
export const useUIStore = create()(persist((set) => ({
    sidebarCollapsed: false,
    sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
    paletteOpen: false,
    detailPanel: { type: null, id: null },
    hiddenSidebarSections: [],
    fileExplorerOpen: false,
    fileExplorerSplit: false,
    rightDockHidden: false,
    omniPanelTab: "widgets",
    filesFocusTick: 0,
    hudCollapsedChannels: [],
    hudExpandedOnMobile: [],
    recentPages: [],
    toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    setSidebarWidth: (width) => set({
        sidebarWidth: Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, width)),
    }),
    openPalette: () => set({ paletteOpen: true }),
    closePalette: () => set({ paletteOpen: false }),
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
    toggleRightDock: () => set((s) => ({ rightDockHidden: !s.rightDockHidden })),
    setRightDockHidden: (hidden) => set({ rightDockHidden: hidden }),
    setOmniPanelTab: (tab) => set({ omniPanelTab: tab }),
    requestFilesFocus: () => set((s) => ({
        fileExplorerOpen: true,
        omniPanelTab: "files",
        filesFocusTick: s.filesFocusTick + 1,
    })),
    toggleDrawerToWidgets: () => set((s) => {
        if (s.fileExplorerOpen && s.omniPanelTab === "widgets") {
            return { fileExplorerOpen: false };
        }
        return { fileExplorerOpen: true, omniPanelTab: "widgets" };
    }),
    toggleHudCollapsed: (channelId) => set((s) => ({
        hudCollapsedChannels: s.hudCollapsedChannels.includes(channelId)
            ? s.hudCollapsedChannels.filter((id) => id !== channelId)
            : [...s.hudCollapsedChannels, channelId],
    })),
    toggleHudExpandedOnMobile: (channelId) => set((s) => ({
        hudExpandedOnMobile: s.hudExpandedOnMobile.includes(channelId)
            ? s.hudExpandedOnMobile.filter((id) => id !== channelId)
            : [...s.hudExpandedOnMobile, channelId],
    })),
    recordPageVisit: (href) => set((s) => {
        const existing = s.recentPages.find((p) => p.href === href);
        return {
            recentPages: [
                existing ?? { href },
                ...s.recentPages.filter((p) => p.href !== href),
            ].slice(0, 20),
        };
    }),
    enrichRecentPage: (href, label) => set((s) => ({
        recentPages: s.recentPages.map((p) => p.href === href ? { ...p, label } : p),
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
        hudCollapsedChannels: state.hudCollapsedChannels,
        hudExpandedOnMobile: state.hudExpandedOnMobile,
        recentPages: state.recentPages,
    }),
    // Migrate old string[] format to RecentPage[]
    merge: (persisted, current) => ({
        ...current,
        ...persisted,
        recentPages: (persisted?.recentPages ?? []).map((p) => migrateRecentPage((typeof p === "string" ? { href: p } : p))),
    }),
}));
