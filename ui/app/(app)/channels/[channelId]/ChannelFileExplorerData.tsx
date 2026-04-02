/**
 * Data section components for the channel file explorer sidebar.
 * Extracted from ChannelFileExplorer.tsx to keep files under 1000 lines.
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import {
  Archive, Database, ChevronDown, ChevronRight,
  Folder, Upload,
  FileJson, FileCode, FileSpreadsheet, Image, FileType, FileText, File as FileIcon,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceDataFolder,
  useDeleteChannelWorkspaceFile,
  useMoveChannelWorkspaceFile,
  useUploadChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";

// Re-export shared types so the main file can import from one place
export type WorkspaceFile = {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  section: string;
  type?: "folder";
  count?: number;
};

export type Section = "active" | "archive" | "data";

/** Compute the new path when moving a file to a different section */
export function computeMovePath(file: WorkspaceFile, targetSection: Section): string {
  const filename = file.name;
  if (targetSection === "active") return filename;
  return `${targetSection}/${filename}`;
}

/** Format bytes as human-readable size */
export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null || isNaN(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 100) return `${kb.toFixed(1)} KB`;
  return `${Math.round(kb)} KB`;
}

/** Rough token estimate (~4 chars/token for English markdown) */
export function estimateTokens(bytes: number): string {
  const tokens = Math.round(bytes / 4);
  if (tokens < 1000) return `~${tokens}`;
  return `~${(tokens / 1000).toFixed(1)}k`;
}

/** Get an appropriate icon for a file based on its extension and section */
export function getFileIcon(name: string, section: string, color: string, accentColor: string) {
  if (section === "archive") return <Archive size={13} color={color} />;

  const ext = name.includes(".") ? name.substring(name.lastIndexOf(".")).toLowerCase() : "";
  switch (ext) {
    case ".md": case ".txt": case ".rst":
      return <FileText size={13} color={section === "active" ? accentColor : color} />;
    case ".json":
      return <FileJson size={13} color={color} />;
    case ".yaml": case ".yml": case ".toml": case ".ini": case ".cfg":
      return <FileCode size={13} color={color} />;
    case ".py": case ".js": case ".ts": case ".tsx": case ".jsx":
    case ".sh": case ".go": case ".rs": case ".rb": case ".java":
    case ".c": case ".cpp": case ".h": case ".hpp": case ".swift":
      return <FileCode size={13} color={color} />;
    case ".csv": case ".tsv": case ".xls": case ".xlsx":
      return <FileSpreadsheet size={13} color={color} />;
    case ".png": case ".jpg": case ".jpeg": case ".gif": case ".svg":
    case ".webp": case ".ico": case ".bmp":
      return <Image size={13} color={color} />;
    case ".pdf":
      return <FileType size={13} color={color} />;
    case ".html": case ".css": case ".xml": case ".sql":
      return <FileCode size={13} color={color} />;
    default:
      return section === "active"
        ? <FileText size={13} color={accentColor} />
        : <FileIcon size={13} color={color} />;
  }
}

