import { useState, useMemo, useCallback } from "react";
import { Text, Pressable, ActivityIndicator, useWindowDimensions } from "react-native";
import { useRouter } from "expo-router";
import { ExternalLink, Search, AlertTriangle, Wrench, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { EmptyState } from "@/src/components/shared/FormControls";
import { TurnCard } from "@/src/components/shared/TurnCard";
import { useTurns } from "@/src/api/hooks/useTurns";

const PAGE_SIZE = 20;

export function LogsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  const [searchText, setSearchText] = useState("");
  const [errorOnly, setErrorOnly] = useState(false);
  const [toolCallsOnly, setToolCallsOnly] = useState(false);
  const [beforeCursor, setBeforeCursor] = useState<string | undefined>(undefined);

  const params = useMemo(() => ({
    count: PAGE_SIZE,
    channel_id: channelId,
    ...(searchText ? { search: searchText } : {}),
    ...(errorOnly ? { has_error: true as const } : {}),
    ...(toolCallsOnly ? { has_tool_calls: true as const } : {}),
    ...(beforeCursor ? { before: beforeCursor } : {}),
  }), [channelId, searchText, errorOnly, toolCallsOnly, beforeCursor]);

  const { data, isLoading } = useTurns(params);

  const hasFilters = !!(searchText || errorOnly || toolCallsOnly);

  const clearFilters = useCallback(() => {
    setSearchText("");
    setErrorOnly(false);
    setToolCallsOnly(false);
    setBeforeCursor(undefined);
  }, []);

  const handleLoadMore = useCallback(() => {
    if (data?.turns.length) {
      const lastTurn = data.turns[data.turns.length - 1];
      setBeforeCursor(lastTurn.created_at);
    }
  }, [data]);

  if (isLoading && !data) return <ActivityIndicator color={t.accent} />;

  return (
    <>
      {/* Compact filter bar */}
      <div style={{
        display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center",
        marginBottom: 12,
      }}>
        <div style={{ position: "relative", flex: isMobile ? "1 1 100%" : "0 0 auto" }}>
          <Search size={12} style={{ position: "absolute", left: 8, top: 8, color: t.textDim }} />
          <input
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setBeforeCursor(undefined); }}
            placeholder="Search messages..."
            style={{
              background: t.surfaceRaised, color: t.text, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6, padding: "5px 10px 5px 26px", fontSize: 12, outline: "none",
              width: isMobile ? "100%" : 200,
            }}
          />
        </div>

        <button
          onClick={() => { setErrorOnly(!errorOnly); setBeforeCursor(undefined); }}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            background: errorOnly ? t.dangerSubtle : t.surfaceRaised,
            border: `1px solid ${errorOnly ? t.danger : t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px", fontSize: 12,
            color: errorOnly ? t.danger : t.textMuted, cursor: "pointer",
          }}
        >
          <AlertTriangle size={11} /> Errors
        </button>

        <button
          onClick={() => { setToolCallsOnly(!toolCallsOnly); setBeforeCursor(undefined); }}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            background: toolCallsOnly ? t.purpleSubtle : t.surfaceRaised,
            border: `1px solid ${toolCallsOnly ? t.purple : t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px", fontSize: 12,
            color: toolCallsOnly ? t.purple : t.textMuted, cursor: "pointer",
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

      {/* Turns list */}
      {data && data.turns.length > 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 6 }}>
          {data.turns.length}{data.turns.length >= PAGE_SIZE ? "+" : ""} turns
        </div>
      )}
      <div style={{
        display: "flex", flexDirection: "column",
        borderRadius: 8, overflow: "hidden",
        border: `1px solid ${t.surfaceRaised}`,
      }}>
        {data?.turns.map((turn) => (
          <TurnCard
            key={turn.correlation_id}
            turn={turn}
            isMobile={isMobile}
            onPress={(cid) => router.push(`/admin/logs/${cid}` as any)}
            showBotBadge={false}
            showChannelBadge={false}
          />
        ))}
        {data?.turns.length === 0 && (
          <EmptyState message="No turns found." />
        )}
      </div>

      {/* Load more */}
      {data && data.turns.length >= PAGE_SIZE && (
        <div style={{ display: "flex", justifyContent: "center", padding: "16px 0" }}>
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

      {/* Link to admin logs */}
      <Pressable
        onPress={() => router.push(`/admin/logs?channel_id=${channelId}` as any)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          alignSelf: "flex-start", marginTop: 4,
        }}
      >
        <Text style={{ fontSize: 13, color: t.accent }}>View all in Logs</Text>
        <ExternalLink size={12} color={t.accent} />
      </Pressable>
    </>
  );
}
