import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter, useLocalSearchParams } from "expo-router";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useLogs, type LogRow } from "@/src/api/hooks/useLogs";
import { useBots } from "@/src/api/hooks/useBots";

// ---------------------------------------------------------------------------
// Badge colors
// ---------------------------------------------------------------------------
const TYPE_COLORS: Record<string, { bg: string; fg: string }> = {
  tool_call:            { bg: "#312e81", fg: "#a5b4fc" },
  memory_injection:     { bg: "#3b0764", fg: "#d8b4fe" },
  skill_context:        { bg: "#134e4a", fg: "#5eead4" },
  knowledge_context:    { bg: "#1e3a5f", fg: "#93c5fd" },
  tool_retrieval:       { bg: "#713f12", fg: "#fde047" },
  context_compressed:   { bg: "#365314", fg: "#bef264" },
  context_breakdown:    { bg: "#164e63", fg: "#67e8f9" },
  token_usage:          { bg: "#333",    fg: "#999"    },
  error:                { bg: "#7f1d1d", fg: "#fca5a5" },
  harness:              { bg: "#78350f", fg: "#fbbf24" },
  response:             { bg: "#166534", fg: "#86efac" },
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
  const c = TYPE_COLORS[type] ?? { bg: "#333", fg: "#999" };
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
        borderBottom: "1px solid #1a1a1a", flexWrap: "wrap", alignItems: "center",
      }}>
        <select
          value={eventType}
          onChange={(e) => { setEventType(e.target.value); setPage(1); }}
          style={{
            background: "#1a1a1a", color: "#999", border: "1px solid #333",
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
            background: "#1a1a1a", color: "#999", border: "1px solid #333",
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
            background: "#1a1a1a", color: "#999", border: "1px solid #333",
            borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
            width: isMobile ? "100%" : 200,
          }}
        />

        {hasFilters && (
          <button
            onClick={clearFilters}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              background: "none", border: "none", color: "#666", cursor: "pointer",
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
        borderBottom: "1px solid #2a2a2a",
        fontSize: 10, fontWeight: 600, color: "#555", textTransform: "uppercase",
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
              <div style={{ padding: 40, textAlign: "center", color: "#666", fontSize: 13 }}>
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
          padding: "10px 20px", borderTop: "1px solid #2a2a2a",
        }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            style={{
              background: "none", border: "none", cursor: page <= 1 ? "default" : "pointer",
              color: page <= 1 ? "#333" : "#999", padding: 4,
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontSize: 12, color: "#666" }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            style={{
              background: "none", border: "none", cursor: page >= totalPages ? "default" : "pointer",
              color: page >= totalPages ? "#333" : "#999", padding: 4,
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
  const rowType = getRowType(row);
  const name = getRowName(row);
  const hasError = !!row.error;

  return (
    <div
      style={{
        display: "flex", gap: 12, alignItems: "center",
        padding: isMobile ? "6px 12px" : "6px 20px",
        borderBottom: "1px solid #1a1a1a",
        fontSize: 12,
        cursor: row.correlation_id ? "pointer" : "default",
      }}
      onClick={() => row.correlation_id && onCorrelationPress(row.correlation_id)}
    >
      {/* Time */}
      <span style={{ width: isMobile ? 60 : 120, color: "#666", fontSize: 11, flexShrink: 0 }}>
        {isMobile ? fmtTime(row.created_at) : (
          <>
            <span style={{ color: "#555" }}>{fmtDate(row.created_at)} </span>
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
        flex: 1, minWidth: 0, color: "#e5e5e5", overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {name}
        {row.kind === "tool_call" && row.tool_type && (
          <span style={{ color: "#555", marginLeft: 6, fontSize: 10 }}>({row.tool_type})</span>
        )}
        {row.kind === "trace_event" && row.count != null && (
          <span style={{ color: "#555", marginLeft: 6, fontSize: 10 }}>({row.count})</span>
        )}
      </span>

      {/* Bot */}
      {!isMobile && (
        <span style={{ width: 90, color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>
          {row.bot_id || "—"}
        </span>
      )}

      {/* Correlation */}
      <span style={{ width: isMobile ? 70 : 100, color: "#555", fontFamily: "monospace", fontSize: 10, flexShrink: 0 }}>
        {row.correlation_id?.substring(0, isMobile ? 8 : 12) || "—"}
      </span>

      {/* Duration */}
      {!isMobile && (
        <span style={{ width: 60, textAlign: "right", color: "#666", flexShrink: 0 }}>
          {fmtDuration(row.duration_ms)}
        </span>
      )}

      {/* Status */}
      <span style={{ width: 40, textAlign: "right", flexShrink: 0 }}>
        {hasError ? (
          <span style={{ fontSize: 10, fontWeight: 600, color: "#fca5a5" }}>ERR</span>
        ) : (
          <span style={{ fontSize: 10, fontWeight: 600, color: "#86efac" }}>OK</span>
        )}
      </span>
    </div>
  );
}
