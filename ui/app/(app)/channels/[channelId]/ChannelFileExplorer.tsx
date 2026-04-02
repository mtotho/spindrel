import { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator, ScrollView, Platform } from "react-native";
import {
  FileText, Archive, ChevronDown, ChevronRight,
  X, Plus, GripVertical,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useQueryClient } from "@tanstack/react-query";
import {
  useChannelWorkspaceFiles,
  useWriteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
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
// Draggable file item row with context menu + inline rename
// ---------------------------------------------------------------------------
function FileRow({
  file,
  channelId,
  selected,
  onSelect,
}: {
  file: WorkspaceFile;
  channelId: string;
  selected: boolean;
  onSelect: (path: string) => void;
}) {
  const t = useThemeTokens();
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");
  const moveMutation = useMoveChannelWorkspaceFile(channelId);

  const icon = getFileIcon(file.name, file.section, t.textMuted, t.accent);
  const sizeStr = formatSize(file.size);
  const displayName = file.name.includes("/")
    ? file.name.substring(file.name.lastIndexOf("/") + 1)
    : file.name;

  // HTML5 drag-and-drop (web only)
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
    // Build new path preserving the directory prefix
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

  return (
    <>
      <Pressable
        onPress={() => onSelect(file.path)}
        className="hover:bg-surface-overlay active:bg-surface-overlay"
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          paddingVertical: 6,
          paddingHorizontal: 10,
          borderRadius: 5,
          backgroundColor: selected ? t.surfaceOverlay : "transparent",
        }}
        {...dragProps as any}
        {...(handleContextMenu ? { onContextMenu: handleContextMenu } as any : {})}
      >
        {Platform.OS === "web" && (
          <View style={{ cursor: "grab", opacity: 0.3, marginRight: -2 } as any}>
            <GripVertical size={11} color={t.textDim} />
          </View>
        )}
        {icon}
        <View style={{ flex: 1, minWidth: 0 }}>
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
                background: t.surfaceOverlay,
                border: `1px solid ${t.accent}`,
                borderRadius: 3,
                padding: "1px 4px",
                fontSize: 12,
                color: t.text,
                outline: "none",
                width: "100%",
                fontFamily: "inherit",
              }}
            />
          ) : (
            <Text
              style={{ color: t.text, fontSize: 12, fontWeight: selected ? "600" : "400" }}
              numberOfLines={1}
            >
              {displayName}
            </Text>
          )}
          {!renaming && sizeStr ? <Text style={{ color: t.textDim, fontSize: 10 }}>{sizeStr}</Text> : null}
        </View>
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
    </>
  );
}

