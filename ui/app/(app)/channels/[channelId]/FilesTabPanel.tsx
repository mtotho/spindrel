/**
 * FilesTabPanel — inline channel-scope file browser for the OmniPanel's
 * Files tab. Ports the body of the former BrowseFilesModal (minus the
 * portal, backdrop, and close button) into a rail-sized surface:
 *
 *   [ + ] [ 📁+ ] [ 🔎 ] [ ⟳ ]                          ~Ntok
 *   Channel · Workspace · Memory
 *   /ws › channels › #home-assistant
 *   [ tree: folders + files, drag-drop upload, context menus, bulk select ]
 *
 * All file ops from the modal are preserved (create, rename, delete, move,
 * upload, bulk select + delete, pin-to-channel context menu item). The
 * IN CONTEXT card has been dropped; the token gauge lives in the action row.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, FolderPlus, Search, Upload, RefreshCw, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { Spinner } from "@/src/components/shared/Spinner";
import { apiFetch } from "@/src/api/client";
import {
  useChannels,
  useChannelWorkspaceFiles,
  useMoveChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import {
  useWorkspaceFiles,
  useWriteWorkspaceFile,
  useMkdirWorkspace,
  useDeleteWorkspaceFile,
  useMoveWorkspaceFile,
  useUploadWorkspaceFile,
} from "@/src/api/hooks/useWorkspaces";
import { useBot } from "@/src/api/hooks/useBots";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { useUIStore } from "@/src/stores/ui";
import { channelSlug } from "@/src/stores/dashboards";
import { ContextMenu, type ContextMenuItem, estimateTokens } from "./ChannelFileExplorerData";
import { parsePayload } from "@/src/components/chat/renderers/nativeApps/shared";
import {
  ScopeStrip,
  Breadcrumb,
  TreeBranch,
  NewItemRow,
  stripSlashes,
} from "./ChannelFileExplorerParts";

// Matches the old InContextCard budget. Shared between the "~Ntok" pill here
// and the channel header's context-budget chip so the two read consistent.
const TOKEN_BUDGET = 8000;
const PINNED_FILES_WIDGET_REF = "core/pinned_files_native";

function pinnedPathsFromDashboardPins(
  pins: Array<{ envelope?: { body?: unknown } }> | undefined,
): Set<string> {
  const match = (pins ?? []).find((pin) => {
    const payload = parsePayload(pin.envelope as any);
    return payload.widget_ref === PINNED_FILES_WIDGET_REF;
  });
  if (!match) return new Set<string>();
  const payload = parsePayload(match.envelope as any);
  const items = (payload.state?.pinned_files as Array<{ path?: string }> | undefined) ?? [];
  return new Set(items.map((item) => item.path).filter((path): path is string => !!path));
}

function joinPath(...parts: string[]): string {
  return parts.map((p) => stripSlashes(p)).filter(Boolean).join("/");
}

function dirForApi(p: string): string {
  if (!p || p === "/") return "/";
  return p.startsWith("/") ? p : `/${p}`;
}

function getMemoryPath(botId: string, sharedWorkspace: boolean): string {
  return sharedWorkspace ? `/bots/${botId}/memory` : "/memory";
}

function pickInitialPath(opts: {
  channelId: string;
  remembered: string | undefined;
}): string {
  if (opts.remembered) return opts.remembered;
  return `/channels/${opts.channelId}`;
}

interface FilesTabPanelProps {
  channelId: string;
  botId: string | undefined;
  workspaceId: string | undefined;
  channelDisplayName?: string | null;
  /** Workspace-relative path of the file currently open in the editor; used
   *  to highlight the row in the tree. Null when no file is open. */
  activeFile?: string | null;
  onSelectFile: (workspaceRelativePath: string) => void;
  /** When true the search filter opens focused on mount — wired to the
   *  Cmd+Shift+B global shortcut so "browse files" lands on search-ready. */
  focusSearchOnMount?: boolean;
}

