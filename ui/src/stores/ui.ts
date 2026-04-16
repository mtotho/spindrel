import { create } from "zustand";
import { persist } from "zustand/middleware";

interface DetailPanelState {
  type: string | null;
  id: string | null;
  data?: unknown;
}

interface UIState {
  sidebarCollapsed: boolean;
  mobileSidebarOpen: boolean;
  detailPanel: DetailPanelState;
  hiddenSidebarSections: string[];
  fileExplorerOpen: boolean;
  fileExplorerSplit: boolean;
  hudCollapsedChannels: string[];
  recentPages: string[];
  toggleSidebar: () => void;
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
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mobileSidebarOpen: false,
      detailPanel: { type: null, id: null },
      hiddenSidebarSections: [],
      fileExplorerOpen: false,
      fileExplorerSplit: false,
      hudCollapsedChannels: [],
      recentPages: [],
      toggleSidebar: () =>
        set((s) => ({
          sidebarCollapsed: !s.sidebarCollapsed,
          // Collapsing on mobile should dismiss the overlay
          ...(!s.sidebarCollapsed ? { mobileSidebarOpen: false } : {}),
        })),
      openMobileSidebar: () => set({ mobileSidebarOpen: true, sidebarCollapsed: false }),
      closeMobileSidebar: () => set({ mobileSidebarOpen: false }),
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
        set((s) => ({
          recentPages: [href, ...s.recentPages.filter((h) => h !== href)].slice(0, 10),
        })),
    }),
    {
      name: "spindrel-ui",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        hiddenSidebarSections: state.hiddenSidebarSections,
        fileExplorerOpen: state.fileExplorerOpen,
        fileExplorerSplit: state.fileExplorerSplit,
        hudCollapsedChannels: state.hudCollapsedChannels,
        recentPages: state.recentPages,
      }),
    },
  ),
);