// ---------------------------------------------------------------------------
// Context menu for file rows
// ---------------------------------------------------------------------------
export function FileContextMenu({
  x,
  y,
  file,
  channelId,
  onClose,
  onRename,
}: {
  x: number;
  y: number;
  file: WorkspaceFile;
  channelId: string;
  onClose: () => void;
  onRename: () => void;
}) {
  const t = useThemeTokens();
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);
  const moveMutation = useMoveChannelWorkspaceFile(channelId);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const items: { label: string; danger?: boolean; action: () => void }[] = [];

  items.push({ label: "Rename...", action: onRename });

  items.push({
    label: "Copy path",
    action: () => { navigator.clipboard?.writeText(file.path); onClose(); },
  });

  // Move to section options
  if (file.section !== "active") {
    items.push({
      label: "Move to Active",
      action: () => {
        const basename = file.name.includes("/") ? file.name.substring(file.name.lastIndexOf("/") + 1) : file.name;
        if (confirm(`Move "${basename}" to Active?\n\nActive files are injected into every request.`)) {
          moveMutation.mutate({ old_path: file.path, new_path: basename });
        }
        onClose();
      },
    });
  }
  if (file.section !== "archive") {
    items.push({
      label: "Move to Archive",
      action: () => {
        const basename = file.name.includes("/") ? file.name.substring(file.name.lastIndexOf("/") + 1) : file.name;
        moveMutation.mutate({ old_path: file.path, new_path: `archive/${basename}` });
        onClose();
      },
    });
  }
  if (file.section !== "data") {
    items.push({
      label: "Move to Data",
      action: () => {
        const basename = file.name.includes("/") ? file.name.substring(file.name.lastIndexOf("/") + 1) : file.name;
        moveMutation.mutate({ old_path: file.path, new_path: `data/${basename}` });
        onClose();
      },
    });
  }

  // Download
  items.push({
    label: "Download",
    action: async () => {
      try {
        const { useAuthStore, getAuthToken } = await import("@/src/stores/auth");
        const { serverUrl } = useAuthStore.getState();
        const token = getAuthToken();
        const url = `${serverUrl}/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(file.path)}`;
        const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
        const data = await res.json();
        const blob = new Blob([data.content], { type: "text/plain" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = file.name.includes("/") ? file.name.substring(file.name.lastIndexOf("/") + 1) : file.name;
        a.click();
        URL.revokeObjectURL(a.href);
      } catch { /* ignore */ }
      onClose();
    },
  });

  items.push({
    label: "Delete",
    danger: true,
    action: () => {
      const basename = file.name.includes("/") ? file.name.substring(file.name.lastIndexOf("/") + 1) : file.name;
      if (confirm(`Delete ${basename}?`)) deleteMutation.mutate(file.path);
      onClose();
    },
  });

  return (
    <div
      ref={menuRef}
      style={{
        position: "fixed",
        left: x,
        top: y,
        zIndex: 9999,
        minWidth: 160,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        padding: "4px 0",
        boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
      }}
    >
      {items.map((item, i) => (
        <div
          key={i}
          onClick={item.action}
          style={{
            padding: "6px 12px",
            fontSize: 12,
            color: item.danger ? t.danger : t.text,
            cursor: "pointer",
            borderTop: item.danger ? `1px solid ${t.surfaceBorder}` : undefined,
            marginTop: item.danger ? 4 : 0,
          }}
          onMouseEnter={(e) => { (e.target as HTMLDivElement).style.background = t.surfaceOverlay; }}
          onMouseLeave={(e) => { (e.target as HTMLDivElement).style.background = "transparent"; }}
        >
          {item.label}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lazy-loading data folder row
// ---------------------------------------------------------------------------
export function DataFolderRow({
  folder,
  channelId,
  activeFile,
  onSelectFile,
  FileRowComponent,
}: {
  folder: WorkspaceFile;
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  FileRowComponent: React.ComponentType<{
    file: WorkspaceFile;
    channelId: string;
    selected: boolean;
    onSelect: (path: string) => void;
  }>;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [osDragOver, setOsDragOver] = useState(false);
  const folderDragCounter = useRef(0);
  const [uploadStatus, setUploadStatus] = useState<{ current: number; total: number } | null>(null);
  const uploadMutation = useUploadChannelWorkspaceFile(channelId);
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

  // OS file drop onto this folder
  const folderDropProps = Platform.OS === "web" ? {
    onDragOver: (e: any) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer.types.includes("Files") && !e.dataTransfer.types.includes("application/x-workspace-file")) {
        e.dataTransfer.dropEffect = "copy";
      }
    },
    onDragEnter: (e: any) => {
      e.preventDefault();
      e.stopPropagation();
      folderDragCounter.current++;
      if (e.dataTransfer.types.includes("Files") && !e.dataTransfer.types.includes("application/x-workspace-file")) {
        setOsDragOver(true);
      }
    },
    onDragLeave: (e: any) => {
      e.preventDefault();
      e.stopPropagation();
      folderDragCounter.current--;
      if (folderDragCounter.current === 0) setOsDragOver(false);
    },
    onDrop: async (e: any) => {
      e.preventDefault();
      e.stopPropagation();
      folderDragCounter.current = 0;
      setOsDragOver(false);

      // Only handle OS file drops, not internal file moves
      if (e.dataTransfer.types.includes("application/x-workspace-file")) return;

      const droppedFiles: File[] = Array.from(e.dataTransfer?.files ?? []);
      if (droppedFiles.length === 0) return;

      if (!open) setOpen(true);
      const targetDir = `data/${folder.name}`;
      setUploadStatus({ current: 0, total: droppedFiles.length });
      for (let i = 0; i < droppedFiles.length; i++) {
        setUploadStatus({ current: i + 1, total: droppedFiles.length });
        try {
          await uploadMutation.mutateAsync({ file: droppedFiles[i], targetDir });
        } catch (err) {
          console.error("Upload failed:", (err as Error).message);
        }
      }
      setUploadStatus(null);
    },
  } : {};

  return (
    <View {...folderDropProps as any}>
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
          backgroundColor: osDragOver ? `${t.accent}18` : "transparent",
          borderWidth: osDragOver ? 1 : 0,
          borderColor: osDragOver ? t.accent : "transparent",
          borderStyle: "dashed" as any,
        }}
      >
        {open
          ? <ChevronDown size={10} color={t.textDim} />
          : <ChevronRight size={10} color={t.textDim} />}
        <Folder size={13} color={osDragOver ? t.accent : t.textMuted} />
        <Text style={{ flex: 1, color: osDragOver ? t.accent : t.text, fontSize: 12, fontWeight: "500" }} numberOfLines={1}>
          {basename}
        </Text>
        {uploadStatus ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <ActivityIndicator color={t.accent} size="small" />
            <Text style={{ color: t.textMuted, fontSize: 10 }}>{uploadStatus.current}/{uploadStatus.total}</Text>
          </View>
        ) : folder.count != null ? (
          <Text style={{ color: t.textDim, fontSize: 10 }}>
            {folder.count}
          </Text>
        ) : null}
      </Pressable>
      {open && (
        <View style={{ paddingLeft: 16 }}>
          {isLoading && <ActivityIndicator color={t.accent} size="small" style={{ padding: 8 }} />}
          {childFiles.map((f) => (
            <FileRowComponent
              key={f.path}
              file={f as WorkspaceFile}
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
              FileRowComponent={FileRowComponent}
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
export function DataSection({
  files,
  channelId,
  activeFile,
  onSelectFile,
  onFileMoved,
  defaultOpen = false,
  FileRowComponent,
}: {
  files: WorkspaceFile[];
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onFileMoved?: (file: WorkspaceFile, targetSection: Section) => void;
  defaultOpen?: boolean;
  FileRowComponent: React.ComponentType<{
    file: WorkspaceFile;
    channelId: string;
    selected: boolean;
    onSelect: (path: string) => void;
  }>;
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
            <FileRowComponent
              key={f.path}
              file={f as WorkspaceFile}
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
              FileRowComponent={FileRowComponent}
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
