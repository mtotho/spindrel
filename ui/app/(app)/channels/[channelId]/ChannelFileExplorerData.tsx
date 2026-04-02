/**
 * Shared types, helpers, and data-section components for ChannelFileExplorer.
 * Extracted to keep individual files under 1000 lines.
 */
import { useState, useRef, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import {
  Archive, ChevronDown, ChevronRight,
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

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
export function computeMovePath(file: WorkspaceFile, targetSection: Section): string {
  const filename = file.name;
  if (targetSection === "active") return filename;
  return `${targetSection}/${filename}`;
}

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null || isNaN(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 100) return `${kb.toFixed(1)} KB`;
  return `${Math.round(kb)} KB`;
}

export function estimateTokens(bytes: number): string {
  const tokens = Math.round(bytes / 4);
  if (tokens < 1000) return `~${tokens}`;
  return `~${(tokens / 1000).toFixed(1)}k`;
}

// Seti-inspired icon colors (VS Code's default icon theme)
const IC = {
  md: "#519aba",    // blue
  json: "#cbcb41",  // yellow
  yaml: "#a074c4",  // purple
  py: "#519aba",    // blue
  js: "#cbcb41",    // yellow
  ts: "#519aba",    // blue
  go: "#519aba",    // blue
  rs: "#dea584",    // orange
  rb: "#cc3e44",    // red
  sh: "#4d5a5e",    // grey
  html: "#e37933",  // orange
  css: "#519aba",   // blue
  csv: "#89e051",   // green
  img: "#a074c4",   // purple
  pdf: "#cc3e44",   // red
};

export function getFileIcon(name: string, section: string, color: string, accentColor: string) {
  if (section === "archive") return <Archive size={14} color={color} />;
  const ext = name.includes(".") ? name.substring(name.lastIndexOf(".")).toLowerCase() : "";
  switch (ext) {
    case ".md": case ".txt": case ".rst":
      return <FileText size={14} color={section === "active" ? accentColor : IC.md} />;
    case ".json":
      return <FileJson size={14} color={IC.json} />;
    case ".yaml": case ".yml": case ".toml": case ".ini": case ".cfg":
      return <FileCode size={14} color={IC.yaml} />;
    case ".py":
      return <FileCode size={14} color={IC.py} />;
    case ".js": case ".jsx":
      return <FileCode size={14} color={IC.js} />;
    case ".ts": case ".tsx":
      return <FileCode size={14} color={IC.ts} />;
    case ".go":
      return <FileCode size={14} color={IC.go} />;
    case ".rs":
      return <FileCode size={14} color={IC.rs} />;
    case ".rb":
      return <FileCode size={14} color={IC.rb} />;
    case ".sh":
      return <FileCode size={14} color={IC.sh} />;
    case ".java": case ".c": case ".cpp": case ".h": case ".hpp": case ".swift":
      return <FileCode size={14} color={color} />;
    case ".csv": case ".tsv": case ".xls": case ".xlsx":
      return <FileSpreadsheet size={14} color={IC.csv} />;
    case ".png": case ".jpg": case ".jpeg": case ".gif": case ".svg":
    case ".webp": case ".ico": case ".bmp":
      return <Image size={14} color={IC.img} />;
    case ".pdf":
      return <FileType size={14} color={IC.pdf} />;
    case ".html": case ".xml":
      return <FileCode size={14} color={IC.html} />;
    case ".css":
      return <FileCode size={14} color={IC.css} />;
    case ".sql":
      return <FileCode size={14} color={color} />;
    default:
      return section === "active"
        ? <FileText size={14} color={accentColor} />
        : <FileIcon size={14} color={color} />;
  }
}

// ---------------------------------------------------------------------------
// Context menu
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

  const basename = (n: string) => n.includes("/") ? n.substring(n.lastIndexOf("/") + 1) : n;
  const items: { label: string; danger?: boolean; separator?: boolean; action: () => void }[] = [];

  items.push({ label: "Rename...", action: onRename });
  items.push({
    label: "Copy path",
    action: () => { navigator.clipboard?.writeText(file.path); onClose(); },
  });

  // Section moves
  if (file.section !== "active") {
    items.push({
      label: "Move to Active",
      separator: true,
      action: () => {
        if (confirm(`Move "${basename(file.name)}" to Active?\n\nActive files are injected into every request.`)) {
          moveMutation.mutate({ old_path: file.path, new_path: basename(file.name) });
        }
        onClose();
      },
    });
  }
  if (file.section !== "archive") {
    items.push({
      label: "Move to Archive",
      separator: !items.some((i) => i.separator),
      action: () => {
        moveMutation.mutate({ old_path: file.path, new_path: `archive/${basename(file.name)}` });
        onClose();
      },
    });
  }
  if (file.section !== "data") {
    items.push({
      label: "Move to Data",
      action: () => {
        moveMutation.mutate({ old_path: file.path, new_path: `data/${basename(file.name)}` });
        onClose();
      },
    });
  }

  items.push({
    label: "Download",
    separator: true,
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
        a.download = basename(file.name);
        a.click();
        URL.revokeObjectURL(a.href);
      } catch { /* ignore */ }
      onClose();
    },
  });

  items.push({
    label: "Delete",
    danger: true,
    separator: true,
    action: () => {
      if (confirm(`Delete ${basename(file.name)}?`)) deleteMutation.mutate(file.path);
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
        minWidth: 170,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 4,
        padding: "3px 0",
        boxShadow: "0 2px 8px rgba(0,0,0,0.35)",
      }}
    >
      {items.map((item, i) => (
        <div
          key={i}
          onClick={item.action}
          style={{
            padding: "4px 12px",
            fontSize: 12,
            color: item.danger ? t.danger : t.text,
            cursor: "pointer",
            borderTop: item.separator ? `1px solid ${t.surfaceBorder}` : undefined,
            marginTop: item.separator ? 3 : 0,
            paddingTop: item.separator ? 7 : 4,
          }}
          onMouseEnter={(e) => { (e.target as HTMLDivElement).style.background = t.accentSubtle; }}
          onMouseLeave={(e) => { (e.target as HTMLDivElement).style.background = "transparent"; }}
        >
          {item.label}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lazy-loading data folder row — compact VS Code style
// ---------------------------------------------------------------------------
export function DataFolderRow({
  folder,
  channelId,
  activeFile,
  onSelectFile,
  FileRowComponent,
  depth = 0,
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
  depth?: number;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState(false);
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

  const indent = 20 + depth * 16;

  return (
    <View {...folderDropProps as any}>
      <Pressable
        onPress={() => setOpen(!open)}
        onHoverIn={() => setHovered(true)}
        onHoverOut={() => setHovered(false)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingLeft: indent - 16,
          paddingRight: 8,
          gap: 4,
          backgroundColor: osDragOver
            ? `${t.accent}15`
            : hovered
              ? `${t.text}08`
              : "transparent",
          cursor: "pointer",
        } as any}
      >
        {open
          ? <ChevronDown size={16} color={t.textDim} style={{ marginRight: -2 }} />
          : <ChevronRight size={16} color={t.textDim} style={{ marginRight: -2 }} />}
        <Folder size={14} color={osDragOver ? t.accent : "#dcb67a"} />
        <Text
          style={{
            flex: 1,
            color: osDragOver ? t.accent : t.text,
            fontSize: 12,
            lineHeight: 22,
          }}
          numberOfLines={1}
        >
          {basename}
        </Text>
        {uploadStatus ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
            <ActivityIndicator color={t.accent} size={10 as any} />
            <Text style={{ color: t.textDim, fontSize: 9 }}>{uploadStatus.current}/{uploadStatus.total}</Text>
          </View>
        ) : folder.count != null ? (
          <Text style={{ color: t.textDim, fontSize: 10 }}>{folder.count}</Text>
        ) : null}
      </Pressable>
      {open && (
        <View style={{ position: "relative" }}>
          {/* Indent guide line */}
          <View style={{
            position: "absolute",
            left: indent + 1,
            top: 0,
            bottom: 0,
            width: 1,
            backgroundColor: `${t.text}12`,
          }} />
          {isLoading && <ActivityIndicator color={t.accent} size="small" style={{ padding: 6 }} />}
          {childFolders.map((f) => (
            <DataFolderRow
              key={f.name}
              folder={f as WorkspaceFile}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              FileRowComponent={FileRowComponent}
              depth={depth + 1}
            />
          ))}
          {childFiles.map((f) => (
            <FileRowComponent
              key={f.path}
              file={f as WorkspaceFile}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
            />
          ))}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Data section — VS Code-style header + OS drag-and-drop upload
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

  const isDragActive = internalDragOver || osDragging;

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

      try {
        const fileData = e.dataTransfer.getData("application/x-workspace-file");
        if (fileData) {
          const file: WorkspaceFile = JSON.parse(fileData);
          if (file.section !== "data") onFileMoved?.(file, "data");
          return;
        }
      } catch { /* not internal */ }

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
        backgroundColor: isDragActive ? `${t.accent}08` : "transparent",
        borderLeftWidth: isDragActive ? 2 : 0,
        borderLeftColor: isDragActive ? t.accent : "transparent",
      }}
      {...internalDropProps as any}
    >
      {/* Section header */}
      <Pressable
        onPress={() => setOpen(!open)}
        style={{
          flexDirection: "row",
          alignItems: "center",
          height: 22,
          paddingLeft: 2,
          paddingRight: 8,
          gap: 2,
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
          Data
        </Text>
        <Text style={{ color: t.textDim, fontSize: 10 }}>{totalCount}</Text>
      </Pressable>

      {open && (
        <View style={{ minHeight: 22, position: "relative" }}>
          {/* Folders before files (VS Code convention) */}
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
          {rootFiles.map((f) => (
            <FileRowComponent
              key={f.path}
              file={f as WorkspaceFile}
              channelId={channelId}
              selected={activeFile === f.path}
              onSelect={onSelectFile}
            />
          ))}
          {uploadStatus && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, height: 22 }}>
              <ActivityIndicator color={t.accent} size={10 as any} />
              <Text style={{ color: t.textDim, fontSize: 10 }}>
                Uploading {uploadStatus.current}/{uploadStatus.total}...
              </Text>
            </View>
          )}
          {files.length === 0 && !uploadStatus && (
            <Text style={{ color: t.textDim, fontSize: 11, paddingHorizontal: 10, height: 22, lineHeight: 22, fontStyle: "italic" }}>
              Drop files here to upload
            </Text>
          )}

          {/* Drop overlay */}
          {osDragging && (
            <View
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: 0,
                bottom: 0,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: `${t.accent}10`,
                pointerEvents: "none" as any,
              }}
            >
              <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                <Upload size={11} color={t.accent} />
                <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>Drop to upload</Text>
              </View>
            </View>
          )}
        </View>
      )}
    </View>
  );
}
