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
import { View, Text, Pressable, ActivityIndicator, ScrollView, Platform } from "react-native";
import { X, Plus, FolderPlus, Search, Upload, RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useDeleteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
  type ChannelWorkspaceFile,
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
}: ChannelFileExplorerProps) {
  const t = useThemeTokens();
  const queryClient = useQueryClient();

  // Bot info — needed to compute the memory path target
  const { data: bot } = useBot(botId);
  const sharedWorkspace = !!bot?.shared_workspace_id;
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

  // Filter / search
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
  const explorerRef = useRef<View>(null);

  useEffect(() => {
    setFocusedIndex(-1);
  }, [currentPath, searchQuery]);

  useEffect(() => {
    if (Platform.OS !== "web") return;
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

  const deleteEntry = useCallback((name: string, path: string, isDir: boolean) => {
    if (!confirm(`Delete ${isDir ? "folder" : "file"} "${name}"?`)) return;
    const stripped = stripSlashes(path);
    deleteWorkspace.mutate(stripped, { onSuccess: () => refetchTree() });
  }, [deleteWorkspace, refetchTree]);

  // IN CONTEXT card actions (channel API)
  const archiveActiveFile = useCallback((f: ChannelWorkspaceFile) => {
    const basename = f.name.includes("/") ? f.name.substring(f.name.lastIndexOf("/") + 1) : f.name;
    moveChannel.mutate({ old_path: f.path, new_path: `archive/${basename}` });
  }, [moveChannel]);
  const deleteActiveFile = useCallback((f: ChannelWorkspaceFile) => {
    if (!confirm(`Delete ${f.name}?`)) return;
    deleteChannel.mutate(f.path);
  }, [deleteChannel]);

  // ── Context menus ─────────────────────────────────────────────────────

  const openFileContextMenu = useCallback((e: any, entry: { name: string; path: string }) => {
    e.preventDefault();
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
          action: () => {
            if (confirm(`Move "${basename}" to Active?\n\nActive files are injected into context every turn.`)) {
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
  }, [channelWorkspaceEnabled, channelId, moveChannel, onSelectFile, deleteEntry]);

  const openFolderContextMenu = useCallback((e: any, entry: { name: string; path: string }) => {
    e.preventDefault();
    const stripped = stripSlashes(entry.path);
    const items: ContextMenuItem[] = [
      { label: "Open", action: () => { setCurrentPath(`/${stripped}`); setContextMenu(null); } },
      { label: "Copy path", action: () => { navigator.clipboard?.writeText(stripped); setContextMenu(null); } },
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
    <View
      ref={explorerRef}
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
        position: "relative",
      }}
      {...(Platform.OS === "web"
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
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingLeft: 10,
          paddingRight: 4,
          height: 28,
          gap: 2,
        }}
      >
        <Text
          style={{
            flex: 1,
            color: t.textMuted,
            fontSize: 11,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          Explorer
        </Text>
        <Pressable
          onPress={() => setNewItem("file")}
          style={({ hovered }: any) => ({
            padding: 5,
            borderRadius: 3,
            backgroundColor: hovered ? `${t.text}10` : "transparent",
            cursor: "pointer",
          } as any)}
          {...(Platform.OS === "web" ? { title: "New file in current folder" } as any : {})}
        >
          <Plus size={13} color={t.textDim} />
        </Pressable>
        <Pressable
          onPress={() => setNewItem("folder")}
          style={({ hovered }: any) => ({
            padding: 5,
            borderRadius: 3,
            backgroundColor: hovered ? `${t.text}10` : "transparent",
            cursor: "pointer",
          } as any)}
          {...(Platform.OS === "web" ? { title: "New folder in current folder" } as any : {})}
        >
          <FolderPlus size={13} color={t.textDim} />
        </Pressable>
        <Pressable
          onPress={refreshAll}
          style={({ hovered }: any) => ({
            padding: 5,
            borderRadius: 3,
            backgroundColor: hovered ? `${t.text}10` : "transparent",
            cursor: "pointer",
          } as any)}
          {...(Platform.OS === "web" ? { title: "Refresh" } as any : {})}
        >
          <RefreshCw size={11} color={t.textDim} />
        </Pressable>
        <Pressable
          onPress={onClose}
          style={({ hovered }: any) => ({
            padding: 5,
            borderRadius: 3,
            backgroundColor: hovered ? `${t.text}10` : "transparent",
            cursor: "pointer",
          } as any)}
        >
          <X size={13} color={t.textDim} />
        </Pressable>
      </View>

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

      {/* Scope strip */}
      <ScopeStrip
        currentPath={currentPath}
        channelTarget={channelTarget}
        memoryTarget={memoryTarget}
        rootTarget="/"
        onJump={setCurrentPath}
      />

      {/* Filter input */}
      {Platform.OS === "web" && (
        <View style={{ paddingHorizontal: 8, paddingBottom: 4 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
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
                  (e.target as HTMLInputElement).blur();
                }
              }}
              placeholder="Filter files…"
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
        </View>
      )}

      {/* Breadcrumb */}
      <Breadcrumb
        path={currentPath}
        channelId={channelId}
        channelDisplayName={channelDisplayName}
        onNavigate={setCurrentPath}
      />

      {/* Tree */}
      <ScrollView style={{ flex: 1 }}>
        {treeLoading ? (
          <ActivityIndicator color={t.accent} style={{ padding: 16 }} />
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
            {folders.map((entry) => (
              <TreeFolderRow
                key={entry.path}
                name={entry.name}
                fullPath={"/" + stripSlashes(entry.path)}
                onNavigate={setCurrentPath}
                onContextMenu={(e) => openFolderContextMenu(e, entry)}
              />
            ))}
            {files.map((entry, i) => (
              <TreeFileRow
                key={entry.path}
                name={entry.name}
                fullPath={stripSlashes(entry.path)}
                size={entry.size}
                modifiedAt={entry.modified_at}
                selected={activeFile === stripSlashes(entry.path)}
                focused={focusedIndex === i}
                onSelect={() => onSelectFile(stripSlashes(entry.path))}
                onDelete={() => deleteEntry(entry.name, entry.path, false)}
                onContextMenu={(e) => openFileContextMenu(e, entry)}
              />
            ))}
            {filtered.length === 0 && !newItem && (
              <Text
                style={{
                  color: t.textDim,
                  fontSize: 11,
                  fontStyle: "italic",
                  padding: 12,
                  textAlign: "center",
                }}
              >
                {searchQuery ? "No matching files" : "Empty directory"}
              </Text>
            )}
            {uploadStatus && (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, padding: 8 }}>
                <ActivityIndicator color={t.accent} size="small" />
                <Text style={{ color: t.textMuted, fontSize: 11 }}>
                  Uploading {uploadStatus.current}/{uploadStatus.total}…
                </Text>
              </View>
            )}
          </>
        )}
      </ScrollView>

      {/* Mutation status strip */}
      {isMutating && (
        <View style={{ height: 2, backgroundColor: t.accentSubtle }}>
          <View style={{ height: 2, width: "100%", backgroundColor: t.accent, opacity: 0.6 }} />
        </View>
      )}

      {/* OS drag overlay */}
      {osDragging && (
        <View
          style={{
            position: "absolute",
            left: 4,
            right: 4,
            top: 4,
            bottom: 4,
            borderWidth: 2,
            borderColor: t.accent,
            borderStyle: "dashed" as any,
            backgroundColor: `${t.accent}15`,
            borderRadius: 6,
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none" as any,
          }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Upload size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>
              Drop to upload to {currentPath}
            </Text>
          </View>
        </View>
      )}

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}
    </View>
  );
}
