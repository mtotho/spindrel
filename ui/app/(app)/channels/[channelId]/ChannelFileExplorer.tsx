import { Spinner } from "@/src/components/shared/Spinner";
/**
 * ChannelFileExplorer — unified left-panel explorer for a channel.
 *
 * Two surfaces stacked:
 *
 *   ┌─ EXPLORER ─────────── ⊕ 📁 ⨯ ┐
 *   │ ╭─ IN CONTEXT ── ~5.5k tok ──╮ │  ← pinned active card (channel API)
 *   │ │ token bar                   │ │     • only when channel workspace
 *   │ │ active file rows            │ │     • subtle accent left border
 *   │ │ ⊕ Add active file           │ │       so it reads as a "live console"
 *   │ ╰─────────────────────────────╯ │
 *   │  Channel  Memory  Workspace      │  ← scope strip (quick jumps)
 *   │  🔍 Filter…                       │
 *   │  /ws › channels › 6edf850e        │  ← clickable breadcrumb
 *   │  📁 archive               (3)    │  ← directory tree (workspace API)
 *   │  📁 data                  (8)    │
 *   │  📄 README.md      12K · 3d      │
 *   └──────────────────────────────────┘
 *
 * The IN CONTEXT card is the only "synthetic view" — it pins the channel's
 * active files (those injected into context every turn) regardless of where
 * you've navigated to in the tree. The tree itself is a real, navigable
 * filesystem view of the bot's full workspace, so you can jump between the
 * channel's working files and the bot's memory in two clicks.
 *
 * Visual subcomponents (InContextCard, ScopeStrip, Breadcrumb, tree rows,
 * NewItemRow) live in ChannelFileExplorerParts.tsx to keep this file under
 * the project's 1000-line split rule.
 */
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { X, Plus, FolderPlus, Search, Upload, RefreshCw, ChevronDown } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import {
  useChannel,
  useChannels,
  useDeleteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
  type ChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import { apiFetch } from "@/src/api/client";
import {
  useWorkspaceFiles,
  useWriteWorkspaceFile,
  useMkdirWorkspace,
  useDeleteWorkspaceFile,
  useMoveWorkspaceFile,
  useUploadWorkspaceFile,
} from "@/src/api/hooks/useWorkspaces";
import { useBot } from "@/src/api/hooks/useBots";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import {
  ContextMenu,
  type ContextMenuItem,
} from "./ChannelFileExplorerData";
import {
  InContextCard,
  ScopeStrip,
  Breadcrumb,
  TreeFolderRow,
  TreeFileRow,
  NewItemRow,
  stripSlashes,
} from "./ChannelFileExplorerParts";

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/** Join path parts with `/`, normalize duplicate slashes. */
function joinPath(...parts: string[]): string {
  return parts
    .map((p) => stripSlashes(p))
    .filter(Boolean)
    .join("/");
}

/** Convert a directory path used by the explorer to the value the workspace API expects. */
function dirForApi(p: string): string {
  // Workspace `/files?path=` accepts `/`-prefixed dir paths.
  if (!p || p === "/") return "/";
  return p.startsWith("/") ? p : `/${p}`;
}

/** Memory path for a bot — depends on whether it lives in a shared workspace. */
function getMemoryPath(botId: string, sharedWorkspace: boolean): string {
  return sharedWorkspace ? `/bots/${botId}/memory` : "/memory";
}

/** Pick a sensible initial directory for a freshly-opened channel. */
function pickInitialPath(opts: {
  channelId: string;
  channelWorkspaceEnabled: boolean;
  botId: string | undefined;
  sharedWorkspace: boolean;
  remembered: string | undefined;
}): string {
  if (opts.remembered) return opts.remembered;
  if (opts.channelWorkspaceEnabled) return `/channels/${opts.channelId}`;
  if (opts.botId) return getMemoryPath(opts.botId, opts.sharedWorkspace);
  return "/";
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface ChannelFileExplorerProps {
  channelId: string;
  botId: string | undefined;
  workspaceId: string | undefined;
  channelDisplayName?: string | null;
  channelWorkspaceEnabled: boolean;
  activeFile: string | null;
  onSelectFile: (workspaceRelativePath: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
  /** When provided, title bar shows a collapse chevron instead of the X close button */
  onCollapseFiles?: () => void;
}

export function ChannelFileExplorer({
  channelId,
  botId,
  workspaceId,
  channelDisplayName,
  channelWorkspaceEnabled,
  activeFile,
  onSelectFile,
  onClose,
  width = 260,
  fullWidth = false,
  onCollapseFiles,
}: ChannelFileExplorerProps) {
  const t = useThemeTokens();
  const queryClient = useQueryClient();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  // Bot info — needed to compute the memory path target
  const { data: bot } = useBot(botId);
  const sharedWorkspace = !!bot?.shared_workspace_id;

  // Pinned panels — used for pin/unpin context menu items
  const { data: channelData } = useChannel(channelId);
  const pinnedPaths = useMemo(
    () => new Set((channelData?.config?.pinned_panels ?? []).map((p) => p.path)),
    [channelData?.config?.pinned_panels],
  );

  // Channel id→display_name map for substituting GUIDs in breadcrumbs.
  // useChannels() is cached app-wide (used by Sidebar/CommandPalette), so this
  // is essentially free here.
  const { data: allChannels } = useChannels();
  const channelNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of allChannels ?? []) {
      const label = c.display_name || c.name;
      if (label) map[c.id] = label;
    }
    return map;
  }, [allChannels]);
  const memoryTarget = botId ? getMemoryPath(botId, sharedWorkspace) : null;
  const channelTarget = channelWorkspaceEnabled ? `/channels/${channelId}` : null;

  // Path state — workspace-relative directory, leading slash. Persisted per channel.
  const setRemembered = useFileBrowserStore((s) => s.setChannelExplorerPath);
  const [currentPath, setCurrentPathRaw] = useState<string>(() =>
    pickInitialPath({
      channelId,
      channelWorkspaceEnabled,
      botId,
      sharedWorkspace,
      remembered: useFileBrowserStore.getState().channelExplorerPaths[channelId],
    }),
  );
  const setCurrentPath = useCallback((p: string) => {
    setCurrentPathRaw(p);
    setRemembered(channelId, p);
  }, [channelId, setRemembered]);

  // If channelId changes (mounted with new channel), reset to its initial path
  useEffect(() => {
    setCurrentPathRaw(
      pickInitialPath({
        channelId,
        channelWorkspaceEnabled,
        botId,
        sharedWorkspace,
        remembered: useFileBrowserStore.getState().channelExplorerPaths[channelId],
      }),
    );
  }, [channelId, channelWorkspaceEnabled, botId, sharedWorkspace]);

  // Filter / search — hidden by default to reduce chrome
  const [showFilter, setShowFilter] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Tree data — workspace files endpoint
  const { data: treeData, isLoading: treeLoading, refetch: refetchTree } = useWorkspaceFiles(
    workspaceId,
    dirForApi(currentPath),
  );

  // Combined refresh: tree + IN CONTEXT card. The card subscribes to a separate
  // channel-scoped query, so a tree-only refetch leaves it stale.
  const refreshAll = useCallback(() => {
    refetchTree();
    queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
  }, [refetchTree, queryClient, channelId]);

  // Mutations on the workspace
  const writeWorkspace = useWriteWorkspaceFile(workspaceId ?? "");
  const mkdirWorkspace = useMkdirWorkspace(workspaceId ?? "");
  const deleteWorkspace = useDeleteWorkspaceFile(workspaceId ?? "");
  const moveWorkspace = useMoveWorkspaceFile(workspaceId ?? "");
  const uploadWorkspace = useUploadWorkspaceFile(workspaceId ?? "");

  // Mutations on the channel workspace (for IN CONTEXT card actions)
  const moveChannel = useMoveChannelWorkspaceFile(channelId);
  const deleteChannel = useDeleteChannelWorkspaceFile(channelId);

  // New file / folder inline state
  const [newItem, setNewItem] = useState<"file" | "folder" | null>(null);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    items: ContextMenuItem[];
  } | null>(null);

  // Filtered + sorted entries: folders first, then files, alphabetically.
  const entries = treeData?.entries ?? [];
  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase();
    const filteredEntries = q ? entries.filter((e) => e.name.toLowerCase().includes(q)) : entries;
    return [...filteredEntries].sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [entries, searchQuery]);

  const folders = filtered.filter((e) => e.is_dir);
  const files = filtered.filter((e) => !e.is_dir);

  // Keyboard nav over the file rows in the current directory
  const focusableFiles = files;
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const focusedFile =
    focusedIndex >= 0 && focusedIndex < focusableFiles.length
      ? focusableFiles[focusedIndex]
      : null;
  const explorerRef = useRef<HTMLDivElement>(null);

  // Multi-select: ctrl+click to toggle, shift+click for range, right-click for bulk actions
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const lastClickedRef = useRef<string | null>(null);

  // Flat ordered list of all visible items (folders then files) for shift-range selection
  const allItemPaths = useMemo(() => [
    ...folders.map((e) => "/" + stripSlashes(e.path)),
    ...files.map((e) => stripSlashes(e.path)),
  ], [folders, files]);

  const handleMultiSelect = useCallback((path: string, e?: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean }) => {
    if (e?.shiftKey && lastClickedRef.current) {
      // Range select between lastClicked and current
      const startIdx = allItemPaths.indexOf(lastClickedRef.current);
      const endIdx = allItemPaths.indexOf(path);
      if (startIdx >= 0 && endIdx >= 0) {
        const lo = Math.min(startIdx, endIdx);
        const hi = Math.max(startIdx, endIdx);
        setSelectedPaths((prev) => {
          const next = new Set(prev);
          for (let i = lo; i <= hi; i++) next.add(allItemPaths[i]);
          return next;
        });
        lastClickedRef.current = path;
        return;
      }
    }
    // Ctrl/Cmd toggle
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    lastClickedRef.current = path;
  }, [allItemPaths]);

  useEffect(() => {
    setFocusedIndex(-1);
    setSelectedPaths(new Set());
  }, [currentPath, searchQuery]);

  useEffect(() => {
    const el = explorerRef.current as unknown as HTMLElement | null;
    if (!el) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      const len = focusableFiles.length;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (len) setFocusedIndex((i) => (i < len - 1 ? i + 1 : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (len) setFocusedIndex((i) => (i > 0 ? i - 1 : len - 1));
      } else if (e.key === "Enter" && focusedFile) {
        onSelectFile(stripSlashes(focusedFile.path));
      } else if (e.key === "n") {
        setNewItem("file");
      } else if (e.key === "/") {
        e.preventDefault();
        setShowFilter(true);
        setTimeout(() => searchRef.current?.focus(), 0);
      }
    };
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  }, [focusableFiles, focusedFile, onSelectFile]);

  // Drag-and-drop OS file upload (uploads into the current directory)
  const [osDragging, setOsDragging] = useState(false);
  const dragCounter = useRef(0);
  const [uploadStatus, setUploadStatus] = useState<{ current: number; total: number } | null>(null);

  const handleDragEnter = useCallback((e: any) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer?.types?.includes("Files")) {
      dragCounter.current++;
      setOsDragging(true);
    }
  }, []);
  const handleDragLeave = useCallback((e: any) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setOsDragging(false);
    }
  }, []);
  const handleDragOver = useCallback((e: any) => {
    e.preventDefault();
    if (e.dataTransfer?.types?.includes("Files")) {
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);
  const handleDrop = useCallback(async (e: any) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setOsDragging(false);
    const dropped: File[] = Array.from(e.dataTransfer?.files ?? []);
    if (dropped.length === 0 || !workspaceId) return;
    const targetDir = stripSlashes(currentPath);
    setUploadStatus({ current: 0, total: dropped.length });
    for (let i = 0; i < dropped.length; i++) {
      setUploadStatus({ current: i + 1, total: dropped.length });
      try {
        await uploadWorkspace.mutateAsync({ file: dropped[i], targetDir });
      } catch (err) {
        console.error("Upload failed:", (err as Error).message);
      }
    }
    setUploadStatus(null);
    refetchTree();
  }, [workspaceId, currentPath, uploadWorkspace, refetchTree]);

  // ── Mutations ─────────────────────────────────────────────────────────

  const writeNewFile = useCallback((name: string) => {
    let filename = name;
    if (!filename.includes(".")) filename += ".md";
    const fullPath = joinPath(currentPath, filename);
    writeWorkspace.mutate(
      { path: fullPath, content: filename.endsWith(".md") ? `# ${filename.replace(/\.md$/, "")}\n` : "" },
      {
        onSuccess: () => {
          onSelectFile(fullPath);
          setNewItem(null);
          refetchTree();
        },
      },
    );
  }, [currentPath, writeWorkspace, refetchTree, onSelectFile]);

  const createFolder = useCallback((name: string) => {
    const fullPath = joinPath(currentPath, name);
    mkdirWorkspace.mutate(fullPath, {
      onSuccess: () => {
        setNewItem(null);
        refetchTree();
      },
    });
  }, [currentPath, mkdirWorkspace, refetchTree]);

  const deleteEntry = useCallback(async (name: string, path: string, isDir: boolean) => {
    const ok = await confirm(`Delete ${isDir ? "folder" : "file"} "${name}"?`, {
      title: `Delete ${isDir ? "folder" : "file"}`,
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    const stripped = stripSlashes(path);
    deleteWorkspace.mutate(stripped, { onSuccess: () => refetchTree() });
  }, [deleteWorkspace, refetchTree]);

  // Drag-and-drop move: triggered when a tree file is dropped onto a tree
  // folder. Prompts the user with a confirmation showing src → dst before
  // calling the workspace move endpoint. The backend's move_path treats an
  // existing-directory dst as "move inside that dir" so we just pass the
  // folder path as dst.
  const handleMoveDrop = useCallback(async (srcPath: string, dstFolderPath: string) => {
    const src = stripSlashes(srcPath);
    const dst = stripSlashes(dstFolderPath);
    if (!src || !dst) return;
    // No-op: dragged onto its own parent dir
    const srcParent = src.includes("/") ? src.substring(0, src.lastIndexOf("/")) : "";
    if (srcParent === dst) return;
    // No-op: same path (defensive)
    if (src === dst) return;
    const basename = src.includes("/") ? src.substring(src.lastIndexOf("/") + 1) : src;
    const dstLabel = dst || "/";
    const ok = await confirm(
      `Move "${basename}" into ${dstLabel}/ ?`,
      { title: "Move file", confirmLabel: "Move", variant: "warning" },
    );
    if (!ok) return;
    moveWorkspace.mutate(
      { src, dst },
      { onSuccess: () => refreshAll() },
    );
  }, [confirm, moveWorkspace, refreshAll]);

  // IN CONTEXT card actions (channel API)
  const archiveActiveFile = useCallback((f: ChannelWorkspaceFile) => {
    const basename = f.name.includes("/") ? f.name.substring(f.name.lastIndexOf("/") + 1) : f.name;
    moveChannel.mutate({ old_path: f.path, new_path: `archive/${basename}` });
  }, [moveChannel]);
  const deleteActiveFile = useCallback(async (f: ChannelWorkspaceFile) => {
    const ok = await confirm(`Delete ${f.name}?`, {
      title: "Delete file",
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    deleteChannel.mutate(f.path);
  }, [deleteChannel, confirm]);

  // ── Context menus ─────────────────────────────────────────────────────

  const openFileContextMenu = useCallback((e: any, entry: { name: string; path: string }) => {
    e.preventDefault();
    e.stopPropagation();
    const stripped = stripSlashes(entry.path);
    const items: ContextMenuItem[] = [
      { label: "Open", action: () => { onSelectFile(stripped); setContextMenu(null); } },
      { label: "Copy path", action: () => { navigator.clipboard?.writeText(stripped); setContextMenu(null); } },
    ];

    // Move-to-active is only meaningful when this file lives inside the channel
    // workspace and the channel has its own workspace dir.
    if (channelWorkspaceEnabled && stripped.startsWith(`channels/${channelId}/`)) {
      const channelRel = stripped.slice(`channels/${channelId}/`.length);
      const basename = channelRel.includes("/") ? channelRel.substring(channelRel.lastIndexOf("/") + 1) : channelRel;
      if (channelRel.startsWith("archive/") || channelRel.startsWith("data/")) {
        items.push({
          label: "Move to Active",
          separator: true,
          action: async () => {
            const ok = await confirm(
              `Move "${basename}" to Active?\n\nActive files are injected into context every turn.`,
              { title: "Move to Active", confirmLabel: "Move", variant: "warning" },
            );
            if (ok) {
              moveChannel.mutate({ old_path: channelRel, new_path: basename });
            }
            setContextMenu(null);
          },
        });
      } else {
        items.push({
          label: "Move to Archive",
          separator: true,
          action: () => {
            moveChannel.mutate({ old_path: channelRel, new_path: `archive/${basename}` });
            setContextMenu(null);
          },
        });
      }
    }

    // Pin / Unpin to channel side rail
    const isPinned = pinnedPaths.has(stripped);
    items.push({
      label: isPinned ? "Unpin from channel" : "Pin to channel",
      separator: true,
      action: async () => {
        setContextMenu(null);
        try {
          if (isPinned) {
            await apiFetch(
              `/api/v1/channels/${channelId}/pins?path=${encodeURIComponent(stripped)}`,
              { method: "DELETE" },
            );
          } else {
            await apiFetch(`/api/v1/channels/${channelId}/pins`, {
              method: "POST",
              body: JSON.stringify({ path: stripped, position: "right" }),
            });
          }
          queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
        } catch (err) {
          console.error("Pin/unpin failed:", err);
        }
      },
    });

    items.push({
      label: "Delete",
      danger: true,
      separator: true,
      action: () => {
        deleteEntry(entry.name, entry.path, false);
        setContextMenu(null);
      },
    });

    setContextMenu({ x: e.clientX, y: e.clientY, items });
  }, [channelWorkspaceEnabled, channelId, moveChannel, onSelectFile, deleteEntry, pinnedPaths, queryClient]);

  const openFolderContextMenu = useCallback((e: any, entry: { name: string; path: string }) => {
    e.preventDefault();
    e.stopPropagation();
    const stripped = stripSlashes(entry.path);
    const items: ContextMenuItem[] = [
      { label: "Open", action: () => { setCurrentPath(`/${stripped}`); setContextMenu(null); } },
      {
        label: "New file inside",
        action: () => {
          // Navigate into the folder first so the inline new-item row renders
          // in the right context — the user sees exactly where the file lands.
          setCurrentPath(`/${stripped}`);
          setNewItem("file");
          setContextMenu(null);
        },
      },
      {
        label: "New folder inside",
        action: () => {
          setCurrentPath(`/${stripped}`);
          setNewItem("folder");
          setContextMenu(null);
        },
      },
      { label: "Copy path", separator: true, action: () => { navigator.clipboard?.writeText(stripped); setContextMenu(null); } },
      {
        label: "Delete",
        danger: true,
        separator: true,
        action: () => {
          deleteEntry(entry.name, entry.path, true);
          setContextMenu(null);
        },
      },
    ];
    setContextMenu({ x: e.clientX, y: e.clientY, items });
  }, [deleteEntry, setCurrentPath]);

  // Background context menu (right-click on empty tree area)
  const openBackgroundContextMenu = useCallback((e: any) => {
    // Don't fire when right-click hit a row (those have their own handlers
    // that already preventDefault before bubbling here).
    if (e.defaultPrevented) return;
    e.preventDefault();
    const items: ContextMenuItem[] = [
      { label: "New file", action: () => { setNewItem("file"); setContextMenu(null); } },
      { label: "New folder", action: () => { setNewItem("folder"); setContextMenu(null); } },
      { label: "Refresh", separator: true, action: () => { refreshAll(); setContextMenu(null); } },
    ];
    setContextMenu({ x: e.clientX, y: e.clientY, items });
  }, [refreshAll]);

  // Bulk context menu — shown when right-clicking a multi-selected item
  const openBulkContextMenu = useCallback((e: any) => {
    e.preventDefault();
    e.stopPropagation();
    const count = selectedPaths.size;
    const items: ContextMenuItem[] = [
      {
        label: `Delete ${count} item${count !== 1 ? "s" : ""}`,
        danger: true,
        action: async () => {
          const ok = await confirm(
            `Delete ${count} item${count !== 1 ? "s" : ""}?`,
            { title: "Delete items", confirmLabel: "Delete", variant: "danger" },
          );
          if (!ok) {
            setContextMenu(null);
            return;
          }
          for (const p of selectedPaths) {
            try { await deleteWorkspace.mutateAsync(stripSlashes(p)); } catch {}
          }
          setSelectedPaths(new Set());
          setContextMenu(null);
          refetchTree();
        },
      },
    ];
    setContextMenu({ x: e.clientX, y: e.clientY, items });
  }, [selectedPaths, deleteWorkspace, refetchTree]);

  const isMutating =
    writeWorkspace.isPending ||
    mkdirWorkspace.isPending ||
    deleteWorkspace.isPending ||
    moveWorkspace.isPending ||
    uploadWorkspace.isPending ||
    moveChannel.isPending ||
    deleteChannel.isPending;

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div
      ref={explorerRef}
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        display: "flex",
        flexDirection: "column",
        height: "100%",
        backgroundColor: t.surfaceRaised,
        position: "relative",
        overflow: "hidden",
      }}
      {...(true
        ? {
            tabIndex: 0,
            onDragEnter: handleDragEnter,
            onDragLeave: handleDragLeave,
            onDragOver: handleDragOver,
            onDrop: handleDrop,
          } as any
        : {})}
    >
      {/* Title bar */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          paddingLeft: onCollapseFiles ? 4 : 10,
          paddingRight: 4,
          height: 28,
          gap: 2,
        }}
      >
        {onCollapseFiles && (
          <button
            type="button"
            onClick={onCollapseFiles}
            className="header-icon-btn"
            style={{ padding: 4, borderRadius: 3, cursor: "pointer", background: "none", border: "none" }}
            title="Collapse files"
          >
            <ChevronDown size={12} color={t.textMuted} />
          </button>
        )}
        <span
          style={{
            flex: 1,
            color: t.textMuted,
            fontSize: 11,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          {onCollapseFiles ? "Files" : "Explorer"}
        </span>
        <button type="button"
          className="header-icon-btn"
          onClick={() => setNewItem("file")}
          style={{ padding: 5, borderRadius: 3, cursor: "pointer", background: "none", border: "none" }}
          title="New file in current folder"
        >
          <Plus size={13} color={t.textDim} />
        </button>
        <button type="button"
          className="header-icon-btn"
          onClick={() => setNewItem("folder")}
          style={{ padding: 5, borderRadius: 3, cursor: "pointer", background: "none", border: "none" }}
          title="New folder in current folder"
        >
          <FolderPlus size={13} color={t.textDim} />
        </button>
        <button type="button"
          className="header-icon-btn"
          onClick={() => { setShowFilter((v) => !v); if (!showFilter) setTimeout(() => searchRef.current?.focus(), 0); }}
          style={{ padding: 5, borderRadius: 3, cursor: "pointer", background: showFilter ? t.surfaceOverlay : "none", border: "none" }}
          title="Filter files (/) "
        >
          <Search size={11} color={showFilter ? t.accent : t.textDim} />
        </button>
        <button type="button"
          className="header-icon-btn"
          onClick={refreshAll}
          style={{ padding: 5, borderRadius: 3, cursor: "pointer", background: "none", border: "none" }}
          title="Refresh"
        >
          <RefreshCw size={11} color={t.textDim} />
        </button>
        {!onCollapseFiles && <button type="button"
          className="header-icon-btn"
          onClick={onClose}
          style={{ padding: 5, borderRadius: 3, cursor: "pointer", background: "none", border: "none" }}
        >
          <X size={13} color={t.textDim} />
        </button>}
      </div>

      {/* IN CONTEXT card (channel-scoped) */}
      {channelWorkspaceEnabled && (
        <InContextCard
          channelId={channelId}
          activeFile={activeFile}
          onSelectFile={onSelectFile}
          onArchive={archiveActiveFile}
          onDelete={deleteActiveFile}
        />
      )}

      {/* Scope targets are now in the breadcrumb dropdown */}

      {/* Filter input — shown on demand via Search icon or `/` key */}
      {showFilter && (
        <div style={{ paddingLeft: 8, paddingRight: 8, paddingBottom: 4 }}>
          <div
            className="flex flex-row items-center"
            style={{
              gap: 5,
              background: t.inputBg,
              borderRadius: 4,
              padding: "3px 8px",
              border: `1px solid ${t.surfaceBorder}`,
              height: 24,
            }}
          >
            <Search size={11} color={t.textDim} style={{ flexShrink: 0 }} />
            <input
              ref={searchRef}
              type="text"
              value={searchQuery}
              onChange={(e: any) => setSearchQuery(e.target.value)}
              onKeyDown={(e: any) => {
                if (e.key === "Escape") {
                  setSearchQuery("");
                  setShowFilter(false);
                }
              }}
              placeholder="Filter files…"
              autoFocus
              style={{
                flex: 1,
                background: "none",
                border: "none",
                outline: "none",
                color: t.text,
                fontSize: 11,
                padding: 0,
                minWidth: 0,
              }}
            />
            {searchQuery && (
              <X
                size={11}
                color={t.textDim}
                style={{ cursor: "pointer", flexShrink: 0 } as any}
                onClick={() => { setSearchQuery(""); searchRef.current?.focus(); }}
              />
            )}
          </div>
        </div>
      )}

      {/* Scope nav — plain text links */}
      <ScopeStrip
        currentPath={currentPath}
        scopeTargets={[
          ...(channelTarget ? [{ label: "Channel", path: channelTarget }] : []),
          ...(memoryTarget ? [{ label: "Memory", path: memoryTarget }] : []),
          { label: "Workspace", path: "/" },
        ]}
        onJump={setCurrentPath}
      />

      {/* Breadcrumb */}
      <Breadcrumb
        path={currentPath}
        channelId={channelId}
        channelDisplayName={channelDisplayName}
        channelNameMap={channelNameMap}
        onNavigate={setCurrentPath}
      />

      {/* Tree */}
      <div className="overflow-auto"
        style={{ flex: 1 }}
        {...{ onContextMenu: openBackgroundContextMenu }}
      >
        {treeLoading ? (
          <div style={{ padding: 16, display: "flex", flexDirection: "row", justifyContent: "center" }}><Spinner color={t.accent} /></div>
        ) : (
          <>
            {newItem && (
              <NewItemRow
                kind={newItem}
                onSubmit={(name) => {
                  if (newItem === "file") writeNewFile(name);
                  else createFolder(name);
                }}
                onCancel={() => setNewItem(null)}
              />
            )}
            {folders.map((entry) => {
              const displayLabel =
                entry.display_name ||
                (channelNameMap[entry.name] ?? null);
              const folderPath = "/" + stripSlashes(entry.path);
              return (
                <TreeFolderRow
                  key={entry.path}
                  name={entry.name}
                  displayLabel={displayLabel}
                  fullPath={folderPath}
                  multiSelected={selectedPaths.has(folderPath)}
                  onNavigate={(path, e) => {
                    if (e?.ctrlKey || e?.metaKey || e?.shiftKey) { handleMultiSelect(path, e); return; }
                    setSelectedPaths(new Set());
                    setCurrentPath(path);
                  }}
                  onContextMenu={(e) => {
                    if (selectedPaths.has(folderPath) && selectedPaths.size > 1) {
                      openBulkContextMenu(e);
                    } else {
                      openFolderContextMenu(e, entry);
                    }
                  }}
                  onMoveDrop={(srcPath) => handleMoveDrop(srcPath, entry.path)}
                />
              );
            })}
            {files.map((entry, i) => {
              const filePath = stripSlashes(entry.path);
              return (
                <TreeFileRow
                  key={entry.path}
                  name={entry.name}
                  fullPath={filePath}
                  size={entry.size}
                  modifiedAt={entry.modified_at}
                  selected={activeFile === filePath}
                  multiSelected={selectedPaths.has(filePath)}
                  focused={focusedIndex === i}
                  onSelect={(e) => {
                    if (e?.ctrlKey || e?.metaKey || e?.shiftKey) { handleMultiSelect(filePath, e); return; }
                    setSelectedPaths(new Set());
                    onSelectFile(filePath);
                  }}
                  onDelete={() => deleteEntry(entry.name, entry.path, false)}
                  onContextMenu={(e) => {
                    if (selectedPaths.has(filePath) && selectedPaths.size > 1) {
                      openBulkContextMenu(e);
                    } else {
                      openFileContextMenu(e, entry);
                    }
                  }}
                />
              );
            })}
            {filtered.length === 0 && !newItem && (
              <span
                style={{
                  color: t.textDim,
                  fontSize: 11,
                  fontStyle: "italic",
                  padding: 12,
                  textAlign: "center",
                }}
              >
                {searchQuery ? "No matching files" : "Empty directory"}
              </span>
            )}
            {uploadStatus && (
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: 8 }}>
                <Spinner color={t.accent} size={14} />
                <span style={{ color: t.textMuted, fontSize: 11 }}>
                  Uploading {uploadStatus.current}/{uploadStatus.total}…
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* Mutation status strip */}
      {isMutating && (
        <div style={{ height: 2, backgroundColor: t.accentSubtle }}>
          <div style={{ height: 2, width: "100%", backgroundColor: t.accent, opacity: 0.6 }} />
        </div>
      )}

      {/* OS drag overlay */}
      {osDragging && (
        <div
          style={{
            position: "absolute",
            left: 4,
            right: 4,
            top: 4,
            bottom: 4,
            border: `2px dashed ${t.accent}`,
            backgroundColor: `${t.accent}15`,
            borderRadius: 6,
            display: "flex", flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
          }}
        >
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Upload size={14} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>
              Drop to upload to {currentPath}
            </span>
          </div>
        </div>
      )}

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* Move-confirmation modal (rendered via portal — see useConfirm). */}
      <ConfirmDialogSlot />
    </div>
  );
}
