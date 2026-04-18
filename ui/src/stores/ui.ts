import { create } from "zustand";
import { persist } from "zustand/middleware";

interface DetailPanelState {
  type: string | null;
  id: string | null;
  data?: unknown;
}

export interface RecentPage {
  href: string;
  label?: string;
  iconKey?: string;
  category?: string;
}

export const SIDEBAR_MIN_WIDTH = 180;
export const SIDEBAR_MAX_WIDTH = 360;
export const SIDEBAR_DEFAULT_WIDTH = 240;

interface UIState {
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  paletteOpen: boolean;
  detailPanel: DetailPanelState;
  hiddenSidebarSections: string[];
  fileExplorerOpen: boolean;
  fileExplorerSplit: boolean;
  hudCollapsedChannels: string[];
  recentPages: RecentPage[];
  toggleSidebar: () => void;
  setSidebarWidth: (width: number) => void;
  openPalette: () => void;
  closePalette: () => void;
  // Legacy aliases — palette replaces the mobile drawer, so these now drive
  // the palette. Kept so existing callers (channel list, footer profile link,
  // page header) keep auto-closing the palette on navigation.
  openMobileSidebar: () => void;
  closeMobileSidebar: () => void;
  openDetail: (type: string, id: string, data?: unknown) => void;
  closeDetail: () => void;
  toggleSidebarSection: (sectionId: string) => void;
  toggleFileExplorer: () => void;
  setFileExplorerOpen: (open: boolean) => void;
  toggleFileExplorerSplit: () => void;
  toggleHudCollapsed: (channelId: string) => void;
  recordPageVisit: (href: string) => void;
  enrichRecentPage: (href: string, label: string) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      sidebarWidth: SIDEBAR_DEFAULT_WIDTH,
      paletteOpen: false,
      detailPanel: { type: null, id: null },
      hiddenSidebarSections: [],
      fileExplorerOpen: false,
      fileExplorerSplit: false,
      hudCollapsedChannels: [],
      recentPages: [],
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarWidth: (width) =>
        set({
          sidebarWidth: Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, width)),
        }),
      openPalette: () => set({ paletteOpen: true }),
      closePalette: () => set({ paletteOpen: false }),
      openMobileSidebar: () => set({ paletteOpen: true }),
      closeMobileSidebar: () => set({ paletteOpen: false }),
      openDetail: (type, id, data) =>
        set({ detailPanel: { type, id, data } }),
      closeDetail: () => set({ detailPanel: { type: null, id: null } }),
      toggleSidebarSection: (sectionId) =>
        set((s) => ({
          hiddenSidebarSections: s.hiddenSidebarSections.includes(sectionId)
            ? s.hiddenSidebarSections.filter((id) => id !== sectionId)
            : [...s.hiddenSidebarSections, sectionId],
        })),
      toggleFileExplorer: () => set((s) => ({ fileExplorerOpen: !s.fileExplorerOpen })),
      setFileExplorerOpen: (open) => set({ fileExplorerOpen: open }),
      toggleFileExplorerSplit: () => set((s) => ({ fileExplorerSplit: !s.fileExplorerSplit })),
      toggleHudCollapsed: (channelId) =>
        set((s) => ({
          hudCollapsedChannels: s.hudCollapsedChannels.includes(channelId)
            ? s.hudCollapsedChannels.filter((id) => id !== channelId)
            : [...s.hudCollapsedChannels, channelId],
        })),
      recordPageVisit: (href) =>
        set((s) => {
          const existing = s.recentPages.find((p) => p.href === href);
          return {
            recentPages: [
              existing ?? { href },
              ...s.recentPages.filter((p) => p.href !== href),
            ].slice(0, 20),
          };
        }),
      enrichRecentPage: (href, label) =>
        set((s) => ({
          recentPages: s.recentPages.map((p) =>
            p.href === href ? { ...p, label } : p,
          ),
        })),
    }),
    {
      name: "spindrel-ui",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        sidebarWidth: state.sidebarWidth,
        hiddenSidebarSections: state.hiddenSidebarSections,
        fileExplorerOpen: state.fileExplorerOpen,
        fileExplorerSplit: state.fileExplorerSplit,
        hudCollapsedChannels: state.hudCollapsedChannels,
        recentPages: state.recentPages,
      }),
      // Migrate old string[] format to RecentPage[]
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<UIState>),
        recentPages: ((persisted as Partial<UIState>)?.recentPages ?? []).map(
          (p: unknown) => (typeof p === "string" ? { href: p } : p) as RecentPage,
        ),
      }),
    },
  ),
);
