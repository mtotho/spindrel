import { useState, useMemo, useCallback } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter, useLocalSearchParams } from "expo-router";
import { X, Search, ChevronDown, ChevronRight, AlertTriangle, Wrench, Clock, Zap } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useTurns, type TurnSummary, type TurnToolCall } from "@/src/api/hooks/useTurns";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------
function FilterBar({
  botFilter, setBotFilter,
  channelFilter, setChannelFilter,
  searchText, setSearchText,
  errorOnly, setErrorOnly,
  toolCallsOnly, setToolCallsOnly,
  bots, channels, hasFilters, clearFilters, isMobile, t,
}: {
  botFilter: string; setBotFilter: (v: string) => void;
  channelFilter: string; setChannelFilter: (v: string) => void;
  searchText: string; setSearchText: (v: string) => void;
  errorOnly: boolean; setErrorOnly: (v: boolean) => void;
  toolCallsOnly: boolean; setToolCallsOnly: (v: boolean) => void;
  bots: any[] | undefined;
  channels: any[] | undefined;
  hasFilters: boolean;
  clearFilters: () => void;
  isMobile: boolean;
  t: any;
}) {
  return (
    <div style={{
      display: "flex", gap: 8, padding: isMobile ? "8px 12px" : "8px 20px",
      borderBottom: `1px solid ${t.surfaceRaised}`, flexWrap: "wrap", alignItems: "center",
    }}>
      {/* Search */}
      <div style={{ position: "relative", flex: isMobile ? "1 1 100%" : "0 0 auto" }}>
        <Search size={12} style={{ position: "absolute", left: 8, top: 8, color: t.textDim }} />
        <input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search messages..."
          style={{
            background: t.surfaceRaised, color: t.text, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px 5px 26px", fontSize: 12, outline: "none",
            width: isMobile ? "100%" : 200,
          }}
        />
      </div>

      {/* Bot filter */}
      <select
        value={botFilter}
        onChange={(e) => setBotFilter(e.target.value)}
        style={{
          background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
        }}
      >
        <option value="">All Bots</option>
        {(bots ?? []).map((b: any) => (
          <option key={b.id} value={b.id}>{b.name || b.id}</option>
        ))}
      </select>

      {/* Channel filter */}
      <select
        value={channelFilter}
        onChange={(e) => setChannelFilter(e.target.value)}
        style={{
          background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
        }}
      >
        <option value="">All Channels</option>
        {(channels ?? []).map((ch: any) => (
          <option key={ch.id} value={ch.id}>{ch.name || ch.id}</option>
        ))}
      </select>

      {/* Toggle: errors only */}
      <button
        onClick={() => setErrorOnly(!errorOnly)}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: errorOnly ? "rgba(239,68,68,0.12)" : t.surfaceRaised,
          border: `1px solid ${errorOnly ? "#dc2626" : t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px", fontSize: 12,
          color: errorOnly ? "#dc2626" : t.textMuted, cursor: "pointer",
        }}
      >
        <AlertTriangle size={11} /> Errors
      </button>

      {/* Toggle: tool calls only */}
      <button
        onClick={() => setToolCallsOnly(!toolCallsOnly)}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: toolCallsOnly ? "rgba(99,102,241,0.12)" : t.surfaceRaised,
          border: `1px solid ${toolCallsOnly ? "#4f46e5" : t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px", fontSize: 12,
          color: toolCallsOnly ? "#4f46e5" : t.textMuted, cursor: "pointer",
        }}
      >
        <Wrench size={11} /> Tools
      </button>

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
  );
}