// ---------------------------------------------------------------------------
// Droppable collapsible section (Active / Archive)
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
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
  const [dragOver, setDragOver] = useState(false);

  // HTML5 drop zone (web only)
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
      } catch { /* ignore bad data */ }
    },
  } : {};

  return (
    <View
      style={{
        marginBottom: 4,
        borderRadius: 6,
        borderWidth: dragOver ? 2 : 0,
        borderColor: dragOver ? t.accent : "transparent",
        borderStyle: "dashed" as any,
        backgroundColor: dragOver ? `${t.accent}11` : "transparent",
      }}
      {...dropProps as any}
    >
      <Pressable
        onPress={() => setOpen(!open)}
        className="hover:bg-surface-overlay active:bg-surface-overlay"
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          paddingVertical: 6,
          paddingHorizontal: 8,
          borderRadius: 4,
        }}
      >
        {open
          ? <ChevronDown size={12} color={t.textDim} />
          : <ChevronRight size={12} color={t.textDim} />}
        {icon}
        <Text style={{ color: t.textMuted, fontSize: 11, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
          {title}
        </Text>
        <Text style={{ color: t.textDim, fontSize: 10 }}>
          ({files.length})
        </Text>
      </Pressable>
      {open && files.length > 0 && (
        <View style={{ paddingLeft: 4 }}>
          {files.map((f) => (
            <FileRow
              key={f.path}
              file={f}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
            />
          ))}
        </View>
      )}
      {open && files.length === 0 && (
        <Text style={{ color: t.textDim, fontSize: 11, paddingHorizontal: 12, paddingBottom: 6, fontStyle: "italic" }}>
          Drop files here
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// New file creator (toggle-friendly)
// ---------------------------------------------------------------------------
function NewFileInput({
  channelId,
  onCreated,
  creating,
  setCreating,
}: {
  channelId: string;
  onCreated: (path: string) => void;
  creating: boolean;
  setCreating: (v: boolean) => void;
}) {
  const t = useThemeTokens();
  const [name, setName] = useState("");
  const writeMutation = useWriteChannelWorkspaceFile(channelId);

  const handleClose = useCallback(() => {
    setCreating(false);
    setName("");
    writeMutation.reset();
  }, [setCreating, writeMutation]);

  if (!creating) {
    return (
      <Pressable
        onPress={() => setCreating(true)}
        className="hover:opacity-100"
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          paddingVertical: 6,
          paddingHorizontal: 10,
          opacity: 0.7,
        }}
      >
        <Plus size={12} color={t.accent} />
        <Text style={{ color: t.accent, fontSize: 11, fontWeight: "500" }}>New file</Text>
      </Pressable>
    );
  }

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
    <View style={{ paddingHorizontal: 8, paddingVertical: 4, gap: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
        <input
          autoFocus
          value={name}
          onChange={(e: any) => setName(e.target.value)}
          onKeyDown={(e: any) => {
            if (e.key === "Enter") handleCreate();
            if (e.key === "Escape") handleClose();
          }}
          placeholder="filename.md"
          style={{
            flex: 1,
            background: t.surfaceOverlay,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 4,
            padding: "4px 8px",
            fontSize: 12,
            color: t.text,
            outline: "none",
            fontFamily: "monospace",
          }}
        />
        <Pressable
          onPress={handleClose}
          style={{ padding: 4 }}
          {...(Platform.OS === "web" ? { title: "Cancel" } as any : {})}
        >
          <X size={12} color={t.textMuted} />
        </Pressable>
      </View>
      {writeMutation.isError && (
        <Text style={{ color: t.danger, fontSize: 10, paddingHorizontal: 2 }}>
          Failed: {(writeMutation.error as Error)?.message || "Unknown error"}
        </Text>
      )}
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

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(channelId, {
    includeArchive: true,
    includeData: true,
  });

  // Auto-refresh file list while the bot is streaming (agent may be creating files)
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
    // Streaming just ended — do one final refresh to catch any last files
    if (wasStreamingRef.current) {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
    }
  }, [isStreaming, channelId, queryClient]);

  useEffect(() => {
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);

  const moveMutation = useMoveChannelWorkspaceFile(channelId);

  const activeFiles = filesData?.files?.filter((f) => f.section === "active") ?? [];
  const archivedFiles = filesData?.files?.filter((f) => f.section === "archive") ?? [];
  const dataFiles = filesData?.files?.filter((f) => f.section === "data") ?? [];

  const totalActiveSize = activeFiles.reduce((sum, f) => sum + f.size, 0);

  const handleFileMoved = useCallback((file: WorkspaceFile, targetSection: Section) => {
    const newPath = computeMovePath(file, targetSection);

    // Warn when moving to active since those files are auto-injected
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
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        borderRightWidth: fullWidth ? 0 : 1,
        borderRightColor: t.surfaceBorder,
        backgroundColor: t.surface,
      }}
    >
      {/* Header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: 12,
          paddingVertical: 10,
          borderBottomWidth: 1,
          borderBottomColor: t.surfaceBorder,
          minHeight: 42,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Text style={{ color: t.text, fontSize: 12, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Files
          </Text>
          {totalActiveSize > 0 && (
            <Text style={{ color: t.textDim, fontSize: 10 }}>
              {formatSize(totalActiveSize)} &middot; {estimateTokens(totalActiveSize)} tokens
            </Text>
          )}
        </View>
        <Pressable
          onPress={onClose}
          className="hover:bg-surface-overlay active:bg-surface-overlay"
          style={{ padding: 4, borderRadius: 4 }}
          {...(Platform.OS === "web" ? { title: "Close explorer" } as any : {})}
        >
          <X size={14} color={t.textMuted} />
        </Pressable>
      </View>

      {/* File tree */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingVertical: 4 }}>
        {isLoading ? (
          <ActivityIndicator color={t.accent} style={{ padding: 20 }} />
        ) : (
          <>
            <FileSection
              title="Active"
              sectionKey="active"
              icon={<FileText size={11} color={t.accent} />}
              files={activeFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              onFileMoved={handleFileMoved}
            />
            <NewFileInput
              channelId={channelId}
              onCreated={onSelectFile}
              creating={newFileCreating}
              setCreating={setNewFileCreating}
            />
            <FileSection
              title="Archive"
              sectionKey="archive"
              icon={<Archive size={11} color={t.textMuted} />}
              files={archivedFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              onFileMoved={handleFileMoved}
              defaultOpen={false}
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
              <Text style={{ color: t.textDim, fontSize: 12, padding: 16, textAlign: "center" }}>
                No workspace files yet
              </Text>
            )}
          </>
        )}
      </ScrollView>

      {/* Move status */}
      {moveMutation.isPending && (
        <View style={{ paddingHorizontal: 12, paddingVertical: 6, borderTopWidth: 1, borderTopColor: t.surfaceBorder }}>
          <Text style={{ color: t.textMuted, fontSize: 10 }}>Moving file...</Text>
        </View>
      )}
    </View>
  );
}
