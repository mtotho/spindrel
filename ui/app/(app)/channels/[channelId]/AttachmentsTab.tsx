import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useRef } from "react";
import { Trash2, Upload, Paperclip, FileText, Image, Music, Video, File } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import {
  useChannelAttachments,
  useChannelAttachmentStats,
  useUploadAttachment,
  useDeleteAttachment,
} from "@/src/api/hooks/useAttachments";
import { SelectInput } from "@/src/components/shared/FormControls";
import { ActionButton } from "@/src/components/shared/SettingsControls";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
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
  const isMobile = useIsMobile();
  const { data: stats } = useChannelAttachmentStats(channelId);
  const { data: attachments, isLoading } = useChannelAttachments(channelId);
  const upload = useUploadAttachment();
  const deleteMut = useDeleteAttachment();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [filterType, setFilterType] = useState("");
  const { confirm, ConfirmDialogSlot } = useConfirm();

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
    const ok = await confirm(`Delete "${filename}"?`, {
      title: "Delete attachment",
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    setDeletingId(id);
    try { await deleteMut.mutateAsync(id); } finally { setDeletingId(null); }
  };

  return (
    <div style={{ display: "flex", gap: 16 }}>
      {/* Stats bar */}
      {stats && (
        <div style={{
          display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim,
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
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", flexDirection: isMobile ? "column" as any : "row" as any }}>
        <div style={{ display: "flex", flexDirection: "row", gap: 10, alignItems: "center" }}>
          <ActionButton
            label={upload.isPending ? "Uploading..." : "Upload"}
            onPress={() => fileRef.current?.click()}
            disabled={upload.isPending}
            size="small"
            icon={<Upload size={13} color="#fff" />}
          />
          <input
            ref={fileRef}
            type="file"
            onChange={handleUpload}
            style={{ display: "none" }}
          />
          <div style={{ minWidth: 120 }}>
            <SelectInput
              value={filterType}
              onChange={setFilterType}
              options={[
                { label: "All types", value: "" },
                { label: "Image", value: "image" },
                { label: "Text", value: "text" },
                { label: "Audio", value: "audio" },
                { label: "Video", value: "video" },
                { label: "File", value: "file" },
              ]}
            />
          </div>
        </div>
        {upload.isError && (
          <span style={{ fontSize: 11, color: t.danger }}>{(upload.error as Error).message}</span>
        )}
      </div>

      {/* Attachment list */}
      {isLoading ? (
        <div style={{ display: "flex", padding: 24, alignItems: "center" }}>
          <Spinner color={t.accent} />
        </div>
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
                  display: "flex", flexDirection: "row", gap: 10, alignItems: "center",
                }}
              >
                <Icon size={16} color={t.textMuted} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
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
                  <div style={{ display: "flex", flexDirection: "row", gap: 10, fontSize: 10, color: t.textDim, marginTop: 2 }}>
                    <span>{formatBytes(att.size_bytes)}</span>
                    <span>{new Date(att.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <button type="button"
                  onClick={() => handleDelete(att.id, att.filename)}
                  disabled={deletingId === att.id}
                  style={{ padding: 10, borderRadius: 6, opacity: deletingId === att.id ? 0.4 : 0.7 }}
                  className="hover:bg-surface-overlay"
                >
                  <Trash2 size={13} color={t.danger} />
                </button>
              </div>
            );
          })}
        </div>
      )}
      <ConfirmDialogSlot />
    </div>
  );
}
