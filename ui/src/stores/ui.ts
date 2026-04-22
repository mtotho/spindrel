import { create } from "zustand";
import { persist } from "zustand/middleware";
import { migrateRecentPage } from "../lib/recentPages";

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
  /** Channel screen's right-hand widget dock hidden-state. Toggled from the
   *  dock's own header chevron and from the peek-tab on the viewport's
   *  right edge. Persisted globally (not per-channel) to match the left
   *  dock's `fileExplorerOpen` semantics. */
  rightDockHidden: boolean;
  /** OmniPanel active tab. Persisted so the last-used tab sticks across
   *  channel navigation. Default = Widgets (the primary reason to open the
   *  rail). The channel page can flip this to "files" via `requestFilesFocus`
   *  when the user hits ⌘⇧B or clicks the header's browse-files icon. */
  omniPanelTab: "widgets" | "files" | "jump";
  /** Bumped whenever the user explicitly asks to focus the files tree (e.g.
   *  ⌘⇧B or the browse-files header button). The FilesTabPanel listens to
   *  this tick and auto-opens + focuses its filter input. */
  filesFocusTick: number;
  hudCollapsedChannels: string[];
  /** Channels where the user has explicitly opted to expand the HUD on
   *  mobile. On small viewports the HUD defaults to collapsed; this tracks
   *  the per-channel override. Ignored on desktop — desktop uses
   *  `hudCollapsedChannels` exclusively. */
  hudExpandedOnMobile: string[];
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
  toggleRightDock: () => void;
  setRightDockHidden: (hidden: boolean) => void;
  setOmniPanelTab: (tab: "widgets" | "files" | "jump") => void;
  /** Open the OmniPanel, switch to the Files tab, and bump filesFocusTick
   *  so FilesTabPanel auto-focuses its search filter. Composite action so
   *  call sites can invoke one thing from a keyboard shortcut / header
   *  button. */
  requestFilesFocus: () => void;
  /** Mobile channel-header widget button: force-open the drawer on the
   *  Widgets tab. Second click while the drawer is open on Widgets closes
   *  it, so the same button toggles the widget view. Does NOT change the
   *  persisted tab when closing — hamburger still reopens wherever the user
   *  last explicitly navigated. */
  toggleDrawerToWidgets: () => void;
  toggleHudCollapsed: (channelId: string) => void;
  toggleHudExpandedOnMobile: (channelId: string) => void;
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
      rightDockHidden: false,
      omniPanelTab: "widgets",
      filesFocusTick: 0,
      hudCollapsedChannels: [],
      hudExpandedOnMobile: [],
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
      toggleRightDock: () => set((s) => ({ rightDockHidden: !s.rightDockHidden })),
      setRightDockHidden: (hidden) => set({ rightDockHidden: hidden }),
      setOmniPanelTab: (tab) => set({ omniPanelTab: tab }),
      requestFilesFocus: () =>
        set((s) => ({
          fileExplorerOpen: true,
          omniPanelTab: "files",
          filesFocusTick: s.filesFocusTick + 1,
        })),
      toggleDrawerToWidgets: () =>
        set((s) => {
          if (s.fileExplorerOpen && s.omniPanelTab === "widgets") {
            return { fileExplorerOpen: false };
          }
          return { fileExplorerOpen: true, omniPanelTab: "widgets" };
        }),
      toggleHudCollapsed: (channelId) =>
        set((s) => ({
          hudCollapsedChannels: s.hudCollapsedChannels.includes(channelId)
            ? s.hudCollapsedChannels.filter((id) => id !== channelId)
            : [...s.hudCollapsedChannels, channelId],
        })),
      toggleHudExpandedOnMobile: (channelId) =>
        set((s) => ({
          hudExpandedOnMobile: s.hudExpandedOnMobile.includes(channelId)
            ? s.hudExpandedOnMobile.filter((id) => id !== channelId)
            : [...s.hudExpandedOnMobile, channelId],
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
        rightDockHidden: state.rightDockHidden,
        omniPanelTab: state.omniPanelTab,
        hudCollapsedChannels: state.hudCollapsedChannels,
        hudExpandedOnMobile: state.hudExpandedOnMobile,
        recentPages: state.recentPages,
      }),
      // Migrate old string[] format to RecentPage[]
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<UIState>),
        recentPages: ((persisted as Partial<UIState>)?.recentPages ?? []).map(
          (p: unknown) => migrateRecentPage((typeof p === "string" ? { href: p } : p) as RecentPage),
        ),
      }),
    },
  ),
);
