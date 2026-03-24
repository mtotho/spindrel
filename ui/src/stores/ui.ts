import { create } from "zustand";

interface DetailPanelState {
  type: string | null;
  id: string | null;
  data?: unknown;
}

interface UIState {
  sidebarCollapsed: boolean;
  mobileSidebarOpen: boolean;
  detailPanel: DetailPanelState;
  toggleSidebar: () => void;
  openMobileSidebar: () => void;
  closeMobileSidebar: () => void;
  openDetail: (type: string, id: string, data?: unknown) => void;
  closeDetail: () => void;
}

export const useUIStore = create<UIState>()((set) => ({
  sidebarCollapsed: false,
  mobileSidebarOpen: false,
  detailPanel: { type: null, id: null },
  toggleSidebar: () =>
    set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  openMobileSidebar: () => set({ mobileSidebarOpen: true }),
  closeMobileSidebar: () => set({ mobileSidebarOpen: false }),
  openDetail: (type, id, data) =>
    set({ detailPanel: { type, id, data } }),
  closeDetail: () => set({ detailPanel: { type: null, id: null } }),
}));
