import { useState, useMemo } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import {
  Plus,
  Search,
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
  Cpu,
  MessageSquare,
  Zap,
  DollarSign,
} from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useUsageSummary, type CostByDimension } from "@/src/api/hooks/useUsage";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import type { BotConfig } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Styling
// ---------------------------------------------------------------------------
const MODEL_COLORS: Array<{ test: (m: string) => boolean; bg: string; fg: string }> = [
  { test: (m) => m.startsWith("gemini/") || m.startsWith("gemini-"), bg: "rgba(34,197,94,0.15)", fg: "#86efac" },
  { test: (m) => m.startsWith("anthropic/") || m.includes("claude"), bg: "rgba(249,115,22,0.15)", fg: "#fdba74" },
  { test: (m) => m.startsWith("openai/") || m.includes("gpt"), bg: "rgba(16,185,129,0.15)", fg: "#6ee7b7" },
  { test: (m) => m.includes("deepseek"), bg: "rgba(59,130,246,0.15)", fg: "#93c5fd" },
];
const FALLBACK_COLOR = { bg: "rgba(100,100,100,0.15)", fg: "#999" };

function getModelColor(model: string) {
  const m = model.toLowerCase();
  return MODEL_COLORS.find((c) => c.test(m)) ?? FALLBACK_COLOR;
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
function fmtTokens(n: number | undefined | null): string {
  if (n == null || n === 0) return "--";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtCost(v: number | null | undefined): string {
  if (v == null || v === 0) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

// ---------------------------------------------------------------------------
// Sort logic
// ---------------------------------------------------------------------------
type SortKey = "name" | "model" | "tokens" | "cost" | "calls";
type SortDir = "asc" | "desc";

interface BotWithUsage {
  bot: BotConfig;
  usage: CostByDimension | null;
}

function sortBots(items: BotWithUsage[], key: SortKey, dir: SortDir): BotWithUsage[] {
  const sorted = [...items].sort((a, b) => {
    let cmp = 0;
    switch (key) {
      case "name":
        cmp = a.bot.name.localeCompare(b.bot.name);
        break;
      case "model":
        cmp = a.bot.model.localeCompare(b.bot.model);
        break;
      case "tokens":
        cmp = (a.usage?.total_tokens ?? 0) - (b.usage?.total_tokens ?? 0);
        break;
      case "cost":
        cmp = (a.usage?.cost ?? 0) - (b.usage?.cost ?? 0);
        break;
      case "calls":
        cmp = (a.usage?.calls ?? 0) - (b.usage?.calls ?? 0);
        break;
    }
    return dir === "asc" ? cmp : -cmp;
  });
  return sorted;
}

// ---------------------------------------------------------------------------
// Capabilities summary
// ---------------------------------------------------------------------------
function capSummary(bot: BotConfig): string {
  const parts: string[] = [];
  const toolCount = (bot.local_tools?.length ?? 0) + (bot.client_tools?.length ?? 0);
  if (toolCount > 0) parts.push(`${toolCount} tools`);
  const skillCount = bot.skills?.length ?? 0;
  if (skillCount > 0) parts.push(`${skillCount} skills`);
  const mcpCount = bot.mcp_servers?.length ?? 0;
  if (mcpCount > 0) parts.push(`${mcpCount} MCP`);
  const delegateCount = bot.delegate_bots?.length ?? 0;
  if (delegateCount > 0) parts.push(`${delegateCount} delegates`);
  return parts.join(" · ") || "No tools";
}

// Feature badges
type Badge = { label: string; color: string };
function featureBadges(bot: BotConfig): Badge[] {
  const badges: Badge[] = [];
  if (bot.memory?.enabled) badges.push({ label: "Memory", color: "#c084fc" });
  if (bot.knowledge?.enabled) badges.push({ label: "Knowledge", color: "#67e8f9" });
  if (bot.context_compaction) badges.push({ label: "Compaction", color: "#86efac" });
  if (bot.persona) badges.push({ label: "Persona", color: "#fbbf24" });
  if ((bot.delegate_bots?.length ?? 0) > 0) badges.push({ label: "Delegation", color: "#fb923c" });
  if (bot.workspace?.enabled) badges.push({ label: "Workspace", color: "#93c5fd" });
  return badges;
}

// ---------------------------------------------------------------------------
// Sort header button
// ---------------------------------------------------------------------------
function SortHeader({
  label,
  sortKey,
  currentKey,
  currentDir,
  onSort,
  align,
  width,
}: {
  label: string;
  sortKey: SortKey;
  currentKey: SortKey;
  currentDir: SortDir;
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
  width?: number | string;
}) {
  const isActive = currentKey === sortKey;
  return (
    <button
      onClick={() => onSort(sortKey)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        background: "none",
        border: "none",
        cursor: "pointer",
        fontSize: 10,
        fontWeight: 600,
        color: isActive ? "#e5e5e5" : "#555",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        padding: "0 2px",
        justifyContent: align === "right" ? "flex-end" : "flex-start",
        width: width ?? "auto",
        flexShrink: 0,
      }}
    >
      {label}
      {isActive ? (
        currentDir === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />
      ) : (
        <ArrowUpDown size={10} style={{ opacity: 0.3 }} />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Bot card (grid tile)
// ---------------------------------------------------------------------------
function BotCard({
  bot,
  usage,
  onPress,
}: {
  bot: BotConfig;
  usage: CostByDimension | null;
  onPress: () => void;
}) {
  const mc = getModelColor(bot.model);
  const badges = featureBadges(bot);
  const caps = capSummary(bot);

  return (
    <button
      onClick={onPress}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "18px 20px",
        background: "#111",
        borderRadius: 12,
        border: "1px solid #1e1e1e",
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "#333";
        e.currentTarget.style.boxShadow = "0 2px 12px rgba(0,0,0,0.3)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "#1e1e1e";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {/* Row 1: Name + model badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          style={{
            fontSize: 15,
            fontWeight: 700,
            color: "#f0f0f0",
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {bot.name}
        </span>
        <span
          style={{
            padding: "3px 10px",
            borderRadius: 6,
            fontSize: 10,
            fontWeight: 600,
            background: mc.bg,
            color: mc.fg,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          {bot.model}
        </span>
      </div>

      {/* Row 2: System prompt preview */}
      {bot.system_prompt && (
        <div
          style={{
            fontSize: 12,
            color: "#666",
            lineHeight: 1.45,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {bot.system_prompt.length > 140 ? bot.system_prompt.slice(0, 140) + "..." : bot.system_prompt}
        </div>
      )}

      {/* Row 3: Feature badges */}
      {badges.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {badges.map((b) => (
            <span
              key={b.label}
              style={{
                padding: "2px 8px",
                borderRadius: 4,
                fontSize: 10,
                fontWeight: 600,
                background: `${b.color}15`,
                color: b.color,
              }}
            >
              {b.label}
            </span>
          ))}
        </div>
      )}

      {/* Row 4: Stats bar — capabilities + usage */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderTop: "1px solid #1a1a1a",
          paddingTop: 10,
          marginTop: 2,
        }}
      >
        <span style={{ fontSize: 11, color: "#555" }}>{caps}</span>

        {/* Usage stats */}
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {usage && usage.calls > 0 && (
            <>
              <span
                style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, color: "#777" }}
                title="Total calls"
              >
                <MessageSquare size={10} color="#555" />
                {usage.calls.toLocaleString()}
              </span>
              <span
                style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, color: "#777" }}
                title="Total tokens"
              >
                <Zap size={10} color="#555" />
                {fmtTokens(usage.total_tokens)}
              </span>
              {usage.cost != null && usage.cost > 0 && (
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 2,
                    fontSize: 11,
                    fontWeight: 600,
                    color: "#86efac",
                    fontFamily: "monospace",
                  }}
                  title="Estimated cost"
                >
                  <DollarSign size={10} color="#86efac" />
                  {usage.cost < 0.01 ? usage.cost.toFixed(4) : usage.cost.toFixed(2)}
                </span>
              )}
            </>
          )}
          {(!usage || usage.calls === 0) && (
            <span style={{ fontSize: 11, color: "#444" }}>No usage data</span>
          )}
        </div>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function BotsScreen() {
  const router = useRouter();
  const { data: bots, isLoading } = useBots();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  // Usage data for the past 30 days
  const { data: usageData } = useUsageSummary({ after: "30d" });

  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // Build usage lookup
  const usageByBot = useMemo(() => {
    const map = new Map<string, CostByDimension>();
    usageData?.cost_by_bot?.forEach((b) => map.set(b.label, b));
    return map;
  }, [usageData]);

  // Merge, filter, sort
  const displayBots = useMemo(() => {
    if (!bots) return [];
    let items: BotWithUsage[] = bots.map((bot) => ({
      bot,
      usage: usageByBot.get(bot.id) ?? null,
    }));

    // Search filter
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(
        ({ bot }) =>
          bot.name.toLowerCase().includes(q) ||
          bot.id.toLowerCase().includes(q) ||
          bot.model.toLowerCase().includes(q),
      );
    }

    return sortBots(items, sortKey, sortDir);
  }, [bots, usageByBot, search, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Default descending for numeric columns, ascending for text
      setSortDir(key === "name" || key === "model" ? "asc" : "desc");
    }
  };

  // Totals
  const totalCost = usageData?.total_cost;
  const totalTokens = usageData?.total_tokens ?? 0;
  const totalCalls = usageData?.total_calls ?? 0;

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
        subtitle={`${bots?.length ?? 0} configured`}
        right={
          <button
            onClick={() => router.push("/admin/bots/new" as any)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              fontSize: 12,
              fontWeight: 600,
              border: "none",
              borderRadius: 6,
              background: "#3b82f6",
              color: "#fff",
              cursor: "pointer",
            }}
          >
            <Plus size={14} />
            New Bot
          </button>
        }
      />

      {/* Toolbar: search + sort + summary stats */}
      <div
        style={{
          display: "flex",
          gap: 10,
          padding: isWide ? "10px 20px" : "8px 12px",
          borderBottom: "1px solid #1a1a1a",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {/* Search */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 6,
            padding: "5px 10px",
            flex: isWide ? "0 1 260px" : "1 1 100%",
          }}
        >
          <Search size={13} color="#555" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search bots..."
            style={{
              background: "none",
              border: "none",
              outline: "none",
              color: "#ccc",
              fontSize: 12,
              flex: 1,
              width: "100%",
            }}
          />
        </div>

        {/* Sort controls */}
        <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
          <SortHeader label="Name" sortKey="name" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortHeader label="Model" sortKey="model" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortHeader label="Calls" sortKey="calls" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortHeader label="Tokens" sortKey="tokens" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortHeader label="Cost" sortKey="cost" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* 30d totals */}
        {totalCalls > 0 && (
          <div
            style={{
              display: "flex",
              gap: 14,
              alignItems: "center",
              fontSize: 11,
              color: "#666",
            }}
          >
            <span title="30-day totals" style={{ color: "#444", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 10 }}>
              30d
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <MessageSquare size={11} color="#555" /> {totalCalls.toLocaleString()} calls
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <Zap size={11} color="#555" /> {fmtTokens(totalTokens)} tokens
            </span>
            {totalCost != null && totalCost > 0 && (
              <span
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 2,
                  color: "#86efac",
                  fontFamily: "monospace",
                  fontWeight: 600,
                }}
              >
                <DollarSign size={11} /> {fmtCost(totalCost)}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Grid */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: isWide ? 20 : 12 }}
      >
        {displayBots.length === 0 && bots && bots.length > 0 && (
          <div style={{ padding: 40, textAlign: "center", color: "#555", fontSize: 13 }}>
            No bots match "{search}"
          </div>
        )}

        {(!bots || bots.length === 0) && (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13 }}>
            <div style={{ color: "#555", marginBottom: 8 }}>No bots configured yet.</div>
            <div style={{ color: "#444", fontSize: 12 }}>Create a bot to get started.</div>
          </div>
        )}

        {displayBots.length > 0 && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isWide
                ? "repeat(auto-fill, minmax(420px, 1fr))"
                : "1fr",
              gap: isWide ? 14 : 10,
            }}
          >
            {displayBots.map(({ bot, usage }) => (
              <BotCard
                key={bot.id}
                bot={bot}
                usage={usage}
                onPress={() => router.push(`/admin/bots/${bot.id}` as any)}
              />
            ))}
          </div>
        )}
      </RefreshableScrollView>
    </View>
  );
}
