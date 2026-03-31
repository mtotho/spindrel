import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { Link } from "expo-router";
import {
  Trash2, Paperclip, FileText, Image, Music, Video, File,
  AlertTriangle, Settings, ChevronLeft, ChevronRight, ChevronDown,
  Eye, Download, X, Layers, List,
} from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { useChannels } from "@/src/api/hooks/useChannels";
import {
  useAdminAttachments,
  useAttachmentGlobalStats,
  useDeleteAttachment,
  usePurgeAttachments,
} from "@/src/api/hooks/useAttachments";

import { formatBytes } from "@/src/utils/format";
import type { AttachmentAdmin } from "@/src/api/hooks/useAttachments";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getFileUrl(id: string): string {
  const { serverUrl } = useAuthStore.getState();
  const token = getAuthToken();
  return `${serverUrl}/api/v1/attachments/${id}/file${token ? `?token=${token}` : ""}`;
}

function canPreview(mime: string): boolean {
  return (
    mime.startsWith("image/") ||
    mime.startsWith("audio/") ||
    mime.startsWith("video/") ||
    mime === "application/pdf"
  );
}

function handlePreviewOrOpen(att: AttachmentAdmin, setPreview: (a: AttachmentAdmin) => void) {
  const url = getFileUrl(att.id);
  if (att.mime_type === "application/pdf") {
    window.open(url, "_blank");
  } else if (canPreview(att.mime_type)) {
    setPreview(att);
  }
}

function handleDownload(att: AttachmentAdmin) {
  const url = getFileUrl(att.id);
  const a = document.createElement("a");
  a.href = url;
  a.download = att.filename;
  a.click();
}

const TYPE_ICONS: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  image: Image,
  text: FileText,
  audio: Music,
  video: Video,
  file: File,
};

// ---------------------------------------------------------------------------
// Styled select
// ---------------------------------------------------------------------------

function FilterSelect({
  value,
  onChange,
  options,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder: string;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ position: "relative", display: "inline-flex" }}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          appearance: "none",
          WebkitAppearance: "none",
          padding: "6px 28px 6px 10px",
          borderRadius: 8,
          border: `1px solid ${value ? t.accent : t.surfaceRaised}`,
          background: value ? t.accentSubtle : t.inputBg,
          color: value ? t.accent : t.textMuted,
          fontSize: 12,
          fontWeight: 500,
          cursor: "pointer",
          outline: "none",
          lineHeight: "18px",
        }}
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <ChevronDown
        size={12}
        color={value ? t.accent : t.textMuted}
        style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" } as any}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toggle button
// ---------------------------------------------------------------------------

function ViewToggle({
  grouped,
  onToggle,
}: {
  grouped: boolean;
  onToggle: () => void;
}) {
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={onToggle}
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 8,
        paddingVertical: 5,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
        backgroundColor: t.inputBg,
      } as any}
      className="hover:bg-surface-overlay"
    >
      {grouped ? <Layers size={12} color={t.textMuted} /> : <List size={12} color={t.textMuted} />}
      <Text style={{ fontSize: 11, color: t.textMuted }}>{grouped ? "Grouped" : "Flat"}</Text>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Type badge
// ---------------------------------------------------------------------------

function TypeBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  return (
    <span style={{
      padding: "1px 7px", borderRadius: 4, fontSize: 10, fontWeight: 600,
      background: t.accentSubtle, color: t.accent, lineHeight: "16px",
    }}>
      {type}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Attachment row
// ---------------------------------------------------------------------------

function AttachmentRow({
  att,
  showChannel,
  deletingId,
  onDelete,
  onPreview,
}: {
  att: AttachmentAdmin;
  showChannel: boolean;
  deletingId: string | null;
  onDelete: (id: string, filename: string) => void;
  onPreview: (a: AttachmentAdmin) => void;
}) {
  const t = useThemeTokens();
  const Icon = TYPE_ICONS[att.type] || Paperclip;
  return (
    <div
      style={{
        padding: "10px 12px", background: t.inputBg, borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
        display: "flex", gap: 10, alignItems: "center",
        position: "relative",
      }}
      {...(att.description ? { title: att.description } : {})}
    >
      <Icon size={18} color={t.textMuted} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: t.text,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {att.filename}
          </span>
          <TypeBadge type={att.type} />
          {!att.has_file_data && (
            <span style={{
              padding: "1px 5px", borderRadius: 4, fontSize: 9, fontWeight: 600,
              background: "rgba(200,100,0,0.15)", color: t.warning,
            }}>
              no data
            </span>
          )}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, fontSize: 11, color: t.textDim, marginTop: 3 }}>
          <span style={{ fontFamily: "monospace", fontSize: 10 }}>{formatBytes(att.size_bytes)}</span>
          {showChannel && att.channel_name && (
            <Link href={`/channels/${att.channel_id}` as any}>
              <span style={{ color: t.accent, cursor: "pointer" }}>#{att.channel_name}</span>
            </Link>
          )}
          <span>{new Date(att.created_at).toLocaleDateString()}</span>
          {att.source_integration !== "web" && (
            <span style={{ fontStyle: "italic" }}>{att.source_integration}</span>
          )}
          {att.description && (
            <span style={{
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              maxWidth: 280, fontStyle: "italic", color: t.textMuted,
            }}>
              {att.description}
            </span>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: 1, flexShrink: 0 }}>
        {att.has_file_data && canPreview(att.mime_type) && (
          <Pressable
            onPress={() => handlePreviewOrOpen(att, onPreview)}
            style={{ padding: 7, borderRadius: 6, opacity: 0.7 }}
            className="hover:bg-surface-overlay"
          >
            <Eye size={14} color={t.accent} />
          </Pressable>
        )}
        {att.has_file_data && (
          <Pressable
            onPress={() => handleDownload(att)}
            style={{ padding: 7, borderRadius: 6, opacity: 0.7 }}
            className="hover:bg-surface-overlay"
          >
            <Download size={14} color={t.textMuted} />
          </Pressable>
        )}
        <Pressable
          onPress={() => onDelete(att.id, att.filename)}
          disabled={deletingId === att.id}
          style={{
            padding: 7, borderRadius: 6,
            opacity: deletingId === att.id ? 0.4 : 0.7,
          }}
          className="hover:bg-surface-overlay"
        >
          <Trash2 size={14} color={t.danger} />
        </Pressable>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channel group header
// ---------------------------------------------------------------------------

function ChannelGroupHeader({
  channelId,
  channelName,
  count,
  sizeBytes,
}: {
  channelId: string | null;
  channelName: string | null;
  count: number;
  sizeBytes: number;
}) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "8px 4px 4px",
    }}>
      {channelId ? (
        <Link href={`/channels/${channelId}` as any}>
          <span style={{ fontSize: 13, fontWeight: 700, color: t.accent, cursor: "pointer" }}>
            #{channelName || "unknown"}
          </span>
        </Link>
      ) : (
        <span style={{ fontSize: 13, fontWeight: 700, color: t.textDim }}>No channel</span>
      )}
      <span style={{ fontSize: 11, color: t.textDim }}>
        {count} file{count !== 1 ? "s" : ""}
      </span>
      <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
        {formatBytes(sizeBytes)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preview modal
// ---------------------------------------------------------------------------

function PreviewModal({ att, onClose }: { att: AttachmentAdmin; onClose: () => void }) {
  const t = useThemeTokens();
  const url = getFileUrl(att.id);

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 999,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: t.surface, borderRadius: 12, padding: 16,
        width: "90%", maxWidth: 720, maxHeight: "90vh",
        display: "flex", flexDirection: "column",
        border: `1px solid ${t.surfaceRaised}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <span style={{
            flex: 1, fontSize: 14, fontWeight: 600, color: t.text,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {att.filename}
          </span>
          <Pressable
            onPress={() => handleDownload(att)}
            style={{ padding: 6, borderRadius: 6 }}
            className="hover:bg-surface-overlay"
          >
            <Download size={14} color={t.accent} />
          </Pressable>
          <Pressable onPress={onClose} style={{ padding: 6, borderRadius: 6 }} className="hover:bg-surface-overlay">
            <X size={14} color={t.textMuted} />
          </Pressable>
        </div>
        <div style={{ flex: 1, overflow: "auto", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {att.mime_type.startsWith("image/") && (
            <img
              src={url}
              alt={att.filename}
              style={{ maxWidth: "100%", maxHeight: "70vh", borderRadius: 8, objectFit: "contain" }}
            />
          )}
          {att.mime_type.startsWith("audio/") && (
            <audio controls src={url} style={{ width: "100%" }} />
          )}
          {att.mime_type.startsWith("video/") && (
            <video controls src={url} style={{ maxWidth: "100%", maxHeight: "70vh", borderRadius: 8 }} />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Purge modal
// ---------------------------------------------------------------------------

function PurgeModal({
  onClose,
  channels,
}: {
  onClose: () => void;
  channels: Array<{ id: string; name: string }>;
}) {
  const t = useThemeTokens();
  const purge = usePurgeAttachments();
  const [beforeDate, setBeforeDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  });
  const [channelId, setChannelId] = useState("");
  const [type, setType] = useState("");
  const [fileDataOnly, setFileDataOnly] = useState(false);

  const handlePurge = async () => {
    if (!confirm(`Purge attachments before ${beforeDate}?`)) return;
    await purge.mutateAsync({
      before_date: new Date(beforeDate).toISOString(),
      channel_id: channelId || undefined,
      type: type || undefined,
      purge_file_data_only: fileDataOnly,
    });
    onClose();
  };

  const inputStyle = {
    padding: "8px 10px",
    borderRadius: 6,
    border: `1px solid ${t.surfaceRaised}`,
    background: t.inputBg,
    color: t.text,
    fontSize: 13,
    width: "100%",
    boxSizing: "border-box" as const,
  };

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 999,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: t.surface, borderRadius: 12, padding: 24,
        width: "90%", maxWidth: 420,
        border: `1px solid ${t.surfaceRaised}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <AlertTriangle size={18} color={t.danger} />
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Purge Attachments</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={{ fontSize: 11, color: t.textDim, display: "block", marginBottom: 4 }}>Before date</label>
            <input type="date" value={beforeDate} onChange={(e) => setBeforeDate(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: t.textDim, display: "block", marginBottom: 4 }}>Channel (optional)</label>
            <select value={channelId} onChange={(e) => setChannelId(e.target.value)} style={inputStyle}>
              <option value="">All channels</option>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.id}>{ch.name || ch.id}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 11, color: t.textDim, display: "block", marginBottom: 4 }}>Type (optional)</label>
            <select value={type} onChange={(e) => setType(e.target.value)} style={inputStyle}>
              <option value="">All types</option>
              {["image", "text", "audio", "video", "file"].map((tp) => (
                <option key={tp} value={tp}>{tp}</option>
              ))}
            </select>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: t.textMuted, cursor: "pointer" }}>
            <input type="checkbox" checked={fileDataOnly} onChange={(e) => setFileDataOnly(e.target.checked)} />
            Purge file data only (keep metadata)
          </label>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 20, justifyContent: "flex-end" }}>
          <Pressable onPress={onClose} style={{ paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6 }}>
            <Text style={{ color: t.textMuted, fontSize: 13 }}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={handlePurge}
            disabled={purge.isPending}
            style={{
              paddingHorizontal: 14, paddingVertical: 8, borderRadius: 6,
              backgroundColor: t.danger, opacity: purge.isPending ? 0.6 : 1,
            }}
          >
            <Text style={{ color: "#fff", fontSize: 13, fontWeight: 600 }}>
              {purge.isPending ? "Purging..." : "Purge"}
            </Text>
          </Pressable>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