export function FilesTabPanel({
  channelId,
  botId,
  workspaceId,
  channelDisplayName,
  activeFile,
  onSelectFile,
  focusSearchOnMount = false,
}: FilesTabPanelProps) {
  const t = useThemeTokens();
  const queryClient = useQueryClient();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const { data: bot } = useBot(botId);
  const sharedWorkspace = !!bot?.shared_workspace_id;
  const { pins: dashboardPins, refetch: refetchDashboardPins } = useDashboardPins(channelSlug(channelId));
  const pinnedPaths = useMemo(
    () => pinnedPathsFromDashboardPins(dashboardPins),
    [dashboardPins],
  );

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
  const channelTarget = `/channels/${channelId}`;

  const setRemembered = useFileBrowserStore((s) => s.setChannelExplorerPath);
  const expandDir = useFileBrowserStore((s) => s.expandDir);
  const [currentPath, setCurrentPathRaw] = useState<string>(() =>
    pickInitialPath({
      channelId,
      remembered: useFileBrowserStore.getState().channelExplorerPaths[channelId],
    }),
  );

  // Auto-expand the Knowledge Base folder for the current channel scope on
  // mount so the auto-indexed convention is visible without an extra click.
  // Idempotent — `expandDir` no-ops when already expanded.
  useEffect(() => {
    expandDir(`channels/${channelId}/knowledge-base`);
  }, [channelId, expandDir]);
  const setCurrentPath = useCallback(
    (p: string) => {
      setCurrentPathRaw(p);
      setRemembered(channelId, p);
    },
    [channelId, setRemembered],
  );

  // Reset path when switching channels (panel is mounted per-channel in the
  // OmniPanel's tab pane; channelId may change when user navigates channels).
  useEffect(() => {
    setCurrentPathRaw(
      pickInitialPath({
        channelId,
        remembered: useFileBrowserStore.getState().channelExplorerPaths[channelId],
      }),
    );
  }, [channelId]);

  const [showFilter, setShowFilter] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Popped-in from Cmd+Shift+B — auto-open the filter input on that gesture.
  useEffect(() => {
    if (focusSearchOnMount) {
      setShowFilter(true);
      setTimeout(() => searchRef.current?.focus(), 0);
    }
  }, [focusSearchOnMount]);

  // External "focus files tree" request — fires on each ⌘⇧B / header button
  // click. Opens the filter so the user can start typing immediately; a
  // second tap focuses it. We skip the initial render's tick to avoid
  // auto-opening the filter on first mount.
  const filesFocusTick = useUIStore((s) => s.filesFocusTick);
  const firstTickRef = useRef(true);
  useEffect(() => {
    if (firstTickRef.current) {
      firstTickRef.current = false;
      return;
    }
    setShowFilter(true);
    setTimeout(() => searchRef.current?.focus(), 0);
  }, [filesFocusTick]);

  const { data: treeData, isLoading: treeLoading, refetch: refetchTree } =
    useWorkspaceFiles(workspaceId, dirForApi(currentPath));

  const refreshAll = useCallback(() => {
    refetchTree();
    queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
  }, [refetchTree, queryClient, channelId]);

  const writeWorkspace = useWriteWorkspaceFile(workspaceId ?? "");
  const mkdirWorkspace = useMkdirWorkspace(workspaceId ?? "");
  const deleteWorkspace = useDeleteWorkspaceFile(workspaceId ?? "");
  const moveWorkspace = useMoveWorkspaceFile(workspaceId ?? "");
  const uploadWorkspace = useUploadWorkspaceFile(workspaceId ?? "");
  const moveChannel = useMoveChannelWorkspaceFile(channelId);

  const [newItem, setNewItem] = useState<"file" | "folder" | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number; items: ContextMenuItem[];
  } | null>(null);

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

  const focusableFiles = files;
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const focusedFile =
    focusedIndex >= 0 && focusedIndex < focusableFiles.length ? focusableFiles[focusedIndex] : null;
  const rootRef = useRef<HTMLDivElement>(null);

  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const lastClickedRef = useRef<string | null>(null);
  const selectedCount = selectedPaths.size;
  const visibleSummary = searchQuery
    ? `${filtered.length} match${filtered.length === 1 ? "" : "es"}`
    : `${folders.length} folder${folders.length === 1 ? "" : "s"} · ${files.length} file${files.length === 1 ? "" : "s"}`;

  const allItemPaths = useMemo(
    () => [
      ...folders.map((e) => "/" + stripSlashes(e.path)),
      ...files.map((e) => stripSlashes(e.path)),
    ],
    [folders, files],
  );

  const handleMultiSelect = useCallback(
    (path: string, e?: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean }) => {
      if (e?.shiftKey && lastClickedRef.current) {
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
      setSelectedPaths((prev) => {
        const next = new Set(prev);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return next;
      });
      lastClickedRef.current = path;
    },
    [allItemPaths],
  );

  useEffect(() => {
    setFocusedIndex(-1);
    setSelectedPaths(new Set());
  }, [currentPath, searchQuery]);

  // Keyboard: Arrow navigation + Enter to open + `n` to add + `/` to filter.
  // Esc here unfocuses filter (no modal to close); it does NOT propagate
  // into the channel page's own Esc handling, since the panel is inlined.
  useEffect(() => {
    const el = rootRef.current;
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
        const p = stripSlashes(focusedFile.path);
        onSelectFile(p);
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

  // OS file upload into currentPath
  const [osDragging, setOsDragging] = useState(false);
  const dragCounter = useRef(0);
  const [uploadStatus, setUploadStatus] = useState<{ current: number; total: number } | null>(null);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer?.types?.includes("Files")) {
      dragCounter.current++;
      setOsDragging(true);
    }
  }, []);
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setOsDragging(false);
    }
  }, []);
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer?.types?.includes("Files")) {
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);
  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
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
    },
    [workspaceId, currentPath, uploadWorkspace, refetchTree],
  );

  const writeNewFile = useCallback(
    (name: string) => {
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
    },
    [currentPath, writeWorkspace, refetchTree, onSelectFile],
  );

  const createFolder = useCallback(
    (name: string) => {
      const fullPath = joinPath(currentPath, name);
      mkdirWorkspace.mutate(fullPath, {
        onSuccess: () => {
          setNewItem(null);
          refetchTree();
        },
      });
    },
    [currentPath, mkdirWorkspace, refetchTree],
  );

  const deleteEntry = useCallback(
    async (name: string, path: string, isDir: boolean) => {
      const ok = await confirm(`Delete ${isDir ? "folder" : "file"} "${name}"?`, {
        title: `Delete ${isDir ? "folder" : "file"}`,
        confirmLabel: "Delete",
        variant: "danger",
      });
      if (!ok) return;
      const stripped = stripSlashes(path);
      deleteWorkspace.mutate(stripped, { onSuccess: () => refetchTree() });
    },
    [confirm, deleteWorkspace, refetchTree],
  );

  const handleMoveDrop = useCallback(
    async (srcPath: string, dstFolderPath: string) => {
      const src = stripSlashes(srcPath);
      const dst = stripSlashes(dstFolderPath);
      if (!src || !dst) return;
      const srcParent = src.includes("/") ? src.substring(0, src.lastIndexOf("/")) : "";
      if (srcParent === dst) return;
      if (src === dst) return;
      const basename = src.includes("/") ? src.substring(src.lastIndexOf("/") + 1) : src;
      const dstLabel = dst || "/";
      const ok = await confirm(`Move "${basename}" into ${dstLabel}/ ?`, {
        title: "Move file",
        confirmLabel: "Move",
        variant: "warning",
      });
      if (!ok) return;
      moveWorkspace.mutate({ src, dst }, { onSuccess: () => refreshAll() });
    },
    [confirm, moveWorkspace, refreshAll],
  );

  const openFileContextMenu = useCallback(
    (e: React.MouseEvent, entry: { name: string; path: string }) => {
      e.preventDefault();
      e.stopPropagation();
      const stripped = stripSlashes(entry.path);
      const items: ContextMenuItem[] = [
        {
          label: "Open",
          action: () => {
            onSelectFile(stripped);
            setContextMenu(null);
          },
        },
        {
          label: "Copy path",
          action: () => {
            navigator.clipboard?.writeText(stripped);
            setContextMenu(null);
          },
        },
      ];

      if (stripped.startsWith(`channels/${channelId}/`)) {
        const channelRel = stripped.slice(`channels/${channelId}/`.length);
        const basename = channelRel.includes("/") ? channelRel.substring(channelRel.lastIndexOf("/") + 1) : channelRel;
        if (channelRel.startsWith("archive/") || channelRel.startsWith("data/")) {
          items.push({
            label: "Move to Active",
            separator: true,
            action: async () => {
              const ok = await confirm(
                `Move "${basename}" to Active?\n\nActive files are eligible for automatic context admission in normal chat and execution, but planning/background runs may still fetch them on demand.`,
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
            await refetchDashboardPins();
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
    },
    [channelId, moveChannel, onSelectFile, deleteEntry, pinnedPaths, refetchDashboardPins, confirm],
  );

  const openFolderContextMenu = useCallback(
    (e: React.MouseEvent, entry: { name: string; path: string }) => {
      e.preventDefault();
      e.stopPropagation();
      const stripped = stripSlashes(entry.path);
      const items: ContextMenuItem[] = [
        {
          label: "Open",
          action: () => {
            setCurrentPath(`/${stripped}`);
            setContextMenu(null);
          },
        },
        {
          label: "New file inside",
          action: () => {
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
        {
          label: "Copy path",
          separator: true,
          action: () => {
            navigator.clipboard?.writeText(stripped);
            setContextMenu(null);
          },
        },
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
    },
    [deleteEntry, setCurrentPath],
  );

  const openBackgroundContextMenu = useCallback(
    (e: React.MouseEvent) => {
      if (e.defaultPrevented) return;
      e.preventDefault();
      const items: ContextMenuItem[] = [
        { label: "New file", action: () => { setNewItem("file"); setContextMenu(null); } },
        { label: "New folder", action: () => { setNewItem("folder"); setContextMenu(null); } },
        { label: "Refresh", separator: true, action: () => { refreshAll(); setContextMenu(null); } },
      ];
      setContextMenu({ x: e.clientX, y: e.clientY, items });
    },
    [refreshAll],
  );

  const openBulkContextMenu = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const count = selectedPaths.size;
      const items: ContextMenuItem[] = [
        {
          label: `Delete ${count} item${count !== 1 ? "s" : ""}`,
          danger: true,
          action: async () => {
            const ok = await confirm(`Delete ${count} item${count !== 1 ? "s" : ""}?`, {
              title: "Delete items",
              confirmLabel: "Delete",
              variant: "danger",
            });
            if (!ok) {
              setContextMenu(null);
              return;
            }
            for (const p of selectedPaths) {
              try { await deleteWorkspace.mutateAsync(stripSlashes(p)); } catch {/* empty */}
            }
            setSelectedPaths(new Set());
            setContextMenu(null);
            refetchTree();
          },
        },
      ];
      setContextMenu({ x: e.clientX, y: e.clientY, items });
    },
    [selectedPaths, deleteWorkspace, refetchTree, confirm],
  );

  // Token gauge — counts active-section channel files only, matching the
  // former IN CONTEXT card's computation. Shows as a compact pill in the
  // action row; tooltip lists active filenames so the details aren't lost.
  const { data: activeFilesData } = useChannelWorkspaceFiles(channelId, {
    includeArchive: false,
    includeData: false,
  });
  const activeFiles = useMemo(
    () => (activeFilesData?.files ?? []).filter((f) => f.section === "active" && f.type !== "folder"),
    [activeFilesData],
  );
  const totalSize = activeFiles.reduce((s, f) => s + (f.size || 0), 0);
  const tokenStr = estimateTokens(totalSize);
  const tokenNum = Math.round(totalSize / 4);
  const tokenPct = Math.min(1, tokenNum / TOKEN_BUDGET);
  const tokenColor =
    tokenPct > 0.85 ? t.danger : tokenPct > 0.6 ? t.warning : t.textDim;
  const tokenTitle = activeFiles.length
    ? `Active files in context:\n${activeFiles.map((f) => f.name).join("\n")}`
    : "No active files in context";

  return (
    <div
      ref={rootRef}
      tabIndex={0}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="flex flex-col h-full min-h-0 overflow-hidden outline-none relative"
      style={{ background: t.surface }}
    >
      <div
        className="shrink-0 border-b"
        style={{
          borderColor: `${t.surfaceBorder}55`,
          background: t.surface,
        }}
      >
        <div
          className="flex items-center gap-0.5 px-2 h-8"
          style={{ borderColor: `${t.surfaceBorder}40` }}
        >
          <button
            type="button"
            className="header-icon-btn p-1.5 rounded cursor-pointer bg-transparent border-0"
            onClick={() => setNewItem("file")}
            title="New file in current folder"
          >
            <Plus size={14} color={t.textDim} />
          </button>
          <button
            type="button"
            className="header-icon-btn p-1.5 rounded cursor-pointer bg-transparent border-0"
            onClick={() => setNewItem("folder")}
            title="New folder in current folder"
          >
            <FolderPlus size={14} color={t.textDim} />
          </button>
          <button
            type="button"
            className="header-icon-btn p-1.5 rounded cursor-pointer border-0"
            onClick={() => {
              setShowFilter((v) => !v);
              if (!showFilter) setTimeout(() => searchRef.current?.focus(), 0);
            }}
            style={{ background: showFilter ? t.surfaceOverlay : "transparent" }}
            title="Filter files ( / )"
          >
            <Search size={13} color={showFilter ? t.accent : t.textDim} />
          </button>
          <button
            type="button"
            className="header-icon-btn p-1.5 rounded cursor-pointer bg-transparent border-0"
            onClick={refreshAll}
            title="Refresh"
          >
            <RefreshCw size={13} color={t.textDim} />
          </button>
          <span
            className="ml-1 truncate"
            style={{
              color: t.textDim,
              fontSize: 10,
              letterSpacing: "0.02em",
            }}
          >
            {visibleSummary}
            {selectedCount > 0 ? ` · ${selectedCount} selected` : " · drag files to move"}
          </span>
          <span
            className="ml-auto relative overflow-hidden rounded"
            title={tokenTitle}
            style={{
              padding: "1px 6px",
              fontSize: 10,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              color: tokenColor,
              backgroundColor: `${t.text}06`,
              flexShrink: 0,
            }}
          >
            <span
              className="absolute left-0 top-0 bottom-0 rounded"
              style={{
                width: `${Math.round(tokenPct * 100)}%`,
                backgroundColor: tokenColor,
                opacity: 0.12,
                transition: "width 0.3s ease, background-color 0.3s ease",
              }}
            />
            <span className="relative">~{tokenStr} tok</span>
          </span>
        </div>

        {showFilter && (
          <div className="px-2 py-1.5 border-t shrink-0" style={{ borderColor: `${t.surfaceBorder}40` }}>
            <div
              className="flex items-center gap-2 rounded px-2 h-7 border"
              style={{ background: t.inputBg, borderColor: t.surfaceBorder }}
            >
              <Search size={12} color={t.textDim} className="shrink-0" />
              <input
                ref={searchRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    e.stopPropagation();
                    setSearchQuery("");
                    setShowFilter(false);
                  }
                }}
                placeholder="Filter files…"
                autoFocus
                className="flex-1 bg-transparent border-0 outline-none text-xs p-0 min-w-0"
                style={{ color: t.text }}
              />
              {searchQuery && (
                <X
                  size={12}
                  color={t.textDim}
                  className="cursor-pointer shrink-0"
                  onClick={() => {
                    setSearchQuery("");
                    searchRef.current?.focus();
                  }}
                />
              )}
            </div>
          </div>
        )}

        <ScopeStrip
          currentPath={currentPath}
          scopeTargets={[
            ...(channelTarget ? [{ label: "Channel", path: channelTarget }] : []),
            { label: "Workspace", path: "/" },
            ...(memoryTarget ? [{ label: "Memory", path: memoryTarget }] : []),
          ]}
          onJump={setCurrentPath}
        />

        <Breadcrumb
          path={currentPath}
          channelId={channelId}
          channelDisplayName={channelDisplayName}
          channelNameMap={channelNameMap}
          onNavigate={setCurrentPath}
        />
      </div>

      {/* Tree */}
      <div
        className="flex-1 min-h-0 overflow-auto"
        onContextMenu={openBackgroundContextMenu}
      >
        {treeLoading ? (
          <div className="flex justify-center p-4">
            <Spinner color={t.accent} />
          </div>
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
            <TreeBranch
              workspaceId={workspaceId}
              folderPath={stripSlashes(currentPath)}
              folderName={stripSlashes(currentPath).split("/").pop() || "/"}
              isRoot
              depth={0}
              selectedPaths={selectedPaths}
              activeFilePath={activeFile ?? null}
              childDisplayLabels={channelNameMap}
              callbacks={{
                onSelectFile: (filePath, e) => {
                  if (e?.ctrlKey || e?.metaKey || e?.shiftKey) {
                    handleMultiSelect(filePath, e);
                    return;
                  }
                  setSelectedPaths(new Set());
                  onSelectFile(filePath);
                },
                onFileContextMenu: (e, entry) => {
                  const filePath = stripSlashes(entry.path);
                  if (selectedPaths.has(filePath) && selectedPaths.size > 1) {
                    openBulkContextMenu(e);
                  } else {
                    openFileContextMenu(e, entry);
                  }
                },
                onFolderContextMenu: (e, entry) => {
                  const folderPath = "/" + stripSlashes(entry.path);
                  if (selectedPaths.has(folderPath) && selectedPaths.size > 1) {
                    openBulkContextMenu(e);
                  } else {
                    openFolderContextMenu(e, entry);
                  }
                },
                onMoveDrop: (srcPath, dstFolderPath) => {
                  void handleMoveDrop(srcPath, dstFolderPath);
                },
                onDeleteFile: (name, path) => deleteEntry(name, path, false),
              }}
            />
            {!treeLoading && (treeData?.entries ?? []).length === 0 && !newItem && (
              <div
                className="px-4 py-6 text-center"
                style={{ color: t.textDim }}
              >
                <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted }}>
                  {searchQuery ? "No matching files" : "Empty directory"}
                </div>
                <div style={{ fontSize: 10, marginTop: 4 }}>
                  {searchQuery ? "Try a broader filter or clear search." : "Create a file, create a folder, or drop files here to upload."}
                </div>
              </div>
            )}
            {uploadStatus && (
              <div className="flex items-center gap-2 p-2">
                <Spinner color={t.accent} size={14} />
                <span style={{ color: t.textMuted, fontSize: 11 }}>
                  Uploading {uploadStatus.current}/{uploadStatus.total}…
                </span>
              </div>
            )}
          </>
        )}
      </div>

      {/* OS drag overlay */}
      {osDragging && (
        <div
          className="absolute inset-1 flex items-center justify-center rounded pointer-events-none gap-2"
          style={{
            border: `2px dashed ${t.accent}`,
            backgroundColor: `${t.accent}15`,
          }}
        >
          <Upload size={14} color={t.accent} />
          <span style={{ color: t.accent, fontSize: 12, fontWeight: 600 }}>
            Drop files to upload into {currentPath}
          </span>
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

      <ConfirmDialogSlot />
    </div>
  );
}
