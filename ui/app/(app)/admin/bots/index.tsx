import { useState, useMemo } from "react";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import {
  Plus,
  Search,
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
  MessageSquare,
  Zap,
} from "lucide-react";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useUsageSummary, type CostByDimension } from "@/src/api/hooks/useUsage";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotConfig } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Styling
// ---------------------------------------------------------------------------
const MODEL_COLORS: Array<{ test: (m: string) => boolean; bg: string; fg: string }> = [
  { test: (m) => m.startsWith("gemini/") || m.startsWith("gemini-"), bg: "rgba(34,197,94,0.15)", fg: "#16a34a" },
  { test: (m) => m.startsWith("anthropic/") || m.includes("claude"), bg: "rgba(249,115,22,0.15)", fg: "#ea580c" },
  { test: (m) => m.startsWith("openai/") || m.includes("gpt"), bg: "rgba(16,185,129,0.15)", fg: "#6ee7b7" },
  { test: (m) => m.includes("deepseek"), bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
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

// Feature badges — plain labels, styled uniformly to avoid visual noise
function featureBadges(bot: BotConfig): string[] {
  const badges: string[] = [];
  if (bot.memory?.enabled) badges.push("Memory");
  if (bot.knowledge?.enabled) badges.push("Knowledge");
  if (bot.context_compaction) badges.push("Compaction");
  if (bot.persona) badges.push("Persona");
  if ((bot.delegate_bots?.length ?? 0) > 0) badges.push("Delegation");
  if (bot.workspace?.enabled) badges.push("Workspace");
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
  const t = useThemeTokens();
  const isActive = currentKey === sortKey;
  return (
    <button
      onClick={() => onSort(sortKey)}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 4,
        background: "none",
        border: "none",
        cursor: "pointer",
        fontSize: 10,
        fontWeight: 600,
        color: isActive ? t.text : t.textDim,
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
  const t = useThemeTokens();
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
        background: t.surfaceRaised,
        borderRadius: 12,
        border: `1px solid ${t.surfaceBorder}`,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = t.textDim;
        e.currentTarget.style.boxShadow = `0 2px 12px ${t.overlayLight}`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = t.surfaceBorder;
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {/* Row 1: Name + model badge */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
        <span
          style={{
            fontSize: 15,
            fontWeight: 700,
            color: t.text,
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
            color: t.textDim,
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

      {/* Row 3: Feature badges — subtle, uniform */}
      {badges.length > 0 && (
        <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
          {badges.map((label) => (
            <span
              key={label}
              style={{
                padding: "2px 8px",
                borderRadius: 4,
                fontSize: 10,
                fontWeight: 500,
                background: t.overlayLight,
                color: t.textMuted,
              }}
            >
              {label}
            </span>
          ))}
        </div>
      )}

      {/* Row 4: Stats bar — capabilities + usage */}
      <div
        style={{
          display: "flex", flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          borderTop: `1px solid ${t.overlayBorder}`,
          paddingTop: 10,
          marginTop: 2,
        }}
      >
        <span style={{ fontSize: 11, color: t.textDim }}>{caps}</span>

        {/* Usage stats */}
        <div style={{ display: "flex", flexDirection: "row", gap: 12, alignItems: "center" }}>
          {usage && usage.calls > 0 && (
            <>
              <span
                style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3, fontSize: 11, color: t.textDim }}
                title="Total calls"
              >
                <MessageSquare size={10} color={t.textDim} />
                {usage.calls.toLocaleString()}
              </span>
              <span
                style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3, fontSize: 11, color: t.textDim }}
                title="Total tokens"
              >
                <Zap size={10} color={t.textDim} />
                {fmtTokens(usage.total_tokens)}
              </span>
              {usage.cost != null && usage.cost > 0 && (
                <span
                  style={{
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 2,
                    fontSize: 11,
                    fontWeight: 600,
                    color: t.textMuted,
                    fontFamily: "monospace",
                  }}
                  title="Estimated cost"
                >
                  $
                  {usage.cost < 0.01 ? usage.cost.toFixed(4) : usage.cost.toFixed(2)}
                </span>
              )}
            </>
          )}
          {(!usage || usage.calls === 0) && (
            <span style={{ fontSize: 11, color: t.textDim }}>No usage data</span>
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
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: bots, isLoading } = useAdminBots();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
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
      <div className="flex-1 bg-surface items-center justify-center">
        <Spinner color={t.accent} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Bots"
        subtitle={`${bots?.length ?? 0} configured`}
        right={
          <button
            onClick={() => navigate("/admin/bots/new")}
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              fontSize: 12,
              fontWeight: 600,
              border: "none",
              borderRadius: 6,
              background: t.accent,
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
          display: "flex", flexDirection: "row",
          gap: 10,
          padding: isWide ? "10px 20px" : "8px 12px",
          borderBottom: `1px solid ${t.surfaceRaised}`,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {/* Search */}
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 6,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "5px 10px",
            flex: isWide ? "0 1 260px" : "1 1 100%",
          }}
        >
          <Search size={13} color={t.textDim} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search bots..."
            style={{
              background: "none",
              border: "none",
              outline: "none",
              color: t.text,
              fontSize: 12,
              flex: 1,
              width: "100%",
            }}
          />
        </div>

        {/* Sort controls */}
        <div style={{ display: "flex", flexDirection: "row", gap: 2, alignItems: "center" }}>
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
              display: "flex", flexDirection: "row",
              gap: 14,
              alignItems: "center",
              fontSize: 11,
              color: t.textDim,
            }}
          >
            <span title="30-day totals" style={{ color: t.textDim, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", fontSize: 10 }}>
              30d
            </span>
            <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
              <MessageSquare size={11} color={t.textDim} /> {totalCalls.toLocaleString()} calls
            </span>
            <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
              <Zap size={11} color={t.textDim} /> {fmtTokens(totalTokens)} tokens
            </span>
            {totalCost != null && totalCost > 0 && (
              <span
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 2,
                  color: t.textMuted,
                  fontFamily: "monospace",
                  fontWeight: 600,
                }}
              >
                {fmtCost(totalCost)}
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
          <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No bots match "{search}"
          </div>
        )}

        {(!bots || bots.length === 0) && (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13 }}>
            <div style={{ color: t.textDim, marginBottom: 8 }}>No bots configured yet.</div>
            <div style={{ color: t.textDim, fontSize: 12 }}>Create a bot to get started.</div>
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
                onPress={() => navigate(`/admin/bots/${bot.id}`)}
              />
            ))}
          </div>
        )}
      </RefreshableScrollView>
    </div>
  );
}
