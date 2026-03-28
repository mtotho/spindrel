import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter, useLocalSearchParams } from "expo-router";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useLogs, type LogRow } from "@/src/api/hooks/useLogs";
import { useBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Badge colors
// ---------------------------------------------------------------------------
const TYPE_COLORS: Record<string, { bg: string; fg: string }> = {
  tool_call:            { bg: "rgba(99,102,241,0.12)",  fg: "#4f46e5" },
  memory_injection:     { bg: "rgba(168,85,247,0.12)",  fg: "#9333ea" },
  skill_context:        { bg: "rgba(20,184,166,0.12)",  fg: "#0d9488" },
  knowledge_context:    { bg: "rgba(59,130,246,0.12)",  fg: "#2563eb" },
  tool_retrieval:       { bg: "rgba(234,179,8,0.12)",   fg: "#ca8a04" },
  context_compressed:   { bg: "rgba(132,204,22,0.12)",  fg: "#65a30d" },
  context_breakdown:    { bg: "rgba(6,182,212,0.12)",   fg: "#0891b2" },
  token_usage:          { bg: "rgba(107,114,128,0.12)", fg: "#6b7280" },
  error:                { bg: "rgba(239,68,68,0.12)",   fg: "#dc2626" },
  harness:              { bg: "rgba(234,179,8,0.12)",   fg: "#b45309" },
  response:             { bg: "rgba(34,197,94,0.12)",   fg: "#16a34a" },
};

const EVENT_TYPE_OPTIONS = [
  { label: "All Types", value: "" },
  { label: "Tool Calls", value: "tool_call" },
  { label: "Memory", value: "memory_injection" },
  { label: "Skill", value: "skill_context" },
  { label: "Knowledge", value: "knowledge_context" },
  { label: "Tool Retrieval", value: "tool_retrieval" },
  { label: "Compressed", value: "context_compressed" },
  { label: "Breakdown", value: "context_breakdown" },
  { label: "Tokens", value: "token_usage" },
  { label: "Error", value: "error" },
  { label: "Harness", value: "harness" },
  { label: "Response", value: "response" },
];

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------
function TypeBadge({ type }: { type: string }) {
  const c = TYPE_COLORS[type] ?? { bg: "rgba(107,114,128,0.12)", fg: "#6b7280" };
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
      background: c.bg, color: c.fg, whiteSpace: "nowrap",
    }}>
      {type}
    </span>
  );
}

function getRowName(row: LogRow): string {
  if (row.kind === "tool_call") return row.tool_name || "—";
  return row.event_name || row.event_type || "—";
}

