import { useState, useMemo, useCallback } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { TurnCard } from "@/src/components/shared/TurnCard";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter, useLocalSearchParams } from "expo-router";
import { X, Search, AlertTriangle, Wrench } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { LogsTabBar } from "@/src/components/logs/LogsTabBar";
import { useTurns } from "@/src/api/hooks/useTurns";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useThemeTokens } from "@/src/theme/tokens";

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
          background: errorOnly ? t.dangerSubtle : t.surfaceRaised,
          border: `1px solid ${errorOnly ? t.danger : t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px", fontSize: 12,
          color: errorOnly ? t.danger : t.textMuted, cursor: "pointer",
        }}
      >
        <AlertTriangle size={11} /> Errors
      </button>

      {/* Toggle: tool calls only */}
      <button
        onClick={() => setToolCallsOnly(!toolCallsOnly)}
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

      <LogsTabBar active="agent" />

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
          <ActivityIndicator color={t.accent} />
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
