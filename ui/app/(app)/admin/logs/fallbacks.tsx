import { useState, useMemo } from "react";
import { View, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { LogsTabBar } from "@/src/components/logs/LogsTabBar";
import { useFallbackEvents, useFallbackCooldowns, useClearCooldown } from "@/src/api/hooks/useFallbacks";
import { useBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";
import { AlertTriangle, Clock, RefreshCw, X } from "lucide-react";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

function fmtRemaining(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

// ---------------------------------------------------------------------------
// Active Cooldowns section
// ---------------------------------------------------------------------------
function CooldownsSection({ t }: { t: ReturnType<typeof useThemeTokens> }) {
  const { data, isLoading } = useFallbackCooldowns();
  const clearMutation = useClearCooldown();

  if (isLoading) return <ActivityIndicator color={t.accent} />;

  const cooldowns = data?.cooldowns ?? [];

  if (cooldowns.length === 0) {
    return (
      <div style={{ padding: "16px 20px", color: t.textDim, fontSize: 13 }}>
        No active cooldowns — all models operating normally.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "12px 20px" }}>
      {cooldowns.map((cd) => (
        <div
          key={cd.model}
          style={{
            background: t.surfaceRaised, border: `1px solid ${t.warningMuted}`,
            borderRadius: 8, padding: "12px 16px", minWidth: 280, flex: "0 1 auto",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{cd.model}</div>
              <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
                using <span style={{ color: t.success, fontWeight: 600 }}>{cd.fallback_model}</span>
              </div>
            </div>
            <button
              onClick={() => clearMutation.mutate(cd.model)}
              style={{
                background: "none", border: "none", cursor: "pointer",
                color: t.textDim, padding: 4,
              }}
              title="Clear cooldown"
            >
              <X size={14} />
            </button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.warningMuted }}>
            <Clock size={11} />
            <span>{fmtRemaining(cd.remaining_seconds)} remaining</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function FallbacksScreen() {
  const t = useThemeTokens();
  const { refreshing, onRefresh } = usePageRefresh();
  const { data: bots } = useBots();

  const [modelFilter, setModelFilter] = useState("");
  const [botFilter, setBotFilter] = useState("");

  const params = useMemo(() => ({
    count: 100,
    ...(modelFilter ? { model: modelFilter } : {}),
    ...(botFilter ? { bot_id: botFilter } : {}),
  }), [modelFilter, botFilter]);

  const { data, isLoading, refetch } = useFallbackEvents(params);

  // Collect unique models for filter dropdown
  const modelOptions = useMemo(() => {
    if (!data?.events) return [];
    const models = new Set<string>();
    data.events.forEach((e) => { models.add(e.model); models.add(e.fallback_model); });
    return Array.from(models).sort();
  }, [data]);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Logs" subtitle="Fallbacks" />
      <LogsTabBar active="fallbacks" />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        {/* Active Cooldowns */}
        <div style={{ padding: "16px 20px 8px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={16} color={t.warningMuted} />
            <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Active Cooldowns</span>
          </div>
        </div>
        <CooldownsSection t={t} />

        {/* Filter bar */}
        <div style={{
          display: "flex", gap: 8, padding: "12px 20px",
          borderTop: `1px solid ${t.surfaceRaised}`, borderBottom: `1px solid ${t.surfaceRaised}`,
          alignItems: "center", flexWrap: "wrap",
        }}>
          <select
            value={modelFilter}
            onChange={(e) => setModelFilter(e.target.value)}
            style={{
              background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
            }}
          >
            <option value="">All Models</option>
            {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>

          <select
            value={botFilter}
            onChange={(e) => setBotFilter(e.target.value)}
            style={{
              background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
            }}
          >
            <option value="">All Bots</option>
            {(bots ?? []).map((b) => <option key={b.id} value={b.id}>{b.name || b.id}</option>)}
          </select>

          <button
            onClick={() => refetch()}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6, padding: "5px 10px", fontSize: 12,
              color: t.textMuted, cursor: "pointer",
            }}
          >
            <RefreshCw size={11} /> Refresh
          </button>
        </div>

        {/* Events heading */}
        <div style={{ padding: "16px 20px 8px" }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>
            Recent Fallback Events{data ? ` (${data.events.length})` : ""}
          </span>
        </div>

        {/* Events table */}
        {isLoading ? (
          <View className="flex-1 items-center justify-center" style={{ padding: 40 }}>
            <ActivityIndicator color={t.accent} />
          </View>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {data?.events.map((ev) => (
              <div
                key={ev.id}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "10px 20px", borderBottom: `1px solid ${t.surfaceRaised}`,
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{
                      fontSize: 12, fontWeight: 600, color: t.danger,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {ev.model}
                    </span>
                    <span style={{ fontSize: 11, color: t.textDim }}>→</span>
                    <span style={{
                      fontSize: 12, fontWeight: 600, color: t.success,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {ev.fallback_model}
                    </span>
                    <span style={{
                      fontSize: 10, padding: "1px 6px", borderRadius: 3,
                      background: t.warningSubtle, color: t.warningMuted, fontWeight: 600,
                    }}>
                      {ev.reason}
                    </span>
                    {ev.bot_id && (
                      <span style={{
                        fontSize: 10, padding: "1px 6px", borderRadius: 3,
                        background: "rgba(99,102,241,0.1)", color: "#4f46e5", fontWeight: 600,
                      }}>
                        {ev.bot_id}
                      </span>
                    )}
                  </div>
                  {ev.error_message && (
                    <div style={{
                      fontSize: 11, color: t.textDim, marginTop: 2,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      maxWidth: 600,
                    }}>
                      {ev.error_message}
                    </div>
                  )}
                </div>
                <div style={{ flexShrink: 0, textAlign: "right" }}>
                  {ev.created_at && (
                    <div style={{ fontSize: 11, color: t.textDim }}>
                      {fmtDate(ev.created_at)} {fmtTime(ev.created_at)}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {data?.events.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
                No fallback events found.
              </div>
            )}
          </div>
        )}
      </RefreshableScrollView>
    </View>
  );
}
