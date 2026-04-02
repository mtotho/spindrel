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
// File row — VS Code-style compact row
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
    const basename = displayName;
    if (confirm(`Delete ${basename}?`)) deleteMutation.mutate(file.path);
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
          paddingLeft: selected ? 9 : 10,
          paddingRight: 6,
          gap: 5,
          backgroundColor: selected
            ? t.accentSubtle
            : hovered
              ? t.surfaceOverlay
              : "transparent",
          borderLeftWidth: selected ? 2 : 0,
          borderLeftColor: selected ? t.accent : "transparent",
          cursor: "pointer",
        } as any}
        {...dragProps as any}
        {...(handleContextMenu ? { onContextMenu: handleContextMenu } as any : {})}
      >
        {icon}
        <View style={{ flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center" }}>
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
                background: t.inputBg,
                border: `1px solid ${t.accent}`,
                borderRadius: 2,
                padding: "0px 4px",
                fontSize: 12,
                color: t.text,
                outline: "none",
                width: "100%",
                height: 18,
                fontFamily: "inherit",
              }}
            />
          ) : (
            <>
              <Text
                style={{
                  color: t.text,
                  fontSize: 12,
                  fontWeight: selected ? "500" : "400",
                  lineHeight: 22,
                }}
                numberOfLines={1}
              >
                {displayName}
              </Text>
              <View style={{ flex: 1 }} />
              {hovered ? (
                <Pressable
                  onPress={handleDelete}
                  style={{ padding: 2, opacity: 0.6 }}
                  {...(Platform.OS === "web" ? { title: "Delete" } as any : {})}
                >
                  <Trash2 size={11} color={t.textDim} />
                </Pressable>
              ) : sizeStr ? (
                <Text style={{ color: t.textDim, fontSize: 10, marginLeft: 6, flexShrink: 0 }}>
                  {sizeStr}
                </Text>
              ) : null}
            </>
          )}
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
// Section header — VS Code-style collapsible with separator
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
  children,
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
  children?: React.ReactNode;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
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
        borderLeftWidth: dragOver ? 2 : 0,
        borderLeftColor: dragOver ? t.accent : "transparent",
      }}
      {...dropProps as any}
    >
      {/* Section header */}
      <Pressable
        onPress={() => setOpen(!open)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingHorizontal: 6,
          gap: 4,
          borderBottomWidth: 1,
          borderBottomColor: t.surfaceBorder,
          cursor: "pointer",
        } as any}
      >
        {open
          ? <ChevronDown size={10} color={t.textDim} />
          : <ChevronRight size={10} color={t.textDim} />}
        {icon}
        <Text style={{
          color: t.textMuted,
          fontSize: 11,
          fontWeight: "700",
          textTransform: "uppercase",
          letterSpacing: 0.8,
          flex: 1,
        }}>
          {title}
        </Text>
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
          {children}
          {files.length === 0 && !children && (
            <Text style={{ color: t.textDim, fontSize: 11, paddingHorizontal: 10, paddingVertical: 4, fontStyle: "italic" }}>
              No files
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Inline new file input — appears inside Active section
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
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingHorizontal: 10,
          gap: 5,
          opacity: 0.6,
          cursor: "pointer",
        } as any}
      >
        <Plus size={11} color={t.accent} />
        <Text style={{ color: t.accent, fontSize: 11 }}>New file</Text>
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
    <View style={{ paddingHorizontal: 6, paddingVertical: 2 }}>
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
            background: t.inputBg,
            border: `1px solid ${t.inputBorderFocus}`,
            borderRadius: 2,
            padding: "1px 6px",
            fontSize: 12,
            color: t.text,
            outline: "none",
            height: 20,
            fontFamily: "inherit",
          }}
        />
        <Pressable onPress={handleClose} style={{ padding: 2 }}>
          <X size={11} color={t.textMuted} />
        </Pressable>
      </View>
      {writeMutation.isError && (
        <Text style={{ color: t.danger, fontSize: 10, paddingHorizontal: 2, paddingTop: 2 }}>
          {(writeMutation.error as Error)?.message || "Failed"}
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
        borderRightWidth: fullWidth ? 0 : 1,
        borderRightColor: t.surfaceBorder,
        backgroundColor: t.surface,
      }}
    >
      {/* Header bar */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: 8,
          height: 32,
          borderBottomWidth: 1,
          borderBottomColor: t.surfaceBorder,
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
          <X size={13} color={t.textDim} />
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
            >
              <NewFileInput
                channelId={channelId}
                onCreated={onSelectFile}
                creating={newFileCreating}
                setCreating={setNewFileCreating}
              />
            </FileSection>
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
        <View style={{ paddingHorizontal: 8, paddingVertical: 4, borderTopWidth: 1, borderTopColor: t.surfaceBorder }}>
          <Text style={{ color: t.textDim, fontSize: 10 }}>Moving...</Text>
        </View>
      )}
    </View>
  );
}
