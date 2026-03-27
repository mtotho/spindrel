import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import type { BotConfig } from "@/src/types/api";

const MODEL_COLORS: Array<{ test: (m: string) => boolean; bg: string; fg: string }> = [
  { test: (m) => m.startsWith("gemini/") || m.startsWith("gemini-"), bg: "rgba(34,197,94,0.15)", fg: "#86efac" },
  { test: (m) => m.startsWith("anthropic/") || m.includes("claude"), bg: "rgba(249,115,22,0.15)", fg: "#fdba74" },
  { test: (m) => m.startsWith("openai/") || m.includes("gpt"), bg: "rgba(16,185,129,0.15)", fg: "#6ee7b7" },
];
const FALLBACK_COLOR = { bg: "rgba(100,100,100,0.15)", fg: "#999" };

function getModelColor(model: string) {
  const m = model.toLowerCase();
  return MODEL_COLORS.find((c) => c.test(m)) ?? FALLBACK_COLOR;
}

type PillDef = { label: string; bg: string; fg: string };

const PILL_STYLES = {
  skill:    { bg: "rgba(168,85,247,0.15)", fg: "#c4b5fd" },
  mcp:      { bg: "rgba(249,115,22,0.15)", fg: "#fdba74" },
  tool:     { bg: "rgba(59,130,246,0.15)", fg: "#93c5fd" },
} as const;

function collectPills(bot: BotConfig): PillDef[] {
  const pills: PillDef[] = [];
  bot.skills?.forEach((s) => pills.push({ label: s.id, ...PILL_STYLES.skill }));
  bot.mcp_servers?.forEach((s) => pills.push({ label: s, ...PILL_STYLES.mcp }));
  bot.local_tools?.forEach((t) => pills.push({ label: t, ...PILL_STYLES.tool }));
  return pills;
}

function buildStats(bot: BotConfig): string {
  const parts: string[] = [];
  const toolCount = (bot.local_tools?.length ?? 0) + (bot.client_tools?.length ?? 0) + (bot.pinned_tools?.length ?? 0);
  if (toolCount > 0) parts.push(`${toolCount} tool${toolCount !== 1 ? "s" : ""}`);
  const skillCount = bot.skills?.length ?? 0;
  if (skillCount > 0) parts.push(`${skillCount} skill${skillCount !== 1 ? "s" : ""}`);
  const mcpCount = bot.mcp_servers?.length ?? 0;
  if (mcpCount > 0) parts.push(`${mcpCount} MCP`);
  const delegateCount = bot.delegate_bots?.length ?? 0;
  if (delegateCount > 0) parts.push(`${delegateCount} delegate${delegateCount !== 1 ? "s" : ""}`);
  return parts.join(" · ");
}

const MAX_PILLS = 6;

function BotCard({ bot, onPress, isWide }: { bot: BotConfig; onPress: () => void; isWide: boolean }) {
  const mc = getModelColor(bot.model);
  const pills = collectPills(bot);
  const stats = buildStats(bot);
  const promptPreview = bot.system_prompt
    ? bot.system_prompt.length > 120
      ? bot.system_prompt.slice(0, 120) + "..."
      : bot.system_prompt
    : null;

  return (
    <button
      onClick={onPress}
      style={{
        display: "flex", flexDirection: "column", gap: 8,
        padding: isWide ? "16px 20px" : "12px 14px",
        background: "#111", borderRadius: 10,
        border: "1px solid #1a1a1a",
        cursor: "pointer", textAlign: "left", width: "100%",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#2a2a2a")}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#1a1a1a")}
    >
      {/* Header: name + model badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "#e5e5e5", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {bot.name}
        </span>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
          background: mc.bg, color: mc.fg, whiteSpace: "nowrap", flexShrink: 0,
        }}>
          {bot.model}
        </span>
      </div>

      {/* System prompt preview */}
      {promptPreview && (
        <div style={{
          fontSize: 12, color: "#666", lineHeight: 1.4,
          display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}>
          {promptPreview}
        </div>
      )}

      {/* Capability pills */}
      {pills.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {pills.slice(0, MAX_PILLS).map((p) => (
            <span key={p.label} style={{
              padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 500,
              background: p.bg, color: p.fg,
            }}>
              {p.label}
            </span>
          ))}
          {pills.length > MAX_PILLS && (
            <span style={{
              padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 500,
              background: "rgba(100,100,100,0.15)", color: "#999",
            }}>
              +{pills.length - MAX_PILLS} more
            </span>
          )}
        </div>
      )}

      {/* Stats row */}
      {stats && (
        <div style={{ fontSize: 11, color: "#555" }}>
          {stats}
        </div>
      )}
    </button>
  );
}

export default function BotsScreen() {
  const router = useRouter();
  const { data, isLoading } = useBots();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Bots"
        subtitle={`${data?.length ?? 0} configured`}
        right={
          <button
            onClick={() => router.push("/admin/bots/new" as any)}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: "#3b82f6", color: "#fff", cursor: "pointer",
            }}
          >
            <Plus size={14} />
            New Bot
          </button>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }} contentContainerStyle={{
        padding: isWide ? 20 : 12,
        gap: isWide ? 12 : 10,
      }}>
        {(!data || data.length === 0) && (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13 }}>
            <div style={{ color: "#555", marginBottom: 8 }}>No bots configured yet.</div>
            <div style={{ color: "#444", fontSize: 12 }}>
              Create a bot to get started.
            </div>
          </div>
        )}

        {data && data.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(380px, 1fr))" : "1fr",
            gap: isWide ? 12 : 10,
          }}>
            {data.map((bot) => (
              <BotCard
                key={bot.id}
                bot={bot}
                isWide={isWide}
                onPress={() => router.push(`/admin/bots/${bot.id}` as any)}
              />
            ))}
          </div>
        )}
      </RefreshableScrollView>
    </View>
  );
}
