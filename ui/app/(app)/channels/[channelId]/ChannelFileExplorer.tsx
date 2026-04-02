import { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator, ScrollView, Platform } from "react-native";
import {
  FileText, Archive, ChevronDown, ChevronRight,
  X, Plus, Trash2, Search,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useQueryClient } from "@tanstack/react-query";
import {
  useChannelWorkspaceFiles,
  useWriteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
  useDeleteChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import { apiFetch } from "@/src/api/client";
import { useChatStore } from "@/src/stores/chat";
import {
  type WorkspaceFile,
  type Section,
  computeMovePath,
  formatSize,
  estimateTokens,
  getFileIcon,
  FileContextMenu,
  DataSection,
} from "./ChannelFileExplorerData";

interface ChannelFileExplorerProps {
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
}

// ---------------------------------------------------------------------------
// File row — VS Code style
// ---------------------------------------------------------------------------
function FileRow({
  file,
  channelId,
  selected,
  onSelect,
  indent = 20,
  focused = false,
}: {
  file: WorkspaceFile;
  channelId: string;
  selected: boolean;
  onSelect: (path: string) => void;
  indent?: number;
  focused?: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");
  const moveMutation = useMoveChannelWorkspaceFile(channelId);
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);

  // File preview tooltip on sustained hover
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [previewTooltip, setPreviewTooltip] = useState<{ x: number; y: number; content: string } | null>(null);
  const rowRef = useRef<View>(null);

  const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp"]);
  const ext = file.name.includes(".") ? file.name.substring(file.name.lastIndexOf(".")).toLowerCase() : "";
  const isImageFile = IMAGE_EXTS.has(ext);

  const startPreviewTimer = useCallback(() => {
    if (Platform.OS !== "web" || isImageFile) return;
    previewTimer.current = setTimeout(() => {
      // Get row position for tooltip placement
      if (rowRef.current) {
        const el = rowRef.current as unknown as HTMLElement;
        const rect = el.getBoundingClientRect();
        apiFetch<{ content: string }>(
          `/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(file.path)}`
        ).then((data) => {
          const lines = data.content.split("\n").slice(0, 10).join("\n");
          setPreviewTooltip({ x: rect.right + 4, y: rect.top, content: lines });
        }).catch(() => {});
      }
    }, 400);
  }, [channelId, file.path, isImageFile]);

  const clearPreviewTimer = useCallback(() => {
    if (previewTimer.current) { clearTimeout(previewTimer.current); previewTimer.current = null; }
    setPreviewTooltip(null);
  }, []);

  const icon = getFileIcon(file.name, file.section, t.textDim, t.accent);
  const sizeStr = formatSize(file.size);
  const displayName = file.name.includes("/")
    ? file.name.substring(file.name.lastIndexOf("/") + 1)
    : file.name;

  const dragProps = Platform.OS === "web" ? {
    draggable: true,
    onDragStart: (e: any) => {
      e.dataTransfer.setData("application/x-workspace-file", JSON.stringify(file));
      e.dataTransfer.effectAllowed = "move";
    },
  } : {};

  const handleContextMenu = Platform.OS === "web" ? (e: any) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  } : undefined;

  const handleRenameStart = useCallback(() => {
    setRenameName(displayName);
    setRenaming(true);
    setContextMenu(null);
  }, [displayName]);

  const handleRenameSubmit = useCallback(() => {
    const newName = renameName.trim();
    if (!newName || newName === displayName) {
      setRenaming(false);
      return;
    }
    const dirPrefix = file.path.includes("/")
      ? file.path.substring(0, file.path.lastIndexOf("/") + 1)
      : "";
    moveMutation.mutate(
      { old_path: file.path, new_path: `${dirPrefix}${newName}` },
      {
        onSuccess: () => setRenaming(false),
        onError: (err) => { alert(`Rename failed: ${(err as Error)?.message}`); },
      },
    );
  }, [renameName, displayName, file.path, moveMutation]);

  const handleDelete = useCallback((e: any) => {
    e.stopPropagation();
    if (confirm(`Delete ${displayName}?`)) deleteMutation.mutate(file.path);
  }, [displayName, file.path, deleteMutation]);

  const handleArchive = useCallback((e: any) => {
    e.stopPropagation();
    const basename = file.name.includes("/")
      ? file.name.substring(file.name.lastIndexOf("/") + 1)
      : file.name;
    moveMutation.mutate({ old_path: file.path, new_path: `archive/${basename}` });
  }, [file.name, file.path, moveMutation]);

  const isRecentlyModified = file.modified_at > 0 && (Date.now() / 1000 - file.modified_at) < 3600;

  return (
    <>
      <Pressable
        ref={rowRef}
        onPress={() => { clearPreviewTimer(); onSelect(file.path); }}
        onHoverIn={() => { setHovered(true); startPreviewTimer(); }}
        onHoverOut={() => { setHovered(false); clearPreviewTimer(); }}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingLeft: indent,
          paddingRight: 8,
          gap: 5,
          backgroundColor: selected
            ? t.accentSubtle
            : hovered || focused
              ? `${t.text}08`
              : "transparent",
          outline: focused && !selected ? `1px dotted ${t.textDim}` : "none",
          outlineOffset: -1,
          cursor: "pointer",
        } as any}
        {...dragProps as any}
        {...(handleContextMenu ? { onContextMenu: handleContextMenu } as any : {})}
      >
        {icon}
        {renaming ? (
          <input
            autoFocus
            value={renameName}
            onChange={(e: any) => setRenameName(e.target.value)}
            onKeyDown={(e: any) => {
              if (e.key === "Enter") handleRenameSubmit();
              if (e.key === "Escape") setRenaming(false);
            }}
            onBlur={handleRenameSubmit}
            onClick={(e: any) => e.stopPropagation()}
            style={{
              flex: 1,
              background: t.inputBg,
              border: `1px solid ${t.accent}`,
              borderRadius: 2,
              padding: "0px 4px",
              fontSize: 12,
              color: t.text,
              outline: "none",
              height: 18,
              fontFamily: "inherit",
              minWidth: 0,
            }}
          />
        ) : (
          <>
            <Text
              style={{
                flex: 1,
                color: t.text,
                fontSize: 12,
                lineHeight: 22,
                minWidth: 0,
              }}
              numberOfLines={1}
            >
              {displayName}
            </Text>
            {hovered ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 1 }}>
                {file.section === "active" && (
                  <Pressable
                    onPress={handleArchive}
                    style={{ padding: 2, opacity: 0.5 }}
                    {...(Platform.OS === "web" ? { title: "Archive" } as any : {})}
                  >
                    <Archive size={12} color={t.textMuted} />
                  </Pressable>
                )}
                <Pressable
                  onPress={handleDelete}
                  style={{ padding: 2, opacity: 0.5 }}
                  {...(Platform.OS === "web" ? { title: "Delete" } as any : {})}
                >
                  <Trash2 size={12} color={t.textMuted} />
                </Pressable>
              </View>
            ) : (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                {isRecentlyModified && (
                  <View style={{
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    backgroundColor: "#14b8a6",
                    flexShrink: 0,
                  }} />
                )}
                {sizeStr ? (
                  <Text style={{ color: t.textDim, fontSize: 10, flexShrink: 0 }}>
                    {sizeStr}
                  </Text>
                ) : null}
              </View>
            )}
          </>
        )}
      </Pressable>
      {contextMenu && (
        <FileContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          file={file}
          channelId={channelId}
          onClose={() => setContextMenu(null)}
          onRename={handleRenameStart}
        />
      )}
      {previewTooltip && Platform.OS === "web" && (
        <div
          style={{
            position: "fixed",
            left: previewTooltip.x,
            top: previewTooltip.y,
            zIndex: 9999,
            width: 300,
            maxHeight: 200,
            overflow: "hidden",
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 4,
            padding: 8,
            boxShadow: "0 2px 8px rgba(0,0,0,0.35)",
            pointerEvents: "none",
          }}
        >
          <pre style={{
            margin: 0,
            fontSize: 10,
            lineHeight: "1.5",
            color: t.text,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            overflow: "hidden",
          }}>
            {previewTooltip.content}
          </pre>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Section header with hover action buttons (VS Code pattern)
// ---------------------------------------------------------------------------
function FileSection({
  title,
  sectionKey,
  icon,
  files,
  channelId,
  activeFile,
  onSelectFile,
  onFileMoved,
  defaultOpen = true,
  onNewFile,
  forceOpen = false,
  focusedPath,
}: {
  title: string;
  sectionKey: Section;
  icon: React.ReactNode;
  files: WorkspaceFile[];
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onFileMoved?: (file: WorkspaceFile, targetSection: Section) => void;
  defaultOpen?: boolean;
  onNewFile?: () => void;
  forceOpen?: boolean;
  focusedPath?: string | null;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = forceOpen || open;
  const [hovered, setHovered] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const dropProps = Platform.OS === "web" ? {
    onDragOver: (e: any) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDragOver(true);
    },
    onDragLeave: () => setDragOver(false),
    onDrop: (e: any) => {
      e.preventDefault();
      setDragOver(false);
      try {
        const file: WorkspaceFile = JSON.parse(e.dataTransfer.getData("application/x-workspace-file"));
        if (file.section !== sectionKey) {
          onFileMoved?.(file, sectionKey);
        }
      } catch { /* ignore */ }
    },
  } : {};

  return (
    <View
      style={{
        backgroundColor: dragOver ? `${t.accent}08` : "transparent",
      }}
      {...dropProps as any}
    >
      {/* Section header */}
      <Pressable
        onPress={() => setOpen(!open)}
        onHoverIn={() => setHovered(true)}
        onHoverOut={() => setHovered(false)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingLeft: 2,
          paddingRight: 8,
          gap: 2,
          backgroundColor: hovered ? `${t.text}08` : "transparent",
          cursor: "pointer",
        } as any}
      >
        {isOpen
          ? <ChevronDown size={16} color={t.textMuted} style={{ marginRight: -2 }} />
          : <ChevronRight size={16} color={t.textMuted} style={{ marginRight: -2 }} />}
        <Text style={{
          color: t.textMuted,
          fontSize: 11,
          fontWeight: "700",
          textTransform: "uppercase",
          letterSpacing: 0.5,
          flex: 1,
        }}>
          {title}
        </Text>
        {/* Hover action: new file button (Active section only) */}
        {hovered && onNewFile && (
          <Pressable
            onPress={(e) => { e.stopPropagation(); onNewFile(); }}
            style={{ padding: 2, opacity: 0.7 }}
            {...(Platform.OS === "web" ? { title: "New file" } as any : {})}
          >
            <Plus size={14} color={t.textMuted} />
          </Pressable>
        )}
        <Text style={{ color: t.textDim, fontSize: 10 }}>
          {files.length}
        </Text>
      </Pressable>

      {/* File list */}
      {isOpen && (
        <View>
          {files.map((f) => (
            <FileRow
              key={f.path}
              file={f}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
              focused={focusedPath === f.path}
            />
          ))}
          {files.length === 0 && (
            <Text style={{ color: t.textDim, fontSize: 11, paddingLeft: 20, height: 22, lineHeight: 22, fontStyle: "italic" }}>
              No files
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Inline new file input (shown when + is clicked)
// ---------------------------------------------------------------------------
function NewFileInput({
  channelId,
  onCreated,
  onClose,
}: {
  channelId: string;
  onCreated: (path: string) => void;
  onClose: () => void;
}) {
  const t = useThemeTokens();
  const [name, setName] = useState("");
  const writeMutation = useWriteChannelWorkspaceFile(channelId);

  const handleClose = useCallback(() => {
    onClose();
    writeMutation.reset();
  }, [onClose, writeMutation]);

  const handleCreate = () => {
    let filename = name.trim();
    if (!filename) return;
    if (!filename.endsWith(".md")) filename += ".md";
    writeMutation.mutate(
      { path: filename, content: `# ${filename.replace(/\.md$/, "")}\n` },
      {
        onSuccess: () => {
          onCreated(filename);
          handleClose();
        },
      },
    );
  };

  return (
    <View style={{ paddingLeft: 20, paddingRight: 8, height: 22, justifyContent: "center" }}>
      <input
        autoFocus
        value={name}
        onChange={(e: any) => setName(e.target.value)}
        onKeyDown={(e: any) => {
          if (e.key === "Enter") handleCreate();
          if (e.key === "Escape") handleClose();
        }}
        onBlur={() => { if (!name.trim()) handleClose(); }}
        placeholder="filename.md"
        style={{
          background: t.inputBg,
          border: `1px solid ${t.accent}`,
          borderRadius: 2,
          padding: "0px 6px",
          fontSize: 12,
          color: t.text,
          outline: "none",
          height: 18,
          width: "100%",
          fontFamily: "inherit",
        }}
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Main explorer panel
// ---------------------------------------------------------------------------
export function ChannelFileExplorer({
  channelId,
  activeFile,
  onSelectFile,
  onClose,
  width = 260,
  fullWidth = false,
}: ChannelFileExplorerProps) {
  const t = useThemeTokens();
  const [newFileCreating, setNewFileCreating] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(channelId, {
    includeArchive: true,
    includeData: true,
  });

  // Auto-refresh while bot is streaming
  const queryClient = useQueryClient();
  const isStreaming = useChatStore((s) => s.getChannel(channelId).isStreaming);
  const wasStreamingRef = useRef(false);

  useEffect(() => {
    if (isStreaming) {
      const interval = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
      }, 3000);
      return () => clearInterval(interval);
    }
    if (wasStreamingRef.current) {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
    }
  }, [isStreaming, channelId, queryClient]);

  useEffect(() => {
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);

  const moveMutation = useMoveChannelWorkspaceFile(channelId);

  const allActiveFiles = filesData?.files?.filter((f) => f.section === "active") ?? [];
  const allArchivedFiles = filesData?.files?.filter((f) => f.section === "archive") ?? [];
  const allDataFiles = filesData?.files?.filter((f) => f.section === "data") ?? [];

  // Filter by search query
  const q = searchQuery.toLowerCase();
  const activeFiles = q ? allActiveFiles.filter((f) => f.name.toLowerCase().includes(q)) : allActiveFiles;
  const archivedFiles = q ? allArchivedFiles.filter((f) => f.name.toLowerCase().includes(q)) : allArchivedFiles;
  const dataFiles = q ? allDataFiles.filter((f) => f.name.toLowerCase().includes(q)) : allDataFiles;

  const totalActiveSize = allActiveFiles.reduce((sum, f) => sum + f.size, 0);
  const tokenEstimate = estimateTokens(totalActiveSize);
  const TOKEN_BUDGET = 8000;
  const estimatedTokenNum = Math.round(totalActiveSize / 4);
  const tokenPct = Math.min(1, estimatedTokenNum / TOKEN_BUDGET);

  // Keyboard navigation — flat list of visible files (active + archive when sections open)
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);
  const explorerRef = useRef<View>(null);

  // Build flat visible file list (active files always visible; archive/data only if not collapsed by default and not filtered)
  const visibleFiles = [...activeFiles, ...archivedFiles];
  const visibleFilesRef = useRef(visibleFiles);
  visibleFilesRef.current = visibleFiles;

  const focusedPath = focusedIndex >= 0 && focusedIndex < visibleFiles.length
    ? visibleFiles[focusedIndex].path : null;
  const focusedPathRef = useRef(focusedPath);
  focusedPathRef.current = focusedPath;

  // Attach keyboard listener when explorer is mounted (web only)
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const el = explorerRef.current as unknown as HTMLElement;
    if (!el) return;
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      const files = visibleFilesRef.current;
      const len = files.length;
      if (!len) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setFocusedIndex((prev) => prev < len - 1 ? prev + 1 : 0);
          break;
        case "ArrowUp":
          e.preventDefault();
          setFocusedIndex((prev) => prev > 0 ? prev - 1 : len - 1);
          break;
        case "Enter":
          if (focusedPathRef.current) onSelectFile(focusedPathRef.current);
          break;
        case "Delete":
        case "Backspace": {
          const fp = focusedPathRef.current;
          if (!fp) break;
          const f = files.find((vf) => vf.path === fp);
          if (f && confirm(`Delete ${f.name}?`)) {
            deleteMutation.mutate(f.path);
            setFocusedIndex((prev) => Math.min(prev, len - 2));
          }
          break;
        }
        case "n":
          setNewFileCreating(true);
          break;
      }
    };
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  }, [onSelectFile, deleteMutation]); // stable deps only

  const handleFileMoved = useCallback((file: WorkspaceFile, targetSection: Section) => {
    const newPath = computeMovePath(file, targetSection);
    if (targetSection === "active") {
      if (!confirm(
        `Move "${file.name}" to Active?\n\nActive files are automatically injected into every request context.`,
      )) return;
    }
    moveMutation.mutate(
      { old_path: file.path, new_path: newPath },
      {
        onError: (err) => {
          alert(`Move failed: ${(err as Error)?.message || "Unknown error"}`);
        },
      },
    );
  }, [moveMutation]);

  return (
    <View
      ref={explorerRef}
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
      }}
      {...(Platform.OS === "web" ? { tabIndex: 0 } as any : {})}
    >
      {/* Title bar */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingLeft: 10,
          paddingRight: 4,
          height: 28,
        }}
      >
        <Text style={{
          color: t.textMuted,
          fontSize: 11,
          fontWeight: "600",
          textTransform: "uppercase",
          letterSpacing: 0.8,
        }}>
          Explorer
        </Text>
        <Pressable
          onPress={onClose}
          style={{ padding: 4, borderRadius: 3, cursor: "pointer" } as any}
        >
          <X size={14} color={t.textDim} />
        </Pressable>
      </View>

      {/* Token budget bar */}
      {totalActiveSize > 0 && (
        <View style={{ paddingHorizontal: 10, paddingBottom: 4 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View style={{
              flex: 1,
              height: 3,
              borderRadius: 1.5,
              backgroundColor: t.surfaceBorder,
              overflow: "hidden",
            }}>
              <View style={{
                width: `${Math.round(tokenPct * 100)}%` as any,
                height: 3,
                borderRadius: 1.5,
                backgroundColor: tokenPct > 0.8 ? "#f59e0b" : t.accent,
              }} />
            </View>
            <Text style={{ color: t.textDim, fontSize: 9, flexShrink: 0 }}>
              {tokenEstimate} tok
            </Text>
          </View>
        </View>
      )}

      {/* Search input */}
      {Platform.OS === "web" && (
        <View style={{ paddingHorizontal: 8, paddingBottom: 6 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
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
              placeholder="Filter files..."
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

      {/* File tree */}
      <ScrollView style={{ flex: 1 }}>
        {isLoading ? (
          <ActivityIndicator color={t.accent} style={{ padding: 20 }} />
        ) : (
          <>
            <FileSection
              title="Active"
              sectionKey="active"
              icon={<FileText size={10} color={t.accent} />}
              files={activeFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              onFileMoved={handleFileMoved}
              onNewFile={() => setNewFileCreating(true)}
              forceOpen={!!q && activeFiles.length > 0}
              focusedPath={focusedPath}
            />
            {newFileCreating && (
              <NewFileInput
                channelId={channelId}
                onCreated={(path) => { onSelectFile(path); setNewFileCreating(false); }}
                onClose={() => setNewFileCreating(false)}
              />
            )}
            <FileSection
              title="Archive"
              sectionKey="archive"
              icon={<Archive size={10} color={t.textDim} />}
              files={archivedFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              onFileMoved={handleFileMoved}
              defaultOpen={false}
              forceOpen={!!q && archivedFiles.length > 0}
              focusedPath={focusedPath}
            />
            <DataSection
              files={dataFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              onFileMoved={handleFileMoved}
              defaultOpen={false}
              FileRowComponent={FileRow}
            />
            {activeFiles.length === 0 && archivedFiles.length === 0 && dataFiles.length === 0 && (
              <Text style={{ color: t.textDim, fontSize: 11, padding: 12, textAlign: "center" }}>
                {q ? "No matching files" : "No workspace files yet"}
              </Text>
            )}
          </>
        )}
      </ScrollView>

      {/* Status bar */}
      {moveMutation.isPending && (
        <View style={{ paddingHorizontal: 8, paddingVertical: 3, borderTopWidth: 1, borderTopColor: t.surfaceBorder }}>
          <Text style={{ color: t.textDim, fontSize: 10 }}>Moving...</Text>
        </View>
      )}
    </View>
  );
}
