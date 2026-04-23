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
import { EmptyState, Section, SelectInput } from "@/src/components/shared/FormControls";
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
    <Section
      title="Attachments"
      description="Files uploaded directly to this channel. They remain available to the channel and can be filtered by type."
      action={
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: isMobile ? "flex-start" : "flex-end" }}>
          <div style={{ minWidth: 152 }}>
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
        </div>
      }
    >
      {stats && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "repeat(2, minmax(0, 1fr))" : "repeat(4, minmax(0, 1fr))",
            gap: 8,
          }}
        >
          {[
            { label: "Count", value: String(stats.total_count) },
            { label: "With data", value: String(stats.with_file_data_count) },
            { label: "Size", value: formatBytes(stats.total_size_bytes) },
            ...(stats.effective_config.retention_days != null
              ? [{ label: "Retention", value: `${stats.effective_config.retention_days}d` }]
              : []),
          ].map((item) => (
            <div
              key={item.label}
              style={{
                padding: "10px 12px",
                borderRadius: 6,
                border: `1px solid ${t.surfaceBorder}`,
                background: t.surface,
              }}
            >
              <div style={{ fontSize: 11, color: t.textDim }}>{item.label}</div>
              <div style={{ marginTop: 4, fontSize: 14, fontWeight: 600, color: t.text, fontFamily: "monospace" }}>
                {item.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {upload.isError && (
        <span style={{ fontSize: 11, color: t.danger }}>{(upload.error as Error).message}</span>
      )}

      {isLoading ? (
        <div style={{ display: "flex", padding: 24, alignItems: "center" }}>
          <Spinner color={t.accent} />
        </div>
      ) : !filtered?.length ? (
        <EmptyState message={filterType ? "No attachments match this filter." : "No attachments in this channel."} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((att) => {
            const Icon = TYPE_ICONS[att.type] || Paperclip;
            return (
              <div
                key={att.id}
                style={{
                padding: "10px 12px",
                background: t.surfaceRaised,
                borderRadius: 6,
                border: `1px solid ${t.surfaceBorder}`,
                  display: "flex",
                  flexDirection: "row",
                  gap: 10,
                  alignItems: "center",
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 6,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: t.surfaceOverlay,
                    flexShrink: 0,
                  }}
                >
                  <Icon size={15} color={t.textMuted} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: t.text,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      minWidth: 0,
                    }}>
                      {att.filename}
                    </span>
                    <span style={{
                      padding: "2px 7px",
                      borderRadius: 999,
                      fontSize: 9,
                      fontWeight: 600,
                      background: t.accentSubtle,
                      color: t.accent,
                    }}>
                      {att.type}
                    </span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "row", gap: 10, fontSize: 10, color: t.textDim, marginTop: 3, flexWrap: "wrap" }}>
                    <span>{formatBytes(att.size_bytes)}</span>
                    <span>{new Date(att.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
                <ActionButton
                  label="Delete"
                  onPress={() => handleDelete(att.id, att.filename)}
                  disabled={deletingId === att.id}
                  variant="danger"
                  size="small"
                  icon={<Trash2 size={12} />}
                />
              </div>
            );
          })}
        </div>
      )}
      <ConfirmDialogSlot />
    </Section>
  );
}
