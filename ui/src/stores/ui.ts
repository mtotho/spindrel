import { create } from "zustand";
import { persist } from "zustand/middleware";
import { migrateRecentPage } from "../lib/recentPages";
import { canonicalizePaletteHref, resolvePaletteRoute } from "../lib/paletteRoutes";
import {
  CHANNEL_PANEL_DEFAULT_WIDTH,
  clampChannelPanelWidth,
} from "../lib/channelPanelLayout";

interface DetailPanelState {
  type: string | null;
  id: string | null;
  data?: unknown;
}

export interface RecentPage {
  href: string;
  label?: string;
  hint?: string;
  iconKey?: string;
  category?: string;
  routeKind?: string;
  pageType?: string;
  contextLabel?: string;
  version?: number;
}

export type OmniPanelTab = "widgets" | "files" | "jump";

export interface ChannelPanelPrefs {
  leftOpen: boolean;
  rightOpen: boolean;
  leftPinned: boolean;
  rightPinned: boolean;
  leftWidth: number;
  rightWidth: number;
  leftTab: OmniPanelTab;
  mobileDrawerOpen: boolean;
  mobileExpandedWidgetId: string | null;
  focusModePrior: {
    leftOpen: boolean;
    rightOpen: boolean;
  } | null;
}

export type ChannelPanelPrefsPatch =
  Partial<ChannelPanelPrefs>
  | ((current: ChannelPanelPrefs) => Partial<ChannelPanelPrefs>);

export function defaultChannelPanelPrefs(): ChannelPanelPrefs {
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
  };
}

