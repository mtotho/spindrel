// Tools-in-context panel — mirrors SkillsInContextPanel in shape and purpose.
// Top: pinned tools (always injected every turn, like "skills in context").
// Bottom: searchable catalog with per-tool status badge (pinned / included /
// discover / none) drawn from the channel's primary bot config.
//
// Harness sessions can drop a tool into the next turn as @tool:<name>. Normal
// sessions still use this as a posture/readability panel.

import { useMemo, useState } from "react";
import { Wrench, Search, X, Pin } from "lucide-react";

import { useThemeTokens } from "../../theme/tokens";
import { useChannelEffectiveTools } from "../../api/hooks/useChannels";
import { useBot } from "../../api/hooks/useBots";
import { useAgentCapabilities } from "../../api/hooks/useAgentCapabilities";
import { useTools, type ToolItem } from "../../api/hooks/useTools";
import { tokenize } from "../shared/ToolSelector";

type Status = "pinned" | "included" | "discover" | "none";

const STATUS_STYLE: Record<Status, { label: string; bg: string; fg: string }> = {
  pinned:   { label: "pinned",   bg: "rgba(168,85,247,0.15)", fg: "#9333ea" },
  included: { label: "included", bg: "rgba(16,185,129,0.15)", fg: "#059669" },
  discover: { label: "discover", bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
  none:     { label: "—",        bg: "rgba(148,163,184,0.12)", fg: "#64748b" },
};

interface PostureArgs {
  channelId?: string;
  botId?: string;
}

/** Cheap hook: resolves pinned/included/discovery sets for the composer's bot.
 *  Exported so the "+" trigger can badge a pinned count without rendering. */
export function useToolsPosture({ channelId, botId }: PostureArgs) {
  const { data: effective } = useChannelEffectiveTools(channelId);
  const { data: bot } = useBot(botId);
  return useMemo(() => {
    const pinned = new Set<string>(effective?.pinned_tools ?? bot?.pinned_tools ?? []);
    const included = new Set<string>(effective?.local_tools ?? bot?.local_tools ?? []);
    const discoveryOn = bot?.tool_discovery !== false && bot?.tool_retrieval !== false;
    return { pinned, included, discoveryOn, pinnedCount: pinned.size };
  }, [effective, bot]);
}

function statusFor(
  name: string,
  pinned: Set<string>,
  included: Set<string>,
  discoveryOn: boolean,
): Status {
  if (pinned.has(name)) return "pinned";
  if (included.has(name)) return "included";
  if (discoveryOn) return "discover";
  return "none";
}

const STATUS_RANK: Record<Status, number> = { pinned: 0, included: 1, discover: 2, none: 3 };

export interface ToolsInContextPanelProps {
  channelId?: string;
  botId?: string;
  onInsertToolTag?: (toolName: string) => void;
  onClose: () => void;
}

export function ToolsInContextPanel({ channelId, botId, onInsertToolTag, onClose }: ToolsInContextPanelProps) {
  const t = useThemeTokens();
  const [search, setSearch] = useState("");

  const { pinned, included, discoveryOn } = useToolsPosture({ channelId, botId });
  const { data: tools = [], isLoading } = useTools();
  const { data: capabilities } = useAgentCapabilities({
    botId,
    channelId,
    includeEndpoints: false,
    includeSchemas: false,
    maxTools: 24,
    enabled: Boolean(botId || channelId),
  });

  const pinnedEntries = useMemo(() => {
    const map = new Map<string, ToolItem>();
    for (const tool of tools) map.set(tool.tool_name, tool);
    return [...pinned].map((name) => ({
      name,
      tool: map.get(name),
    }));
  }, [tools, pinned]);

  const recommended = useMemo(() => {
    if (!capabilities?.tools?.recommended_core?.length || !tools.length) return [];
    const byName = new Map<string, ToolItem>();
    for (const tool of tools) byName.set(tool.tool_name, tool);
    return capabilities.tools.recommended_core
      .map((name) => byName.get(name))
      .filter((tool): tool is ToolItem => Boolean(tool))
      .slice(0, 6);
  }, [capabilities, tools]);

  const filtered = useMemo(() => {
    if (!tools.length) return [];
    let pool = tools;
    if (search.trim()) {
      const q = tokenize(search);
      pool = pool.filter((tool) => {
        const haystack = [
          ...tokenize(tool.tool_name),
          ...tokenize(tool.description ?? ""),
          ...tokenize(tool.source_integration ?? ""),
        ].join(" ");
        return q.every((qt) => haystack.includes(qt));
      });
    }
    return [...pool]
      .map((tool) => ({ tool, status: statusFor(tool.tool_name, pinned, included, discoveryOn) }))
      .sort((a, b) => {
        const r = STATUS_RANK[a.status] - STATUS_RANK[b.status];
        if (r !== 0) return r;
        return a.tool.tool_name.localeCompare(b.tool.tool_name);
      })
      .slice(0, 120);
  }, [tools, search, pinned, included, discoveryOn]);

  return (
    <div className="flex flex-col h-full">
      <div
        className="flex flex-row items-center justify-between px-3 py-2 shrink-0"
        style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
      >
        <div className="flex flex-row items-center gap-1.5">
          <Wrench size={12} color={t.accent} />
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
            Tools in context
          </span>
          <span style={{ fontSize: 10, color: t.textDim }}>{pinned.size}</span>
        </div>
        <button
          onClick={() => { setSearch(""); onClose(); }}
          aria-label="Close"
          className="bg-transparent border-none cursor-pointer p-1 rounded"
          style={{ display: "flex", alignItems: "center" }}
        >
          <X size={12} color={t.textDim} />
        </button>
      </div>

      {pinnedEntries.length > 0 ? (
        <div
          className="shrink-0"
          style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
        >
          {pinnedEntries.map(({ name, tool }) => (
            <PinnedRow key={name} name={name} description={tool?.description ?? null} />
          ))}
        </div>
      ) : (
        <div
          className="px-3 py-2 shrink-0 text-[10px]"
          style={{
            color: t.textDim,
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}
        >
          No pinned tools. {discoveryOn
            ? "Bot discovers tools on-demand via search_tools."
            : "Tools below with \u201Cincluded\u201D are available this turn."}
        </div>
      )}

      <div
        className="flex flex-row items-center gap-1.5 px-2 py-2 shrink-0"
        style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
      >
        <Search size={12} className="text-text-dim shrink-0 ml-1" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search all tools\u2026"
          autoFocus
          className="flex-1 min-w-0 px-2 py-1 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent/40"
        />
      </div>

      <div
        className="px-3 py-1 text-[10px] shrink-0"
        style={{ color: t.textDim, borderBottom: `1px solid ${t.surfaceBorder}55` }}
      >
        {isLoading
          ? "Loading tools\u2026"
          : `${filtered.length} of ${tools.length} tool${tools.length === 1 ? "" : "s"}${
              search.trim() && filtered.length === 120 ? " (showing first 120)" : ""
            }`}
      </div>

      <div className="overflow-y-auto" style={{ flex: 1 }}>
        {filtered.length === 0 ? (
          <div
            className="px-3 py-4 text-center"
            style={{ fontSize: 11, color: t.textDim }}
          >
            {isLoading ? "" : "No tools match."}
          </div>
        ) : (
          <>
            {!search.trim() && recommended.length > 0 && (
              <div
                className="py-1"
                style={{ borderBottom: `1px solid ${t.surfaceBorder}55` }}
              >
                <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">
                  Recommended now
                </div>
                {recommended.map((tool) => (
                  <CatalogRow
                    key={`recommended:${tool.tool_name}:${tool.id}`}
                    tool={tool}
                    status={statusFor(tool.tool_name, pinned, included, discoveryOn)}
                    onSelect={onInsertToolTag}
                  />
                ))}
              </div>
            )}
            {filtered.map(({ tool, status }) => (
              <CatalogRow
                key={`${tool.tool_name}:${tool.id}`}
                tool={tool}
                status={status}
                onSelect={onInsertToolTag}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function PinnedRow({ name, description }: { name: string; description: string | null }) {
  const t = useThemeTokens();
  return (
    <div
      className="flex flex-col px-3 py-1.5"
      style={{ backgroundColor: t.surface }}
      title={description || name}
    >
      <div className="flex flex-row items-center gap-1.5">
        <Pin size={10} color={t.purple} />
        <span
          style={{
            fontSize: 12,
            color: t.text,
            fontWeight: 500,
            fontFamily: "monospace",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
          }}
        >
          {name}
        </span>
      </div>
      {description && (
        <span
          style={{
            fontSize: 10,
            color: t.textDim,
            marginLeft: 16,
            marginTop: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {description}
        </span>
      )}
    </div>
  );
}

function CatalogRow({ tool, status, onSelect }: { tool: ToolItem; status: Status; onSelect?: (toolName: string) => void }) {
  const t = useThemeTokens();
  const badge = STATUS_STYLE[status];
  const dim = status === "none";
  const clickable = !!onSelect && (status !== "none" || !tool.server_name);
  const content = (
    <>
      <div className="flex flex-row items-center gap-2">
        <Wrench
          size={11}
          color={status === "pinned" ? t.purple : status === "included" ? t.accent : t.textDim}
          className="shrink-0"
        />
        <span
          className="text-xs font-medium truncate"
          style={{ color: t.text, fontFamily: "monospace" }}
        >
          {tool.tool_name}
        </span>
        {tool.source_integration && (
          <span className="text-[9px] shrink-0" style={{ color: t.textDim }}>
            {tool.source_integration}
          </span>
        )}
        <span
          className="text-[9px] font-semibold rounded ml-auto shrink-0"
          style={{
            padding: "1px 6px",
            background: badge.bg,
            color: badge.fg,
          }}
        >
          {clickable ? "add once" : badge.label}
        </span>
      </div>
      {tool.description && (
        <span
          className="text-[10px] line-clamp-1 pl-[18px]"
          style={{ color: t.textDim }}
        >
          {tool.description}
        </span>
      )}
    </>
  );
  if (clickable) {
    return (
      <button
        type="button"
        onClick={() => onSelect?.(tool.tool_name)}
        className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-surface-overlay/60"
        style={{ opacity: dim ? 0.7 : 1 }}
        title={`Add @tool:${tool.tool_name} for one turn`}
      >
        {content}
      </button>
    );
  }
  return (
    <div
      className="flex flex-col gap-0.5 w-full px-3 py-2 text-left"
      style={{ opacity: dim ? 0.55 : 1 }}
      title={tool.description ?? tool.tool_name}
    >
      {content}
    </div>
  );
}
