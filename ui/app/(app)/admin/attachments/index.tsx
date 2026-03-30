import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { Link } from "expo-router";
import {
  Trash2, Paperclip, FileText, Image, Music, Video, File,
  AlertTriangle, Settings, ChevronLeft, ChevronRight,
} from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannels } from "@/src/api/hooks/useChannels";
import {
  useAdminAttachments,
  useAttachmentGlobalStats,
  useDeleteAttachment,
  usePurgeAttachments,
} from "@/src/api/hooks/useAttachments";

import { formatBytes } from "@/src/utils/format";

const TYPE_ICONS: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  image: Image,
  text: FileText,
  audio: Music,
  video: Video,
  file: File,
};

function TypeBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
      background: t.accentSubtle, color: t.accent,
    }}>
      {type}
    </span>
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
  const [filterChannel, setFilterChannel] = useState("");
  const [filterType, setFilterType] = useState("");
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

  const handleDelete = async (id: string, filename: string) => {
    if (!confirm(`Delete attachment "${filename}"?`)) return;
    setDeletingId(id);
    try { await deleteMut.mutateAsync(id); } finally { setDeletingId(null); }
  };

  const selectStyle = {
    padding: "6px 10px",
    borderRadius: 6,
    border: `1px solid ${t.surfaceRaised}`,
    background: t.inputBg,
    color: t.text,
    fontSize: 12,
  };

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
        contentContainerStyle={{ padding: 16, gap: 16, maxWidth: 800, width: "100%", boxSizing: "border-box" } as any}
      >
        {/* Stats row */}
        {stats && (
          <div style={{
            display: "flex", flexWrap: "wrap", gap: 12,
            padding: "12px 16px", background: t.inputBg, borderRadius: 8,
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
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {Object.entries(stats.by_type).map(([type, count]) => (
                <span key={type} style={{
                  padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
                  background: t.accentSubtle, color: t.accent,
                }}>
                  {type}: {count}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <select
            value={filterChannel}
            onChange={(e) => { setFilterChannel(e.target.value); setPage(0); }}
            style={selectStyle}
          >
            <option value="">All channels</option>
            {channelList.map((ch) => (
              <option key={ch.id} value={ch.id}>{ch.name}</option>
            ))}
          </select>
          <select
            value={filterType}
            onChange={(e) => { setFilterType(e.target.value); setPage(0); }}
            style={selectStyle}
          >
            <option value="">All types</option>
            {["image", "text", "audio", "video", "file"].map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
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
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.attachments.map((att) => {
              const Icon = TYPE_ICONS[att.type] || Paperclip;
              return (
                <div
                  key={att.id}
                  style={{
                    padding: "12px 14px", background: t.inputBg, borderRadius: 8,
                    border: `1px solid ${t.surfaceRaised}`,
                    display: "flex", gap: 12, alignItems: "center",
                  }}
                >
                  <Icon size={20} color={t.textMuted} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {att.filename}
                      </span>
                      <TypeBadge type={att.type} />
                      {!att.has_file_data && (
                        <span style={{ padding: "2px 6px", borderRadius: 4, fontSize: 9, fontWeight: 600, background: "rgba(200,100,0,0.15)", color: t.warning }}>
                          no data
                        </span>
                      )}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 11, color: t.textDim, marginTop: 4 }}>
                      <span>{formatBytes(att.size_bytes)}</span>
                      {att.channel_name && (
                        <Link href={`/channels/${att.channel_id}` as any}>
                          <span style={{ color: t.accent, cursor: "pointer" }}>#{att.channel_name}</span>
                        </Link>
                      )}
                      <span>{new Date(att.created_at).toLocaleDateString()}</span>
                      {att.source_integration !== "web" && (
                        <span style={{ fontStyle: "italic" }}>{att.source_integration}</span>
                      )}
                    </div>
                  </div>
                  <Pressable
                    onPress={() => handleDelete(att.id, att.filename)}
                    disabled={deletingId === att.id}
                    style={{
                      padding: 8, borderRadius: 6, flexShrink: 0,
                      opacity: deletingId === att.id ? 0.4 : 0.7,
                    }}
                    className="hover:bg-surface-overlay"
                  >
                    <Trash2 size={14} color={t.danger} />
                  </Pressable>
                </div>
              );
            })}
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
    </View>
  );
}