function normalizeChannelPanelPrefs(
  prefs: Partial<ChannelPanelPrefs> | undefined,
): ChannelPanelPrefs {
  const base = defaultChannelPanelPrefs();
  return {
    ...base,
    ...(prefs ?? {}),
    leftWidth: clampChannelPanelWidth(prefs?.leftWidth ?? base.leftWidth),
    rightWidth: clampChannelPanelWidth(prefs?.rightWidth ?? base.rightWidth),
    leftTab: prefs?.leftTab ?? base.leftTab,
    mobileExpandedWidgetId: prefs?.mobileExpandedWidgetId ?? null,
    focusModePrior: prefs?.focusModePrior ?? null,
  };
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
  omniPanelTab: OmniPanelTab;
  /** Per-channel runtime panel preferences. Dashboard pin placement remains
   *  canonical; these values only control chat-screen visibility/chrome. */
  channelPanelPrefs: Record<string, ChannelPanelPrefs>;
  /** Bumped whenever the user explicitly asks to focus the files tree (e.g.
   *  ⌘⇧B or the browse-files header button). The FilesTabPanel listens to
   *  this tick and auto-opens + focuses its filter input. */
  filesFocusTick: number;
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
  setFileExplorerSplit: (split: boolean) => void;
  toggleRightDock: () => void;
  setRightDockHidden: (hidden: boolean) => void;
  setOmniPanelTab: (tab: OmniPanelTab) => void;
  ensureChannelPanelPrefs: (channelId: string, defaults?: Partial<ChannelPanelPrefs>) => void;
  patchChannelPanelPrefs: (channelId: string, patch: ChannelPanelPrefsPatch) => void;
  setChannelPanelTab: (channelId: string, tab: OmniPanelTab) => void;
  setMobileDrawerOpen: (channelId: string, open: boolean) => void;
  toggleMobileDrawerToWidgets: (channelId: string) => void;
  setMobileExpandedWidget: (channelId: string, widgetId: string | null) => void;
  /** Open the OmniPanel, switch to the Files tab, and bump filesFocusTick
   *  so FilesTabPanel auto-focuses its search filter. Composite action so
   *  call sites can invoke one thing from a keyboard shortcut / header
   *  button. */
  requestFilesFocus: () => void;
  requestChannelFilesFocus: (channelId: string) => void;
  /** Mobile channel-header widget button: force-open the drawer on the
   *  Widgets tab. Second click while the drawer is open on Widgets closes
   *  it, so the same button toggles the widget view. Does NOT change the
   *  persisted tab when closing — hamburger still reopens wherever the user
   *  last explicitly navigated. */
  toggleDrawerToWidgets: () => void;
  recordPageVisit: (href: string) => void;
  enrichRecentPage: (href: string, patch: string | Partial<RecentPage>) => void;
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
      channelPanelPrefs: {},
      filesFocusTick: 0,
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
      setFileExplorerSplit: (split) => set({ fileExplorerSplit: split }),
      toggleRightDock: () => set((s) => ({ rightDockHidden: !s.rightDockHidden })),
      setRightDockHidden: (hidden) => set({ rightDockHidden: hidden }),
      setOmniPanelTab: (tab) => set({ omniPanelTab: tab }),
      ensureChannelPanelPrefs: (channelId, defaults) =>
        set((s) => {
          if (s.channelPanelPrefs[channelId]) return s;
          return {
            channelPanelPrefs: {
              ...s.channelPanelPrefs,
              [channelId]: normalizeChannelPanelPrefs(defaults),
            },
          };
        }),
      patchChannelPanelPrefs: (channelId, patch) =>
        set((s) => {
          const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
          const patchValue = typeof patch === "function" ? patch(current) : patch;
          return {
            channelPanelPrefs: {
              ...s.channelPanelPrefs,
              [channelId]: normalizeChannelPanelPrefs({ ...current, ...patchValue }),
            },
          };
        }),
      setChannelPanelTab: (channelId, tab) =>
        set((s) => {
          const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
          return {
            channelPanelPrefs: {
              ...s.channelPanelPrefs,
              [channelId]: { ...current, leftTab: tab },
            },
          };
        }),
      setMobileDrawerOpen: (channelId, open) =>
        set((s) => {
          const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
          return {
            channelPanelPrefs: {
              ...s.channelPanelPrefs,
              [channelId]: { ...current, mobileDrawerOpen: open },
            },
          };
        }),
      toggleMobileDrawerToWidgets: (channelId) =>
        set((s) => {
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
      setMobileExpandedWidget: (channelId, widgetId) =>
        set((s) => {
          const current = normalizeChannelPanelPrefs(s.channelPanelPrefs[channelId]);
          return {
            channelPanelPrefs: {
              ...s.channelPanelPrefs,
              [channelId]: { ...current, mobileExpandedWidgetId: widgetId },
            },
          };
        }),
      requestFilesFocus: () =>
        set((s) => ({
          fileExplorerOpen: true,
          omniPanelTab: "files",
          filesFocusTick: s.filesFocusTick + 1,
        })),
      requestChannelFilesFocus: (channelId) =>
        set((s) => {
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
      toggleDrawerToWidgets: () =>
        set((s) => {
          if (s.fileExplorerOpen && s.omniPanelTab === "widgets") {
            return { fileExplorerOpen: false };
          }
          return { fileExplorerOpen: true, omniPanelTab: "widgets" };
        }),
      recordPageVisit: (href) =>
        set((s) => {
          const canonicalHref = canonicalizePaletteHref(href);
          const route = resolvePaletteRoute(canonicalHref);
          if (route && !route.recordable) return s;
          const base: RecentPage = {
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
      enrichRecentPage: (href, patch) =>
        set((s) => ({
          recentPages: s.recentPages.map((p) =>
            p.href === canonicalizePaletteHref(href)
              ? {
                  ...p,
                  ...(typeof patch === "string" ? { label: patch } : patch),
                  version: 2,
                }
              : p,
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
        channelPanelPrefs: state.channelPanelPrefs,
        recentPages: state.recentPages,
      }),
      // Migrate old string[] format to RecentPage[]
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<UIState>),
        channelPanelPrefs: Object.fromEntries(
          Object.entries((persisted as Partial<UIState>)?.channelPanelPrefs ?? {}).map(
            ([channelId, prefs]) => [channelId, normalizeChannelPanelPrefs(prefs as Partial<ChannelPanelPrefs>)],
          ),
        ),
        recentPages: ((persisted as Partial<UIState>)?.recentPages ?? []).map(
          (p: unknown) => migrateRecentPage((typeof p === "string" ? { href: p } : p) as RecentPage),
        ),
      }),
    },
  ),
);
