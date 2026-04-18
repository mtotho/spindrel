import { create } from "zustand";
import { persist } from "zustand/middleware";

export type PaneId = "left" | "right";

export interface OpenFile {
  path: string;
  name: string;
  dirty: boolean;
  editContent: string | null; // null = not editing
}

export interface PaneState {
  openFiles: OpenFile[];
  activeFile: string | null; // path of active file
}

// Use plain object instead of Set to avoid SSR serialization issues
type DirMap = Record<string, boolean>;

interface FileBrowserState {
  // Split view
  splitMode: boolean;
  splitRatio: number; // 0-1, left pane proportion

  // Panes
  leftPane: PaneState;
  rightPane: PaneState;

  // Tree
  treeVisible: boolean;
  expandedDirs: DirMap;
  treeWidth: number;

  // Channel file explorer (chat sidebar)
  channelExplorerWidth: number;
  // Per-channel remembered last-visited path inside the channel explorer.
  // In-memory only (intentionally not persisted) — resets on reload.
  channelExplorerPaths: Record<string, string>;
  setChannelExplorerPath: (channelId: string, path: string) => void;

  // Actions — split
  toggleSplit: () => void;
  setSplitRatio: (ratio: number) => void;

  // Actions — tree
  toggleTree: () => void;
  showTree: () => void;
  hideTree: () => void;
  toggleDir: (path: string) => void;
  expandDir: (path: string) => void;
  collapseDir: (path: string) => void;
  setTreeWidth: (width: number) => void;
  setChannelExplorerWidth: (width: number) => void;

  // Actions — files
  openFile: (path: string, name: string, pane?: PaneId) => void;
  closeFile: (path: string, pane: PaneId) => void;
  setActiveFile: (path: string, pane: PaneId) => void;
  startEdit: (path: string, pane: PaneId, content: string) => void;
  updateEdit: (path: string, pane: PaneId, content: string) => void;
  cancelEdit: (path: string, pane: PaneId) => void;
  markClean: (path: string, pane: PaneId) => void;

  // Reset
  reset: () => void;
}

const emptyPane: PaneState = { openFiles: [], activeFile: null };

function updatePaneFile(
  pane: PaneState,
  path: string,
  updater: (f: OpenFile) => OpenFile
): PaneState {
  return {
    ...pane,
    openFiles: pane.openFiles.map((f) => (f.path === path ? updater(f) : f)),
  };
}

export const useFileBrowserStore = create<FileBrowserState>()(
  persist(
    (set, get) => ({
  splitMode: false,
  splitRatio: 0.5,
  leftPane: { ...emptyPane },
  rightPane: { ...emptyPane },
  treeVisible: true,
  expandedDirs: {} as DirMap,
  treeWidth: 220,
  channelExplorerWidth: 300,
  channelExplorerPaths: {},

  setChannelExplorerPath: (channelId, path) =>
    set((s) => ({ channelExplorerPaths: { ...s.channelExplorerPaths, [channelId]: path } })),

  toggleTree: () => set((s) => ({ treeVisible: !s.treeVisible })),
  showTree: () => set({ treeVisible: true }),
  hideTree: () => set({ treeVisible: false }),

  toggleSplit: () =>
    set((s) => {
      if (s.splitMode) {
        // Closing split — move right pane files to left
        const merged = [...s.leftPane.openFiles];
        for (const f of s.rightPane.openFiles) {
          if (!merged.some((m) => m.path === f.path)) merged.push(f);
        }
        return {
          splitMode: false,
          leftPane: {
            openFiles: merged,
            activeFile: s.leftPane.activeFile ?? s.rightPane.activeFile,
          },
          rightPane: { ...emptyPane },
        };
      }
      return { splitMode: true };
    }),

  setSplitRatio: (ratio) => set({ splitRatio: Math.max(0.2, Math.min(0.8, ratio)) }),

  toggleDir: (path) =>
    set((s) => {
      const next = { ...s.expandedDirs };
      if (next[path]) delete next[path];
      else next[path] = true;
      return { expandedDirs: next };
    }),

  expandDir: (path) =>
    set((s) => {
      if (s.expandedDirs[path]) return s;
      return { expandedDirs: { ...s.expandedDirs, [path]: true } };
    }),

  collapseDir: (path) =>
    set((s) => {
      if (!s.expandedDirs[path]) return s;
      const next = { ...s.expandedDirs };
      delete next[path];
      return { expandedDirs: next };
    }),

  setTreeWidth: (width) => set({ treeWidth: Math.max(140, Math.min(500, width)) }),
  setChannelExplorerWidth: (width) => set({ channelExplorerWidth: Math.max(200, Math.min(600, width)) }),

  openFile: (path, name, pane = "left") =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      const current = s[key];
      const exists = current.openFiles.some((f) => f.path === path);
      if (exists) {
        return { [key]: { ...current, activeFile: path } };
      }
      return {
        [key]: {
          openFiles: [...current.openFiles, { path, name, dirty: false, editContent: null }],
          activeFile: path,
        },
      };
    }),

  closeFile: (path, pane) =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      const current = s[key];
      const filtered = current.openFiles.filter((f) => f.path !== path);
      let activeFile = current.activeFile;
      if (activeFile === path) {
        activeFile = filtered.length > 0 ? filtered[filtered.length - 1].path : null;
      }
      // Auto-close split if right pane becomes empty
      if (pane === "right" && filtered.length === 0) {
        return { splitMode: false, [key]: { openFiles: [], activeFile: null } };
      }
      return { [key]: { openFiles: filtered, activeFile } };
    }),

  setActiveFile: (path, pane) =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      return { [key]: { ...s[key], activeFile: path } };
    }),

  startEdit: (path, pane, content) =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      return { [key]: updatePaneFile(s[key], path, (f) => ({ ...f, editContent: content, dirty: false })) };
    }),

  updateEdit: (path, pane, content) =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      return { [key]: updatePaneFile(s[key], path, (f) => ({ ...f, editContent: content, dirty: true })) };
    }),

  cancelEdit: (path, pane) =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      return { [key]: updatePaneFile(s[key], path, (f) => ({ ...f, editContent: null, dirty: false })) };
    }),

  markClean: (path, pane) =>
    set((s) => {
      const key = pane === "left" ? "leftPane" : "rightPane";
      return { [key]: updatePaneFile(s[key], path, (f) => ({ ...f, dirty: false, editContent: null })) };
    }),

  reset: () =>
    set({
      splitMode: false,
      splitRatio: 0.5,
      leftPane: { ...emptyPane },
      rightPane: { ...emptyPane },
      treeVisible: true,
      expandedDirs: {} as DirMap,
      treeWidth: 220,
      channelExplorerWidth: 300,
      channelExplorerPaths: {},
    }),
    }),
    {
      name: "spindrel-file-browser",
      partialize: (s) => ({
        channelExplorerWidth: s.channelExplorerWidth,
        splitMode: s.splitMode,
        splitRatio: s.splitRatio,
        treeWidth: s.treeWidth,
        treeVisible: s.treeVisible,
      }),
    },
  ),
);