export default function AttachmentsPage() {
  const t = useThemeTokens();
  const { refreshing, onRefresh } = usePageRefresh();
  const { data: channels } = useChannels();
  const { data: stats } = useAttachmentGlobalStats();
  const deleteMut = useDeleteAttachment();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showPurge, setShowPurge] = useState(false);
  const [previewAtt, setPreviewAtt] = useState<AttachmentAdmin | null>(null);
  const [filterChannel, setFilterChannel] = useState("");
  const [filterType, setFilterType] = useState("");
  const [groupByChannel, setGroupByChannel] = useState(true);
  const [page, setPage] = useState(0);

  const { data, isLoading } = useAdminAttachments({
    channelId: filterChannel || undefined,
    type: filterType || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  const channelList = useMemo(
    () => (channels || []).map((ch) => ({ id: ch.id, name: ch.display_name || ch.name || ch.client_id || ch.id })),
    [channels]
  );

  const channelOptions = useMemo(
    () => channelList.map((ch) => ({ value: ch.id, label: ch.name })),
    [channelList]
  );

  const typeOptions = useMemo(
    () => ["image", "text", "audio", "video", "file"].map((t) => ({ value: t, label: t })),
    []
  );

  // Group attachments by channel_id for grouped view
  const grouped = useMemo(() => {
    if (!data?.attachments.length) return [];
    const map = new Map<string, { channelId: string | null; channelName: string | null; items: AttachmentAdmin[] }>();
    for (const att of data.attachments) {
      const key = att.channel_id || "__none__";
      let group = map.get(key);
      if (!group) {
        group = { channelId: att.channel_id, channelName: att.channel_name, items: [] };
        map.set(key, group);
      }
      group.items.push(att);
    }
    return Array.from(map.values());
  }, [data?.attachments]);

  const handleDelete = async (id: string, filename: string) => {
    if (!confirm(`Delete attachment "${filename}"?`)) return;
    setDeletingId(id);
    try { await deleteMut.mutateAsync(id); } finally { setDeletingId(null); }
  };

  const showGrouped = groupByChannel && !filterChannel;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Attachments"
        subtitle={stats ? `${stats.total_count} total - ${formatBytes(stats.total_size_bytes)}` : undefined}
        right={
          <Pressable
            onPress={() => setShowPurge(true)}
            style={{
              paddingHorizontal: 12, paddingVertical: 7, borderRadius: 6,
              backgroundColor: t.danger,
            }}
          >
            <Text style={{ color: "#fff", fontSize: 12, fontWeight: 600 }}>Purge</Text>
          </Pressable>
        }
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ padding: 16, gap: 12, maxWidth: 800, width: "100%", boxSizing: "border-box" } as any}
      >
        {/* Stats row */}
        {stats && (
          <div style={{
            display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center",
            padding: "10px 14px", background: t.inputBg, borderRadius: 8,
            border: `1px solid ${t.surfaceRaised}`,
          }}>
            <div style={{ fontSize: 12, color: t.textDim }}>
              Total: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{stats.total_count}</span>
            </div>
            <div style={{ fontSize: 12, color: t.textDim }}>
              With data: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{stats.with_file_data_count}</span>
            </div>
            <div style={{ fontSize: 12, color: t.textDim }}>
              Size: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{formatBytes(stats.total_size_bytes)}</span>
            </div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {Object.entries(stats.by_type).map(([type, count]) => (
                <TypeBadge key={type} type={`${type}: ${count}`} />
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <FilterSelect
            value={filterChannel}
            onChange={(v) => { setFilterChannel(v); setPage(0); }}
            options={channelOptions}
            placeholder="All channels"
          />
          <FilterSelect
            value={filterType}
            onChange={(v) => { setFilterType(v); setPage(0); }}
            options={typeOptions}
            placeholder="All types"
          />
          <ViewToggle grouped={groupByChannel} onToggle={() => setGroupByChannel((g) => !g)} />
          {data && (
            <span style={{ fontSize: 11, color: t.textDim }}>{data.total} results</span>
          )}
          <div style={{ flex: 1 }} />
          <Link href={"/settings#Attachments" as any}>
            <div style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
              <Settings size={12} color={t.accent} />
              <span style={{ fontSize: 11, color: t.accent }}>Settings</span>
            </div>
          </Link>
        </div>

        {/* List */}
        {isLoading ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <ActivityIndicator color={t.accent} />
          </View>
        ) : !data?.attachments.length ? (
          <div style={{ padding: 24, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No attachments found.
          </div>
        ) : showGrouped ? (
          // Grouped by channel
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {grouped.map((group) => (
              <div key={group.channelId || "__none__"}>
                <ChannelGroupHeader
                  channelId={group.channelId}
                  channelName={group.channelName}
                  count={group.items.length}
                  sizeBytes={group.items.reduce((s, a) => s + a.size_bytes, 0)}
                />
                <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
                  {group.items.map((att) => (
                    <AttachmentRow
                      key={att.id}
                      att={att}
                      showChannel={false}
                      deletingId={deletingId}
                      onDelete={handleDelete}
                      onPreview={setPreviewAtt}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          // Flat list
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {data.attachments.map((att) => (
              <AttachmentRow
                key={att.id}
                att={att}
                showChannel={!filterChannel}
                deletingId={deletingId}
                onDelete={handleDelete}
                onPreview={setPreviewAtt}
              />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 12 }}>
            <Pressable
              onPress={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              style={{ padding: 8, borderRadius: 6, opacity: page === 0 ? 0.3 : 1 }}
            >
              <ChevronLeft size={16} color={t.textMuted} />
            </Pressable>
            <span style={{ fontSize: 12, color: t.textDim }}>
              {page + 1} / {totalPages}
            </span>
            <Pressable
              onPress={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              style={{ padding: 8, borderRadius: 6, opacity: page >= totalPages - 1 ? 0.3 : 1 }}
            >
              <ChevronRight size={16} color={t.textMuted} />
            </Pressable>
          </div>
        )}
      </RefreshableScrollView>

      {showPurge && (
        <PurgeModal
          onClose={() => setShowPurge(false)}
          channels={channelList}
        />
      )}

      {previewAtt && (
        <PreviewModal att={previewAtt} onClose={() => setPreviewAtt(null)} />
      )}
    </View>
  );
}
