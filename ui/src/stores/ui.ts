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
  activeWorkspaceId: string | null;
  hiddenSidebarSections: string[];
  toggleSidebar: () => void;
  openMobileSidebar: () => void;
  closeMobileSidebar: () => void;
  openDetail: (type: string, id: string, data?: unknown) => void;
  closeDetail: () => void;
  setActiveWorkspace: (id: string | null) => void;
  toggleSidebarSection: (sectionId: string) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      mobileSidebarOpen: false,
      detailPanel: { type: null, id: null },
      activeWorkspaceId: null,
      hiddenSidebarSections: [],
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
      setActiveWorkspace: (id) => set({ activeWorkspaceId: id }),
      toggleSidebarSection: (sectionId) =>
        set((s) => ({
          hiddenSidebarSections: s.hiddenSidebarSections.includes(sectionId)
            ? s.hiddenSidebarSections.filter((id) => id !== sectionId)
            : [...s.hiddenSidebarSections, sectionId],
        })),
    }),
    {
      name: "spindrel-ui",
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        activeWorkspaceId: state.activeWorkspaceId,
        hiddenSidebarSections: state.hiddenSidebarSections,
      }),
    },
  ),
);