// ---------------------------------------------------------------------------
// Tool calls expandable section
// ---------------------------------------------------------------------------
function ToolCallsList({ toolCalls, t }: { toolCalls: TurnToolCall[]; t: any }) {
  const [expanded, setExpanded] = useState(false);
  if (toolCalls.length === 0) return null;

  return (
    <div style={{ marginTop: 6 }}>
      <button
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          background: "rgba(99,102,241,0.08)", border: "none", borderRadius: 4,
          padding: "3px 8px", fontSize: 11, color: "#4f46e5", cursor: "pointer",
        }}
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {toolCalls.length} tool call{toolCalls.length !== 1 ? "s" : ""}
      </button>
      {expanded && (
        <div style={{
          marginTop: 4, paddingLeft: 8,
          borderLeft: `2px solid rgba(99,102,241,0.2)`,
        }}>
          {toolCalls.map((tc, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "3px 0", fontSize: 11, color: t.textMuted,
            }}>
              <span style={{ fontWeight: 600, color: t.text }}>{tc.tool_name}</span>
              <span style={{ color: t.textDim, fontSize: 10 }}>{tc.tool_type}</span>
              {tc.duration_ms != null && (
                <span style={{ color: t.textDim }}>{fmtDuration(tc.duration_ms)}</span>
              )}
              {tc.error && (
                <span style={{
                  fontSize: 10, fontWeight: 600, color: "#dc2626",
                  background: "rgba(239,68,68,0.1)", padding: "1px 5px", borderRadius: 3,
                }}>ERR</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Turn card
// ---------------------------------------------------------------------------
function TurnCard({ turn, isMobile, bots, onPress, t }: {
  turn: TurnSummary;
  isMobile: boolean;
  bots: any[] | undefined;
  onPress: (cid: string) => void;
  t: any;
}) {
  const botName = bots?.find((b: any) => b.id === turn.bot_id)?.name || turn.bot_id || "";

  return (
    <div
      onClick={() => onPress(turn.correlation_id)}
      style={{
        padding: isMobile ? "10px 12px" : "12px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        cursor: "pointer",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = t.surfaceRaised)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {/* Header line: time + bot + channel + error badge */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        fontSize: 11, color: t.textDim, marginBottom: 4,
      }}>
        <span>{fmtDate(turn.created_at)} {fmtTime(turn.created_at)}</span>
        {botName && (
          <span style={{
            background: "rgba(99,102,241,0.1)", color: "#4f46e5",
            padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
          }}>{botName}</span>
        )}
        {turn.channel_name && (
          <span style={{
            background: "rgba(20,184,166,0.1)", color: "#0d9488",
            padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
          }}>{turn.channel_name}</span>
        )}
        {turn.model && !isMobile && (
          <span style={{ fontSize: 10, color: t.textDim }}>{turn.model}</span>
        )}
        {turn.has_error && (
          <span style={{
            display: "flex", alignItems: "center", gap: 3,
            background: "rgba(239,68,68,0.12)", color: "#dc2626",
            padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
          }}>
            <AlertTriangle size={10} /> Error
          </span>
        )}
      </div>

      {/* User message */}
      <div style={{
        fontSize: 13, color: t.text, lineHeight: "1.4",
        overflow: "hidden",
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
      }}>
        {turn.user_message || "(no message)"}
      </div>

      {/* Response preview */}
      {turn.response_preview && (
        <div style={{
          fontSize: 12, color: t.textMuted, marginTop: 4,
          lineHeight: "1.4",
          overflow: "hidden",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}>
          {turn.response_preview}
        </div>
      )}

      {/* Tool calls */}
      <ToolCallsList toolCalls={turn.tool_calls} t={t} />

      {/* Errors */}
      {turn.errors.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {turn.errors.map((err, i) => (
            <div key={i} style={{
              fontSize: 11, color: "#dc2626", background: "rgba(239,68,68,0.06)",
              padding: "4px 8px", borderRadius: 4, marginTop: 2,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {err.event_name && <span style={{ fontWeight: 600 }}>{err.event_name}: </span>}
              {err.message || "Unknown error"}
            </div>
          ))}
        </div>
      )}

      {/* Stats line */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        marginTop: 6, fontSize: 10, color: t.textDim,
      }}>
        {turn.duration_ms != null && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <Clock size={10} /> {fmtDuration(turn.duration_ms)}
          </span>
        )}
        {turn.total_tokens > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <Zap size={10} /> {fmtTokens(turn.total_tokens)} tokens
          </span>
        )}
        {turn.iterations > 0 && (
          <span>{turn.iterations} iter</span>
        )}
      </div>
    </div>
  );
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

  const PAGE_SIZE = 30;

  const [botFilter, setBotFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState(channelIdParam ?? "");
  const [searchText, setSearchText] = useState("");
  const [errorOnly, setErrorOnly] = useState(false);
  const [toolCallsOnly, setToolCallsOnly] = useState(false);
  const [beforeCursor, setBeforeCursor] = useState<string | undefined>(undefined);

  const params = useMemo(() => ({
    count: PAGE_SIZE,
    ...(botFilter ? { bot_id: botFilter } : {}),
    ...(channelFilter ? { channel_id: channelFilter } : {}),
    ...(searchText ? { search: searchText } : {}),
    ...(errorOnly ? { has_error: true as const } : {}),
    ...(toolCallsOnly ? { has_tool_calls: true as const } : {}),
    ...(beforeCursor ? { before: beforeCursor } : {}),
  }), [botFilter, channelFilter, searchText, errorOnly, toolCallsOnly, beforeCursor]);

  const { data, isLoading } = useTurns(params);
  const { data: bots } = useBots();
  const { data: channels } = useChannels();

  const hasFilters = !!(botFilter || channelFilter || searchText || errorOnly || toolCallsOnly);

  const clearFilters = useCallback(() => {
    setBotFilter("");
    setChannelFilter("");
    setSearchText("");
    setErrorOnly(false);
    setToolCallsOnly(false);
    setBeforeCursor(undefined);
  }, []);

  const handleFilterChange = useCallback((setter: (v: any) => void, value: any) => {
    setter(value);
    setBeforeCursor(undefined); // reset pagination on filter change
  }, []);

  const handleLoadMore = useCallback(() => {
    if (data?.turns.length) {
      const lastTurn = data.turns[data.turns.length - 1];
      setBeforeCursor(lastTurn.created_at);
    }
  }, [data]);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Logs"
        subtitle={data ? `${data.turns.length} turns` : "Loading..."}
      />

      <FilterBar
        botFilter={botFilter}
        setBotFilter={(v) => handleFilterChange(setBotFilter, v)}
        channelFilter={channelFilter}
        setChannelFilter={(v) => handleFilterChange(setChannelFilter, v)}
        searchText={searchText}
        setSearchText={(v) => handleFilterChange(setSearchText, v)}
        errorOnly={errorOnly}
        setErrorOnly={(v) => handleFilterChange(setErrorOnly, v)}
        toolCallsOnly={toolCallsOnly}
        setToolCallsOnly={(v) => handleFilterChange(setToolCallsOnly, v)}
        bots={bots}
        channels={channels}
        hasFilters={hasFilters}
        clearFilters={clearFilters}
        isMobile={isMobile}
        t={t}
      />

      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          <div style={{ display: "flex", flexDirection: "column" }}>
            {data?.turns.map((turn) => (
              <TurnCard
                key={turn.correlation_id}
                turn={turn}
                isMobile={isMobile}
                bots={bots}
                onPress={(cid) => router.push(`/admin/logs/${cid}` as any)}
                t={t}
              />
            ))}
            {data?.turns.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
                No turns found.
              </div>
            )}
          </div>

          {/* Load more */}
          {data && data.turns.length >= PAGE_SIZE && (
            <div style={{ display: "flex", justifyContent: "center", padding: "16px 20px" }}>
              <button
                onClick={handleLoadMore}
                style={{
                  background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 6, padding: "8px 24px", fontSize: 12, color: t.textMuted,
                  cursor: "pointer",
                }}
              >
                Load older turns
              </button>
            </div>
          )}
        </RefreshableScrollView>
      )}
    </View>
  );
}
