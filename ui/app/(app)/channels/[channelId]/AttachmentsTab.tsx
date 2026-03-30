import { useState, useRef } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Trash2, Upload, Paperclip, FileText, Image, Music, Video, File } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelAttachments,
  useChannelAttachmentStats,
  useUploadAttachment,
  useDeleteAttachment,
} from "@/src/api/hooks/useAttachments";
import { formatBytes } from "@/src/utils/format";

const TYPE_ICONS: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  image: Image,
  text: FileText,
  audio: Music,
  video: Video,
  file: File,
};

export function AttachmentsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const { data: stats } = useChannelAttachmentStats(channelId);
  const { data: attachments, isLoading } = useChannelAttachments(channelId);
  const upload = useUploadAttachment();
  const deleteMut = useDeleteAttachment();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [filterType, setFilterType] = useState("");

  const filtered = filterType
    ? attachments?.filter((a) => a.type === filterType)
    : attachments;

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await upload.mutateAsync({ file, channelId });
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleDelete = async (id: string, filename: string) => {
    if (!confirm(`Delete "${filename}"?`)) return;
    setDeletingId(id);
    try { await deleteMut.mutateAsync(id); } finally { setDeletingId(null); }
  };

  return (
    <View style={{ gap: 16 }}>
      {/* Stats bar */}
      {stats && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim,
          padding: "10px 14px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${t.surfaceRaised}`,
        }}>
          <span>Count: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{stats.total_count}</span></span>
          <span>With data: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{stats.with_file_data_count}</span></span>
          <span>Size: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{formatBytes(stats.total_size_bytes)}</span></span>
          {stats.effective_config.retention_days != null && (
            <span>Retention: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{stats.effective_config.retention_days}d</span></span>
          )}
        </div>
      )}

      {/* Upload + filter */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Pressable
          onPress={() => fileRef.current?.click()}
          disabled={upload.isPending}
          style={{
            flexDirection: "row", alignItems: "center", gap: 6,
            paddingHorizontal: 12, paddingVertical: 8, borderRadius: 6,
            backgroundColor: t.accent, opacity: upload.isPending ? 0.6 : 1,
          }}
        >
          <Upload size={14} color="#fff" />
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: 600 }}>
            {upload.isPending ? "Uploading..." : "Upload"}
          </Text>
        </Pressable>
        <input
          ref={fileRef}
          type="file"
          onChange={handleUpload}
          style={{ display: "none" }}
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          style={{
            padding: "6px 10px", borderRadius: 6,
            border: `1px solid ${t.surfaceRaised}`,
            background: t.inputBg, color: t.text, fontSize: 12,
          }}
        >
          <option value="">All types</option>
          {["image", "text", "audio", "video", "file"].map((tp) => (
            <option key={tp} value={tp}>{tp}</option>
          ))}
        </select>
        {upload.isError && (
          <span style={{ fontSize: 11, color: t.danger }}>{(upload.error as Error).message}</span>
        )}
      </div>

      {/* Attachment list */}
      {isLoading ? (
        <View style={{ padding: 24, alignItems: "center" }}>
          <ActivityIndicator color={t.accent} />
        </View>
      ) : !filtered?.length ? (
        <div style={{ padding: 24, textAlign: "center", color: t.textDim, fontSize: 13 }}>
          No attachments in this channel.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {filtered.map((att) => {
            const Icon = TYPE_ICONS[att.type] || Paperclip;
            return (
              <div
                key={att.id}
                style={{
                  padding: "10px 12px", background: t.inputBg, borderRadius: 8,
                  border: `1px solid ${t.surfaceRaised}`,
                  display: "flex", gap: 10, alignItems: "center",
                }}
              >
                <Icon size={16} color={t.textMuted} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{
                      fontSize: 12, fontWeight: 600, color: t.text,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {att.filename}
                    </span>
                    <span style={{
                      padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
                      background: t.accentSubtle, color: t.accent,
                    }}>
                      {att.type}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 10, fontSize: 10, color: t.textDim, marginTop: 2 }}>
                    <span>{formatBytes(att.size_bytes)}</span>
                    <span>{new Date(att.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <Pressable
                  onPress={() => handleDelete(att.id, att.filename)}
                  disabled={deletingId === att.id}
                  style={{ padding: 6, borderRadius: 6, opacity: deletingId === att.id ? 0.4 : 0.7 }}
                  className="hover:bg-surface-overlay"
                >
                  <Trash2 size={13} color={t.danger} />
                </Pressable>
              </div>
            );
          })}
        </div>
      )}
    </View>
  );
}