function getRowType(row: LogRow): string {
  return row.kind === "tool_call" ? "tool_call" : row.event_type || "trace_event";
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function LogsScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { channel_id: channelIdParam } = useLocalSearchParams<{ channel_id?: string }>();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [sessionFilter, setSessionFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState(channelIdParam ?? "");

  const params = useMemo(() => ({
    page,
    page_size: 50,
    ...(eventType ? { event_type: eventType } : {}),
    ...(botFilter ? { bot_id: botFilter } : {}),
    ...(sessionFilter ? { session_id: sessionFilter } : {}),
    ...(channelFilter ? { channel_id: channelFilter } : {}),
  }), [page, eventType, botFilter, sessionFilter, channelFilter]);

  const { data, isLoading } = useLogs(params);
  const { data: bots } = useBots();

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;
  const hasFilters = !!(eventType || botFilter || sessionFilter || channelFilter);

  const clearFilters = () => {
    setEventType("");
    setBotFilter("");
    setSessionFilter("");
    setChannelFilter("");
    setPage(1);
  };

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Logs"
        subtitle={data ? `${data.total} entries` : "Loading..."}
      />

      {/* Filter bar */}
      <div style={{
        display: "flex", gap: 8, padding: isMobile ? "8px 12px" : "8px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`, flexWrap: "wrap", alignItems: "center",
      }}>
        <select
          value={eventType}
          onChange={(e) => { setEventType(e.target.value); setPage(1); }}
          style={{
            background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
          }}
        >
          {EVENT_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <select
          value={botFilter}
          onChange={(e) => { setBotFilter(e.target.value); setPage(1); }}
          style={{
            background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
          }}
        >
          <option value="">All Bots</option>
          {(data?.bot_ids ?? []).map((b) => (
            <option key={b} value={b}>{bots?.find((x: any) => x.id === b)?.name || b}</option>
          ))}
        </select>

        <input
          value={sessionFilter}
          onChange={(e) => { setSessionFilter(e.target.value); setPage(1); }}
          placeholder="Session ID..."
          style={{
            background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
            width: isMobile ? "100%" : 200,
          }}
        />

        {hasFilters && (
          <button
            onClick={clearFilters}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              background: "none", border: "none", color: t.textDim, cursor: "pointer",
              fontSize: 12,
            }}
          >
            <X size={12} /> Clear
          </button>
        )}
      </div>

      {/* Column headers */}
      <div style={{
        display: "flex", gap: 12,
        padding: isMobile ? "6px 12px" : "6px 20px",
        borderBottom: `1px solid ${t.surfaceOverlay}`,
        fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}>
        <span style={{ width: isMobile ? 60 : 120 }}>Time</span>
        <span style={{ width: 120 }}>Type</span>
        <span style={{ flex: 1, minWidth: 0 }}>Name / Detail</span>
        {!isMobile && <span style={{ width: 90 }}>Bot</span>}
        <span style={{ width: isMobile ? 70 : 100 }}>Correlation</span>
        {!isMobile && <span style={{ width: 60, textAlign: "right" }}>Duration</span>}
        <span style={{ width: 40, textAlign: "right" }}>Status</span>
      </div>

      {/* Body */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          <div style={{ display: "flex", flexDirection: "column" }}>
            {data?.rows.map((row) => (
              <LogRowItem key={row.id} row={row} isMobile={isMobile} onCorrelationPress={(cid) => {
                router.push(`/admin/logs/${cid}` as any);
              }} />
            ))}
            {data?.rows.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
                No log entries found.
              </div>
            )}
          </div>
        </RefreshableScrollView>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{
          display: "flex", justifyContent: "center", alignItems: "center", gap: 12,
          padding: "10px 20px", borderTop: `1px solid ${t.surfaceOverlay}`,
        }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            style={{
              background: "none", border: "none", cursor: page <= 1 ? "default" : "pointer",
              color: page <= 1 ? t.surfaceBorder : t.textMuted, padding: 4,
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontSize: 12, color: t.textDim }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            style={{
              background: "none", border: "none", cursor: page >= totalPages ? "default" : "pointer",
              color: page >= totalPages ? t.surfaceBorder : t.textMuted, padding: 4,
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Row item
// ---------------------------------------------------------------------------
function LogRowItem({ row, isMobile, onCorrelationPress }: {
  row: LogRow;
  isMobile: boolean;
  onCorrelationPress: (cid: string) => void;
}) {
  const t = useThemeTokens();
  const rowType = getRowType(row);
  const name = getRowName(row);
  const hasError = !!row.error;

  return (
    <div
      style={{
        display: "flex", gap: 12, alignItems: "center",
        padding: isMobile ? "6px 12px" : "6px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        fontSize: 12,
        cursor: row.correlation_id ? "pointer" : "default",
      }}
      onClick={() => row.correlation_id && onCorrelationPress(row.correlation_id)}
    >
      {/* Time */}
      <span style={{ width: isMobile ? 60 : 120, color: t.textDim, fontSize: 11, flexShrink: 0 }}>
        {isMobile ? fmtTime(row.created_at) : (
          <>
            <span style={{ color: t.textDim }}>{fmtDate(row.created_at)} </span>
            {fmtTime(row.created_at)}
          </>
        )}
      </span>

      {/* Type badge */}
      <span style={{ width: 120, flexShrink: 0 }}>
        <TypeBadge type={rowType} />
      </span>

      {/* Name */}
      <span style={{
        flex: 1, minWidth: 0, color: t.text, overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {name}
        {row.kind === "tool_call" && row.tool_type && (
          <span style={{ color: t.textDim, marginLeft: 6, fontSize: 10 }}>({row.tool_type})</span>
        )}
        {row.kind === "trace_event" && row.count != null && (
          <span style={{ color: t.textDim, marginLeft: 6, fontSize: 10 }}>({row.count})</span>
        )}
      </span>

      {/* Bot */}
      {!isMobile && (
        <span style={{ width: 90, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>
          {row.bot_id || "—"}
        </span>
      )}

      {/* Correlation */}
      <span style={{ width: isMobile ? 70 : 100, color: t.textDim, fontFamily: "monospace", fontSize: 10, flexShrink: 0 }}>
        {row.correlation_id?.substring(0, isMobile ? 8 : 12) || "—"}
      </span>

      {/* Duration */}
      {!isMobile && (
        <span style={{ width: 60, textAlign: "right", color: t.textDim, flexShrink: 0 }}>
          {fmtDuration(row.duration_ms)}
        </span>
      )}

      {/* Status */}
      <span style={{ width: 40, textAlign: "right", flexShrink: 0 }}>
        {hasError ? (
          <span style={{ fontSize: 10, fontWeight: 600, color: "#dc2626" }}>ERR</span>
        ) : (
          <span style={{ fontSize: 10, fontWeight: 600, color: "#16a34a" }}>OK</span>
        )}
      </span>
    </div>
  );
}
