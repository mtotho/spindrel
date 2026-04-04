import { useState, useRef, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import {
  FileText, Archive, Database, Folder, FolderOpen, ChevronDown, ChevronRight,
  Trash2, Upload,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFiles,
  useChannelWorkspaceDataFolder,
  useDeleteChannelWorkspaceFile,
  useUploadChannelWorkspaceFile,
  type ChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ROW_HEIGHT = 28;
const INDENT_SIZE = 16;
const ROW_PADDING_LEFT = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// ExplorerFileRow
// ---------------------------------------------------------------------------

function ExplorerFileRow({
  file,
  channelId,
  selected,
  onSelect,
}: {
  file: ChannelWorkspaceFile;
  channelId: string;
  selected: boolean;
  onSelect: (path: string) => void;
}) {
  const t = useThemeTokens();
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);
  const [hovered, setHovered] = useState(false);

  const icon =
    file.section === "archive" ? <Archive size={14} color={t.textMuted} /> :
    file.section === "data" ? <Database size={14} color={t.textMuted} /> :
    <FileText size={14} color={t.accent} />;

  const displayName = file.name.includes("/")
    ? file.name.substring(file.name.lastIndexOf("/") + 1)
    : file.name;

  const webHover = Platform.OS === "web" ? {
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
  } : {};

  return (
    <Pressable
      onPress={() => onSelect(file.path)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        height: ROW_HEIGHT,
        paddingLeft: ROW_PADDING_LEFT,
        paddingRight: 8,
        backgroundColor: selected ? t.accentSubtle : hovered ? t.surfaceOverlay : "transparent",
        cursor: "pointer" as any,
      }}
      {...webHover as any}
    >
      <View style={{ marginRight: 6, flexShrink: 0 }}>{icon}</View>
      <Text
        style={{
          flex: 1,
          color: selected ? t.accent : t.text,
          fontSize: 13,
          fontWeight: selected ? "600" : "400",
        }}
        numberOfLines={1}
      >
        {displayName}
      </Text>
      {hovered ? (
        <Pressable
          onPress={(e) => {
            e.stopPropagation();
            if (confirm(`Delete ${displayName}?`)) {
              deleteMutation.mutate(file.path);
            }
          }}
          style={{ padding: 2, flexShrink: 0 }}
        >
          <Trash2 size={12} color={t.danger} />
        </Pressable>
      ) : (
        <Text style={{ color: t.textDim, fontSize: 11, flexShrink: 0 }}>
          {formatSize(file.size)}
        </Text>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// ExplorerFolderRow — lazy-loading folder with indented children container
// ---------------------------------------------------------------------------

function ExplorerFolderRow({
  folder,
  channelId,
  selectedPath,
  onSelect,
}: {
  folder: ChannelWorkspaceFile;
  channelId: string;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
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

  const webHover = Platform.OS === "web" ? {
    onMouseEnter: () => setHovered(true),
    onMouseLeave: () => setHovered(false),
  } : {};

  const FolderIcon = open ? FolderOpen : Folder;

  return (
    <View>
      <Pressable
        onPress={() => setOpen(!open)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: ROW_HEIGHT,
          paddingLeft: ROW_PADDING_LEFT,
          paddingRight: 8,
          backgroundColor: hovered ? t.surfaceOverlay : "transparent",
          cursor: "pointer" as any,
        }}
        {...webHover as any}
      >
        <View style={{ marginRight: 4, flexShrink: 0 }}>
          {open
            ? <ChevronDown size={12} color={t.textDim} />
            : <ChevronRight size={12} color={t.textDim} />}
        </View>
        <View style={{ marginRight: 6, flexShrink: 0 }}>
          <FolderIcon size={14} color={t.textMuted} />
        </View>
        <Text
          style={{ flex: 1, color: t.text, fontSize: 13, fontWeight: "500" }}
          numberOfLines={1}
        >
          {basename}
        </Text>
        {folder.count != null && (
          <Text style={{ color: t.textDim, fontSize: 11 }}>
            {folder.count}
          </Text>
        )}
      </Pressable>

      {/* Children: indented container with tree line */}
      {open && (
        <View style={{
          marginLeft: ROW_PADDING_LEFT + 5,
          paddingLeft: INDENT_SIZE - 1,
          borderLeftWidth: 1,
          borderLeftColor: t.surfaceBorder,
        }}>
          {isLoading && (
            <View style={{ height: ROW_HEIGHT, justifyContent: "center", paddingLeft: ROW_PADDING_LEFT }}>
              <ActivityIndicator color={t.accent} size="small" />
            </View>
          )}
          {childFiles.map((f) => (
            <ExplorerFileRow
              key={f.path}
              file={f}
              channelId={channelId}
              selected={selectedPath === f.path}
              onSelect={onSelect}
            />
          ))}
          {childFolders.map((f) => (
            <ExplorerFolderRow
              key={f.name}
              folder={f}
              channelId={channelId}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// ExplorerSection — collapsible section header (ACTIVE / ARCHIVE / DATA)
// ---------------------------------------------------------------------------

function ExplorerSection({
  title,
  count,
  defaultOpen = true,
  children,
  dropZone,
}: {
  title: string;
  count: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
  dropZone?: {
    isDragging: boolean;
    onDragOver: (e: any) => void;
    onDragEnter: (e: any) => void;
    onDragLeave: (e: any) => void;
    onDrop: (e: any) => void;
  };
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);

  const dropProps = dropZone && Platform.OS === "web" ? {
    onDragOver: dropZone.onDragOver,
    onDragEnter: dropZone.onDragEnter,
    onDragLeave: dropZone.onDragLeave,
    onDrop: dropZone.onDrop,
  } : {};

  return (
    <View {...dropProps as any} style={{ position: "relative" }}>
      {/* Section header */}
      <Pressable
        onPress={() => setOpen(!open)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 24,
          paddingHorizontal: 10,
          backgroundColor: t.surfaceOverlay,
          borderBottomWidth: 1,
          borderBottomColor: t.surfaceBorder,
          cursor: "pointer" as any,
        }}
      >
        <View style={{ marginRight: 4 }}>
          {open ? <ChevronDown size={10} color={t.textDim} /> : <ChevronRight size={10} color={t.textDim} />}
        </View>
        <Text
          style={{
            flex: 1,
            color: t.textMuted,
            fontSize: 11,
            fontWeight: "700",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          {title}
        </Text>
        <Text style={{ color: t.textDim, fontSize: 10 }}>{count}</Text>
      </Pressable>

      {/* Section body */}
      {open && (
        <View style={{ minHeight: dropZone ? 32 : undefined }}>
          {children}
        </View>
      )}

      {/* Drop overlay */}
      {dropZone?.isDragging && open && (
        <View
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 24,
            bottom: 0,
            borderWidth: 2,
            borderColor: t.accent,
            borderStyle: "dashed" as any,
            backgroundColor: `${t.accent}15`,
            borderRadius: 4,
            margin: 2,
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none" as any,
          }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Upload size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>
              Drop files to upload to data/
            </Text>
          </View>
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// ChannelFileBrowser — main panel
// ---------------------------------------------------------------------------

export function ChannelFileBrowser({
  channelId,
  selectedPath,
  onSelect,
}: {
  channelId: string;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  const t = useThemeTokens();

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(channelId, {
    includeArchive: true,
    includeData: true,
  });
  const uploadMutation = useUploadChannelWorkspaceFile(channelId);

  const activeFiles = filesData?.files?.filter((f) => f.section === "active") ?? [];
  const archivedFiles = filesData?.files?.filter((f) => f.section === "archive") ?? [];
  const dataFiles = filesData?.files?.filter((f) => f.section === "data") ?? [];
  const dataRootFiles = dataFiles.filter((f) => f.type !== "folder");
  const dataFolders = dataFiles.filter((f) => f.type === "folder");
  const dataTotalCount = dataRootFiles.length + dataFolders.reduce((sum, f) => sum + (f.count ?? 0), 0);

  // Drag-and-drop upload state
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const [uploadStatus, setUploadStatus] = useState<{ uploading: number; done: number; total: number } | null>(null);

  const handleDragOver = useCallback((e: any) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const handleDragEnter = useCallback((e: any) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    if (dragCounter.current === 1) {
      setIsDragging(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: any) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: any) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);

    const files: File[] = Array.from(e.dataTransfer?.files ?? []);
    if (files.length === 0) return;

    setUploadStatus({ uploading: 0, done: 0, total: files.length });

    for (let i = 0; i < files.length; i++) {
      setUploadStatus({ uploading: i + 1, done: i, total: files.length });
      try {
        await uploadMutation.mutateAsync({ file: files[i], targetDir: "data" });
      } catch (err) {
        console.error("Upload failed:", (err as Error).message);
      }
    }

    setUploadStatus(null);
  }, [uploadMutation]);

  if (isLoading) {
    return (
      <View style={{
        backgroundColor: t.surfaceRaised,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
        borderRadius: 8,
        padding: 24,
        alignItems: "center",
      }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const hasNoFiles = activeFiles.length === 0 && archivedFiles.length === 0 && dataFiles.length === 0;

  return (
    <View style={{
      backgroundColor: t.surfaceRaised,
      borderWidth: 1,
      borderColor: t.surfaceBorder,
      borderRadius: 8,
      overflow: "hidden",
    }}>
      {hasNoFiles ? (
        <View style={{ padding: 20, alignItems: "center" }}>
          <Text style={{ color: t.textDim, fontSize: 12 }}>
            No workspace files yet. The bot will create them automatically.
          </Text>
        </View>
      ) : (
        <>
          {/* ACTIVE section */}
          <ExplorerSection title="Active" count={activeFiles.length} defaultOpen>
            {activeFiles.map((f) => (
              <ExplorerFileRow
                key={f.path}
                file={f}
                channelId={channelId}
                selected={selectedPath === f.path}
                onSelect={onSelect}
              />
            ))}
            {activeFiles.length === 0 && (
              <View style={{ height: ROW_HEIGHT, justifyContent: "center", paddingLeft: 12 }}>
                <Text style={{ color: t.textDim, fontSize: 11, fontStyle: "italic" }}>No active files</Text>
              </View>
            )}
          </ExplorerSection>

          {/* ARCHIVE section */}
          <ExplorerSection title="Archive" count={archivedFiles.length} defaultOpen={false}>
            {archivedFiles.map((f) => (
              <ExplorerFileRow
                key={f.path}
                file={f}
                channelId={channelId}
                selected={selectedPath === f.path}
                onSelect={onSelect}
              />
            ))}
            {archivedFiles.length === 0 && (
              <View style={{ height: ROW_HEIGHT, justifyContent: "center", paddingLeft: 12 }}>
                <Text style={{ color: t.textDim, fontSize: 11, fontStyle: "italic" }}>No archived files</Text>
              </View>
            )}
          </ExplorerSection>

          {/* DATA section with drop zone */}
          <ExplorerSection
            title="Data"
            count={dataTotalCount}
            defaultOpen={false}
            dropZone={{
              isDragging,
              onDragOver: handleDragOver,
              onDragEnter: handleDragEnter,
              onDragLeave: handleDragLeave,
              onDrop: handleDrop,
            }}
          >
            {dataRootFiles.map((f) => (
              <ExplorerFileRow
                key={f.path}
                file={f}
                channelId={channelId}
                selected={selectedPath === f.path}
                onSelect={onSelect}
              />
            ))}
            {dataFolders.map((f) => (
              <ExplorerFolderRow
                key={f.name}
                folder={f}
                channelId={channelId}
                selectedPath={selectedPath}
                onSelect={onSelect}
              />
            ))}
            {dataFiles.length === 0 && !uploadStatus && (
              <View style={{ height: 32, justifyContent: "center", paddingLeft: 12 }}>
                <Text style={{ color: t.textDim, fontSize: 11, fontStyle: "italic" }}>
                  Drag files here to upload
                </Text>
              </View>
            )}
            {uploadStatus && (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8, height: ROW_HEIGHT, paddingLeft: 12 }}>
                <ActivityIndicator color={t.accent} size="small" />
                <Text style={{ color: t.textMuted, fontSize: 11 }}>
                  Uploading {uploadStatus.uploading}/{uploadStatus.total}...
                </Text>
              </View>
            )}
          </ExplorerSection>
        </>
      )}
    </View>
  );
}
