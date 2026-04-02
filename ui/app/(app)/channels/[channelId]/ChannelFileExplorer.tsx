import { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator, ScrollView, Platform } from "react-native";
import {
  FileText, Archive, ChevronDown, ChevronRight,
  X, Plus, Trash2,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useQueryClient } from "@tanstack/react-query";
import {
  useChannelWorkspaceFiles,
  useWriteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
  useDeleteChannelWorkspaceFile,
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
// File row — VS Code style
// ---------------------------------------------------------------------------
function FileRow({
  file,
  channelId,
  selected,
  onSelect,
  indent = 20,
}: {
  file: WorkspaceFile;
  channelId: string;
  selected: boolean;
  onSelect: (path: string) => void;
  indent?: number;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameName, setRenameName] = useState("");
  const moveMutation = useMoveChannelWorkspaceFile(channelId);
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);

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

  return (
    <>
      <Pressable
        onPress={() => onSelect(file.path)}
        onHoverIn={() => setHovered(true)}
        onHoverOut={() => setHovered(false)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingLeft: indent,
          paddingRight: 8,
          gap: 5,
          backgroundColor: selected
            ? t.accentSubtle
            : hovered
              ? `${t.text}08`
              : "transparent",
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
              <Pressable
                onPress={handleDelete}
                style={{ padding: 2, opacity: 0.5 }}
                {...(Platform.OS === "web" ? { title: "Delete" } as any : {})}
              >
                <Trash2 size={12} color={t.textMuted} />
              </Pressable>
            ) : sizeStr ? (
              <Text style={{ color: t.textDim, fontSize: 10, flexShrink: 0 }}>
                {sizeStr}
              </Text>
            ) : null}
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
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
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
        {open
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
      {open && (
        <View>
          {files.map((f) => (
            <FileRow
              key={f.path}
              file={f}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
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

  const activeFiles = filesData?.files?.filter((f) => f.section === "active") ?? [];
  const archivedFiles = filesData?.files?.filter((f) => f.section === "archive") ?? [];
  const dataFiles = filesData?.files?.filter((f) => f.section === "data") ?? [];

  const totalActiveSize = activeFiles.reduce((sum, f) => sum + f.size, 0);

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
      style={{
        ...(fullWidth ? { flex: 1 } : { width, flexShrink: 0 }),
        backgroundColor: t.surfaceRaised,
      }}
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
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Text style={{
            color: t.textMuted,
            fontSize: 11,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}>
            Explorer
          </Text>
          {totalActiveSize > 0 && (
            <Text style={{ color: t.textDim, fontSize: 9 }}>
              {formatSize(totalActiveSize)} &middot; {estimateTokens(totalActiveSize)} tok
            </Text>
          )}
        </View>
        <Pressable
          onPress={onClose}
          style={{ padding: 4, borderRadius: 3, cursor: "pointer" } as any}
        >
          <X size={14} color={t.textDim} />
        </Pressable>
      </View>

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
                No workspace files yet
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
