import { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator, ScrollView, Platform } from "react-native";
import {
  FileText, Archive, Database, ChevronDown, ChevronRight,
  X, Trash2, Plus, GripVertical, Folder, Upload,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useQueryClient } from "@tanstack/react-query";
import {
  useChannelWorkspaceFiles,
  useChannelWorkspaceDataFolder,
  useDeleteChannelWorkspaceFile,
  useWriteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
  useUploadChannelWorkspaceFile,
  type ChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import { useChatStore } from "@/src/stores/chat";

type WorkspaceFile = {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  section: string;
  type?: "folder";
  count?: number;
};

type Section = "active" | "archive" | "data";

interface ChannelFileExplorerProps {
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
}

/** Compute the new path when moving a file to a different section */
function computeMovePath(file: WorkspaceFile, targetSection: Section): string {
  const filename = file.name;
  if (targetSection === "active") return filename;
  return `${targetSection}/${filename}`;
}

/** Format bytes as human-readable size */
function formatSize(bytes: number | null | undefined): string {
  if (bytes == null || isNaN(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 100) return `${kb.toFixed(1)} KB`;
  return `${Math.round(kb)} KB`;
}

/** Rough token estimate (~4 chars/token for English markdown) */
function estimateTokens(bytes: number): string {
  const tokens = Math.round(bytes / 4);
  if (tokens < 1000) return `~${tokens}`;
  return `~${(tokens / 1000).toFixed(1)}k`;
}

// ---------------------------------------------------------------------------
// Draggable file item row
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
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);

  const icon =
    file.section === "archive" ? <Archive size={13} color={t.textMuted} /> :
    file.section === "data" ? <Database size={13} color={t.textMuted} /> :
    <FileText size={13} color={t.accent} />;

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

  return (
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
    >
      {Platform.OS === "web" && (
        <View style={{ cursor: "grab", opacity: 0.3, marginRight: -2 } as any}>
          <GripVertical size={11} color={t.textDim} />
        </View>
      )}
      {icon}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text
          style={{ color: t.text, fontSize: 12, fontWeight: selected ? "600" : "400" }}
          numberOfLines={1}
        >
          {displayName}
        </Text>
        {sizeStr ? <Text style={{ color: t.textDim, fontSize: 10 }}>{sizeStr}</Text> : null}
      </View>
      <Pressable
        onPress={(e) => {
          e.stopPropagation();
          if (confirm(`Delete ${file.name}?`)) {
            deleteMutation.mutate(file.path);
          }
        }}
        className="hover:opacity-100"
        style={{ padding: 3, opacity: 0.4 }}
        {...(Platform.OS === "web" ? { title: "Delete file" } as any : {})}
      >
        <Trash2 size={11} color={t.danger} />
      </Pressable>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Droppable collapsible section
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
// Lazy-loading data folder row
// ---------------------------------------------------------------------------
function DataFolderRow({
  folder,
  channelId,
  activeFile,
  onSelectFile,
}: {
  folder: WorkspaceFile;
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useChannelWorkspaceDataFolder(
    open ? channelId : undefined,
    open ? folder.name : null,
  );

  const children = data?.files?.filter((f) => f.section === "data") ?? [];
  const childFiles = children.filter((f) => f.type !== "folder");
  const childFolders = children.filter((f) => f.type === "folder");
  const basename = folder.name.includes("/")
    ? folder.name.substring(folder.name.lastIndexOf("/") + 1)
    : folder.name;

  return (
    <View>
      <Pressable
        onPress={() => setOpen(!open)}
        className="hover:bg-surface-overlay active:bg-surface-overlay"
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          paddingVertical: 6,
          paddingHorizontal: 10,
          borderRadius: 5,
        }}
      >
        {open
          ? <ChevronDown size={10} color={t.textDim} />
          : <ChevronRight size={10} color={t.textDim} />}
        <Folder size={13} color={t.textMuted} />
        <Text style={{ flex: 1, color: t.text, fontSize: 12, fontWeight: "500" }} numberOfLines={1}>
          {basename}
        </Text>
        {folder.count != null && (
          <Text style={{ color: t.textDim, fontSize: 10 }}>
            {folder.count}
          </Text>
        )}
      </Pressable>
      {open && (
        <View style={{ paddingLeft: 16 }}>
          {isLoading && <ActivityIndicator color={t.accent} size="small" style={{ padding: 8 }} />}
          {childFiles.map((f) => (
            <FileRow
              key={f.path}
              file={f}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
            />
          ))}
          {childFolders.map((f) => (
            <DataFolderRow
              key={f.name}
              folder={f as WorkspaceFile}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
            />
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Data section with folder support + OS drag-and-drop upload
// ---------------------------------------------------------------------------
function DataSection({
  files,
  channelId,
  activeFile,
  onSelectFile,
  onFileMoved,
  defaultOpen = false,
}: {
  files: WorkspaceFile[];
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onFileMoved?: (file: WorkspaceFile, targetSection: Section) => void;
  defaultOpen?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
  const [internalDragOver, setInternalDragOver] = useState(false);
  const [osDragging, setOsDragging] = useState(false);
  const dragCounter = useRef(0);
  const [uploadStatus, setUploadStatus] = useState<{ current: number; total: number } | null>(null);
  const uploadMutation = useUploadChannelWorkspaceFile(channelId);

  const rootFiles = files.filter((f) => f.type !== "folder");
  const folders = files.filter((f) => f.type === "folder");
  const totalCount = rootFiles.length + folders.reduce((sum, f) => sum + (f.count ?? 0), 0);

  // Internal workspace file drag (move between sections)
  const internalDropProps = Platform.OS === "web" ? {
    onDragOver: (e: any) => {
      e.preventDefault();
      // Check if this is an internal file move or OS file drop
      if (e.dataTransfer.types.includes("application/x-workspace-file")) {
        e.dataTransfer.dropEffect = "move";
        setInternalDragOver(true);
      } else if (e.dataTransfer.types.includes("Files")) {
        e.dataTransfer.dropEffect = "copy";
      }
    },
    onDragEnter: (e: any) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current++;
      if (e.dataTransfer.types.includes("Files") && !e.dataTransfer.types.includes("application/x-workspace-file")) {
        setOsDragging(true);
      }
    },
    onDragLeave: (e: any) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current--;
      if (dragCounter.current === 0) {
        setInternalDragOver(false);
        setOsDragging(false);
      }
    },
    onDrop: async (e: any) => {
      e.preventDefault();
      dragCounter.current = 0;
      setInternalDragOver(false);
      setOsDragging(false);

      // Check for internal workspace file move first
      try {
        const fileData = e.dataTransfer.getData("application/x-workspace-file");
        if (fileData) {
          const file: WorkspaceFile = JSON.parse(fileData);
          if (file.section !== "data") {
            onFileMoved?.(file, "data");
          }
          return;
        }
      } catch { /* not an internal drag */ }

      // OS file drop — upload to data/
      const droppedFiles: File[] = Array.from(e.dataTransfer?.files ?? []);
      if (droppedFiles.length === 0) return;

      // Auto-expand if closed
      if (!open) setOpen(true);

      setUploadStatus({ current: 0, total: droppedFiles.length });
      for (let i = 0; i < droppedFiles.length; i++) {
        setUploadStatus({ current: i + 1, total: droppedFiles.length });
        try {
          await uploadMutation.mutateAsync({ file: droppedFiles[i], targetDir: "data" });
        } catch (err) {
          console.error("Upload failed:", (err as Error).message);
        }
      }
      setUploadStatus(null);
    },
  } : {};

  return (
    <View
      style={{
        marginBottom: 4,
        borderRadius: 6,
        borderWidth: (internalDragOver || osDragging) ? 2 : 0,
        borderColor: (internalDragOver || osDragging) ? t.accent : "transparent",
        borderStyle: "dashed" as any,
        backgroundColor: (internalDragOver || osDragging) ? `${t.accent}11` : "transparent",
      }}
      {...internalDropProps as any}
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
        <Database size={11} color={t.textMuted} />
        <Text style={{ color: t.textMuted, fontSize: 11, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Data
        </Text>
        <Text style={{ color: t.textDim, fontSize: 10 }}>
          ({totalCount})
        </Text>
      </Pressable>
      {open && (
        <View style={{ paddingLeft: 4, minHeight: 28 }}>
          {rootFiles.map((f) => (
            <FileRow
              key={f.path}
              file={f}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
            />
          ))}
          {folders.map((f) => (
            <DataFolderRow
              key={f.name}
              folder={f}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
            />
          ))}
          {uploadStatus && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6 }}>
              <ActivityIndicator color={t.accent} size="small" />
              <Text style={{ color: t.textMuted, fontSize: 10 }}>
                Uploading {uploadStatus.current}/{uploadStatus.total}...
              </Text>
            </View>
          )}
          {files.length === 0 && !uploadStatus && (
            <Text style={{ color: t.textDim, fontSize: 11, paddingHorizontal: 12, paddingBottom: 6, fontStyle: "italic" }}>
              Drop files here to upload
            </Text>
          )}
        </View>
      )}

      {/* Drop overlay when dragging OS files */}
      {osDragging && (
        <View
          style={{
            position: "absolute",
            left: 2,
            right: 2,
            top: open ? 30 : 2,
            bottom: 2,
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none" as any,
          }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Upload size={12} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>Drop to upload</Text>
          </View>
        </View>
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
