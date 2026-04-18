/**
 * BrowseFilesModal — full-width file manager for a channel's workspace.
 *
 * Evicted from the cramped left-rail tree into a proper modal where
 * scope strip + breadcrumb + folder rows can breathe. Desktop renders
 * centered (~760×560); mobile takes the full screen.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, Plus, FolderPlus, Search, Upload, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { Spinner } from "@/src/components/shared/Spinner";
import { apiFetch } from "@/src/api/client";
import {
  useChannel,
  useChannels,
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
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { ContextMenu, type ContextMenuItem } from "./ChannelFileExplorerData";
import {
  ScopeStrip,
  Breadcrumb,
  TreeFolderRow,
  TreeFileRow,
  NewItemRow,
  stripSlashes,
} from "./ChannelFileExplorerParts";

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

interface BrowseFilesModalProps {
  open: boolean;
  channelId: string;
  botId: string | undefined;
  workspaceId: string | undefined;
  channelDisplayName?: string | null;
  channelWorkspaceEnabled: boolean;
  onSelectFile: (workspaceRelativePath: string) => void;
  onClose: () => void;
}

export function BrowseFilesModal({
  open,
  channelId,
  botId,
  workspaceId,
  channelDisplayName,
  channelWorkspaceEnabled,
  onSelectFile,
  onClose,
}: BrowseFilesModalProps) {
  const t = useThemeTokens();
  const queryClient = useQueryClient();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const { data: bot } = useBot(botId);
  const sharedWorkspace = !!bot?.shared_workspace_id;

  const { data: channelData } = useChannel(channelId);
  const pinnedPaths = useMemo(
    () => new Set((channelData?.config?.pinned_panels ?? []).map((p) => p.path)),
    [channelData?.config?.pinned_panels],
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
  const channelTarget = channelWorkspaceEnabled ? `/channels/${channelId}` : null;

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
  const setCurrentPath = useCallback(
    (p: string) => {
      setCurrentPathRaw(p);
      setRemembered(channelId, p);
    },
    [channelId, setRemembered],
  );

  // Reset path when (re)opening against a different channel
  useEffect(() => {
    if (!open) return;
    setCurrentPathRaw(
      pickInitialPath({
        channelId,
        channelWorkspaceEnabled,
        botId,
        sharedWorkspace,
        remembered: useFileBrowserStore.getState().channelExplorerPaths[channelId],
      }),
    );
  }, [open, channelId, channelWorkspaceEnabled, botId, sharedWorkspace]);

  const [showFilter, setShowFilter] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

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

  // Keyboard: Esc closes, Arrow/Enter/n/` standard tree navigation
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === "Escape") {
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        onClose();
        return;
      }
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
        onClose();
      } else if (e.key === "n") {
        setNewItem("file");
      } else if (e.key === "/") {
        e.preventDefault();
        setShowFilter(true);
        setTimeout(() => searchRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, focusableFiles, focusedFile, onSelectFile, onClose]);

  // OS file upload into currentPath
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
  const handleDrop = useCallback(
    async (e: any) => {
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
            onClose();
            setNewItem(null);
            refetchTree();
          },
        },
      );
    },
    [currentPath, writeWorkspace, refetchTree, onSelectFile, onClose],
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
    (e: any, entry: { name: string; path: string }) => {
      e.preventDefault();
      e.stopPropagation();
      const stripped = stripSlashes(entry.path);
      const items: ContextMenuItem[] = [
        {
          label: "Open",
          action: () => {
            onSelectFile(stripped);
            onClose();
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
    },
    [channelWorkspaceEnabled, channelId, moveChannel, onSelectFile, onClose, deleteEntry, pinnedPaths, queryClient, confirm],
  );

  const openFolderContextMenu = useCallback(
    (e: any, entry: { name: string; path: string }) => {
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
    (e: any) => {
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
    (e: any) => {
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
              try { await deleteWorkspace.mutateAsync(stripSlashes(p)); } catch {}
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

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[10050]"
        style={{ background: "rgba(0,0,0,0.45)" }}
        onClick={onClose}
      />

      {/* Dialog: centered on desktop, full-screen on mobile */}
      <div
        ref={rootRef}
        tabIndex={0}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="fixed z-[10051] flex flex-col overflow-hidden outline-none
                   inset-0
                   sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2
                   sm:inset-auto sm:w-[min(760px,92vw)] sm:h-[min(560px,80vh)]
                   sm:rounded-lg sm:border"
        style={{
          background: t.surfaceRaised,
          borderColor: t.surfaceBorder,
          boxShadow: "0 16px 48px rgba(0,0,0,0.4)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center px-3 h-11 gap-1 border-b shrink-0"
          style={{ borderColor: t.surfaceBorder }}
        >
          <span
            className="flex-1 uppercase tracking-wider"
            style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
          >
            Browse files
          </span>
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
          <button
            type="button"
            className="header-icon-btn p-1.5 rounded cursor-pointer bg-transparent border-0"
            onClick={onClose}
            title="Close ( Esc )"
          >
            <X size={14} color={t.textDim} />
          </button>
        </div>

        {/* Filter */}
        {showFilter && (
          <div className="px-3 py-2 border-b shrink-0" style={{ borderColor: t.surfaceBorder }}>
            <div
              className="flex items-center gap-2 rounded px-2 h-7 border"
              style={{ background: t.inputBg, borderColor: t.surfaceBorder }}
            >
              <Search size={12} color={t.textDim} className="shrink-0" />
              <input
                ref={searchRef}
                type="text"
                value={searchQuery}
                onChange={(e: any) => setSearchQuery(e.target.value)}
                onKeyDown={(e: any) => {
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

        {/* Scope strip */}
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
        <div
          className="flex-1 overflow-auto"
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
              {folders.map((entry) => {
                const displayLabel = entry.display_name || (channelNameMap[entry.name] ?? null);
                const folderPath = "/" + stripSlashes(entry.path);
                return (
                  <TreeFolderRow
                    key={entry.path}
                    name={entry.name}
                    displayLabel={displayLabel}
                    fullPath={folderPath}
                    multiSelected={selectedPaths.has(folderPath)}
                    onNavigate={(path, e) => {
                      if (e?.ctrlKey || e?.metaKey || e?.shiftKey) {
                        handleMultiSelect(path, e);
                        return;
                      }
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
                    selected={false}
                    multiSelected={selectedPaths.has(filePath)}
                    focused={focusedIndex === i}
                    onSelect={(e) => {
                      if (e?.ctrlKey || e?.metaKey || e?.shiftKey) {
                        handleMultiSelect(filePath, e);
                        return;
                      }
                      setSelectedPaths(new Set());
                      onSelectFile(filePath);
                      onClose();
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
                <div
                  className="italic text-center p-3"
                  style={{ color: t.textDim, fontSize: 11 }}
                >
                  {searchQuery ? "No matching files" : "Empty directory"}
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
              Drop to upload to {currentPath}
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
    </>,
    document.body,
  );
}
