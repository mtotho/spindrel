import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useRef } from "react";
import { Trash2, Upload, Paperclip, FileText, Image, Music, Video, File } from "lucide-react";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import {
  useChannelAttachments,
  useChannelAttachmentStats,
  useUploadAttachment,
  useDeleteAttachment,
} from "@/src/api/hooks/useAttachments";
import { EmptyState, Section, SelectInput } from "@/src/components/shared/FormControls";
import { ActionButton, SettingsControlRow, SettingsStatGrid, StatusBadge } from "@/src/components/shared/SettingsControls";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { formatBytes } from "@/src/utils/format";

const TYPE_ICONS: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  image: Image,
  text: FileText,
  audio: Music,
  video: Video,
  file: File,
};

export function AttachmentsTab({ channelId }: { channelId: string }) {
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
        <div className={`flex flex-wrap items-center gap-2 ${isMobile ? "justify-start" : "justify-end"}`}>
          <div className="min-w-[152px]">
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
            icon={<Upload size={13} />}
          />
          <input
            ref={fileRef}
            type="file"
            onChange={handleUpload}
            className="hidden"
          />
        </div>
      }
    >
      {stats && (
        <SettingsStatGrid
          items={[
            { label: "Count", value: String(stats.total_count) },
            { label: "With data", value: String(stats.with_file_data_count) },
            { label: "Size", value: formatBytes(stats.total_size_bytes) },
            ...(stats.effective_config.retention_days != null
              ? [{ label: "Retention", value: `${stats.effective_config.retention_days}d` }]
              : []),
          ]}
        />
      )}

      {upload.isError && (
        <span className="text-[11px] text-danger">{(upload.error as Error).message}</span>
      )}

      {isLoading ? (
        <div className="flex items-center p-6">
          <Spinner />
        </div>
      ) : !filtered?.length ? (
        <EmptyState message={filterType ? "No attachments match this filter." : "No attachments in this channel."} />
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((att) => {
            const Icon = TYPE_ICONS[att.type] || Paperclip;
            return (
              <SettingsControlRow
                key={att.id}
                className="flex items-center gap-2.5"
              >
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-overlay/60">
                  <Icon size={15} className="text-text-muted" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="min-w-0 truncate text-[12px] font-semibold text-text">
                      {att.filename}
                    </span>
                    <StatusBadge label={att.type} variant="info" />
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-2.5 text-[10px] text-text-dim">
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
              </SettingsControlRow>
            );
          })}
        </div>
      )}
      <ConfirmDialogSlot />
    </Section>
  );
}
