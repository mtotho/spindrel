import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator, ScrollView, Platform } from "react-native";
import {
  FileText, Archive, Database, ChevronDown, ChevronRight,
  X, Trash2, Plus,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFiles,
  useDeleteChannelWorkspaceFile,
  useWriteChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";

interface ChannelFileExplorerProps {
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onClose: () => void;
  width?: number;
  fullWidth?: boolean;
}

// ---------------------------------------------------------------------------
// File item row
// ---------------------------------------------------------------------------
function FileRow({
  file,
  channelId,
  selected,
  onSelect,
}: {
  file: { name: string; path: string; size: number; modified_at: number; section: string };
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

  const sizeKb = (file.size / 1024).toFixed(1);

  return (
    <Pressable
      onPress={() => onSelect(file.path)}
      className="hover:bg-surface-overlay active:bg-surface-overlay"
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingVertical: 6,
        paddingHorizontal: 10,
        borderRadius: 5,
        backgroundColor: selected ? t.surfaceOverlay : "transparent",
      }}
    >
      {icon}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text
          style={{ color: t.text, fontSize: 12, fontWeight: selected ? "600" : "400" }}
          numberOfLines={1}
        >
          {file.name}
        </Text>
        <Text style={{ color: t.textDim, fontSize: 10 }}>{sizeKb} KB</Text>
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
// Collapsible section
// ---------------------------------------------------------------------------
function FileSection({
  title,
  icon,
  files,
  channelId,
  activeFile,
  onSelectFile,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ReactNode;
  files: { name: string; path: string; size: number; modified_at: number; section: string }[];
  channelId: string;
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  defaultOpen?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);

  if (files.length === 0) return null;

  return (
    <View style={{ marginBottom: 4 }}>
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
        <Text style={{ color: t.textDim, fontSize: 10 }}>({files.length})</Text>
      </Pressable>
      {open && (
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
    </View>
  );
}

// ---------------------------------------------------------------------------
// New file creator
// ---------------------------------------------------------------------------
function NewFileInput({ channelId, onCreated }: { channelId: string; onCreated: (path: string) => void }) {
  const t = useThemeTokens();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const writeMutation = useWriteChannelWorkspaceFile(channelId);

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
          setName("");
          setCreating(false);
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
            if (e.key === "Escape") { setCreating(false); setName(""); writeMutation.reset(); }
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
        <Pressable onPress={() => { setCreating(false); setName(""); writeMutation.reset(); }} style={{ padding: 4 }}>
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

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(channelId, {
    includeArchive: true,
    includeData: true,
  });

  const activeFiles = filesData?.files?.filter((f) => f.section === "active") ?? [];
  const archivedFiles = filesData?.files?.filter((f) => f.section === "archive") ?? [];
  const dataFiles = filesData?.files?.filter((f) => f.section === "data") ?? [];

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
        <Text style={{ color: t.text, fontSize: 12, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
          Files
        </Text>
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
              icon={<FileText size={11} color={t.accent} />}
              files={activeFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
            />
            <NewFileInput channelId={channelId} onCreated={onSelectFile} />
            <FileSection
              title="Archive"
              icon={<Archive size={11} color={t.textMuted} />}
              files={archivedFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
              defaultOpen={false}
            />
            <FileSection
              title="Data"
              icon={<Database size={11} color={t.textMuted} />}
              files={dataFiles}
              channelId={channelId}
              activeFile={activeFile}
              onSelectFile={onSelectFile}
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
    </View>
  );
}
