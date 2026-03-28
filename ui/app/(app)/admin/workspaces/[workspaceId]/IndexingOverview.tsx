/**
 * Indexing overview panel for the workspace settings page.
 * Shows all bots' resolved indexing configurations in a single audit view.
 */
import { useState } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { ChevronDown, Database, Eye, EyeOff } from "lucide-react";
import { useWorkspaceIndexing, useWorkspaceIndexStatus, type BotIndexingInfo } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Per-bot indexing card
// ---------------------------------------------------------------------------

function BotIndexCard({ bot, indexCounts }: { bot: BotIndexingInfo; indexCounts: Record<string, number> }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const r = bot.resolved;
  const overrideKeys = Object.keys(bot.explicit_overrides).filter((k) => k !== "enabled");
  const chunkCount = indexCounts[bot.bot_id] ?? 0;

  return (
    <div
      style={{
        background: t.surface,
        border: `1px solid ${bot.indexing_enabled ? t.surfaceRaised : t.surfaceBorder}`,
        borderRadius: 8,
        overflow: "hidden",
        opacity: bot.indexing_enabled ? 1 : 0.5,
      }}
    >
      {/* Header row */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "10px 14px",
          background: "none",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <ChevronDown
          size={13}
          color={t.textMuted}
          style={{ transform: expanded ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s", flexShrink: 0 } as any}
        />
        {/* Status dot */}
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            background: bot.indexing_enabled ? "#14b8a6" : t.surfaceBorder,
            flexShrink: 0,
          }}
        />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
          {bot.bot_name}
        </span>
        {/* Role badge */}
        <span
          style={{
            padding: "2px 7px",
            borderRadius: 4,
            fontSize: 10,
            fontWeight: 600,
            background: bot.role === "orchestrator" ? "rgba(168,85,247,0.12)" : "rgba(59,130,246,0.08)",
            color: bot.role === "orchestrator" ? "#8b5cf6" : "#60a5fa",
          }}
        >
          {bot.role}
        </span>
        {/* Chunk count */}
        {bot.indexing_enabled && chunkCount > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Database size={11} color={t.textDim} />
            <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
              {chunkCount}
            </span>
          </span>
        )}
        {/* Override indicator */}
        {overrideKeys.length > 0 && (
          <span
            style={{
              padding: "2px 6px",
              borderRadius: 3,
              fontSize: 9,
              fontWeight: 600,
              background: "rgba(245,158,11,0.1)",
              color: "#f59e0b",
            }}
          >
            {overrideKeys.length} override{overrideKeys.length > 1 ? "s" : ""}
          </span>
        )}
        {!bot.indexing_enabled && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <EyeOff size={11} color={t.textDim} />
            <span style={{ fontSize: 10, color: t.textDim }}>disabled</span>
          </span>
        )}
      </button>

      {/* Expanded details */}
      {expanded && (
        <div style={{ padding: "0 14px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Resolved config grid */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <ConfigChip label="top_k" value={r.top_k} overridden={!!bot.explicit_overrides.top_k} />
            <ConfigChip label="threshold" value={r.similarity_threshold} overridden={!!bot.explicit_overrides.similarity_threshold} />
            <ConfigChip label="cooldown" value={`${r.cooldown_seconds}s`} overridden={!!bot.explicit_overrides.cooldown_seconds} />
            <ConfigChip label="watch" value={r.watch ? "on" : "off"} overridden={!!bot.explicit_overrides.watch} />
            <ConfigChip label="model" value={r.embedding_model} overridden={!!bot.explicit_overrides.embedding_model} />
          </div>

          {/* Patterns */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
              Patterns
              {bot.explicit_overrides.patterns && (
                <span style={{ color: "#f59e0b", fontWeight: 600, marginLeft: 6, textTransform: "none" }}>overridden</span>
              )}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {(r.patterns || []).map((pat, i) => (
                <span
                  key={i}
                  style={{
                    padding: "2px 8px",
                    borderRadius: 4,
                    fontSize: 11,
                    fontFamily: "monospace",
                    background: t.inputBg,
                    color: "#60a5fa",
                  }}
                >
                  {pat}
                </span>
              ))}
            </div>
          </div>

          {/* Segments */}
          {r.segments && r.segments.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
                Segments
              </div>
              {r.segments.map((seg: any, i: number) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "4px 8px",
                    background: t.inputBg,
                    borderRadius: 4,
                    fontSize: 11,
                    marginBottom: 4,
                  }}
                >
                  <span style={{ fontFamily: "monospace", color: "#60a5fa" }}>{seg.path_prefix}</span>
                  {seg.embedding_model && (
                    <span style={{ color: t.textMuted }}>
                      model: <span style={{ color: "#a78bfa", fontFamily: "monospace" }}>{seg.embedding_model}</span>
                    </span>
                  )}
                  {seg.patterns && <span style={{ color: t.textDim }}>patterns: {seg.patterns.length}</span>}
                  {seg.similarity_threshold != null && <span style={{ color: t.textDim }}>thresh: {seg.similarity_threshold}</span>}
                  {seg.top_k != null && <span style={{ color: t.textDim }}>k: {seg.top_k}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config chip (shows label + value, highlighted if overridden)
// ---------------------------------------------------------------------------

function ConfigChip({ label, value, overridden }: { label: string; value: any; overridden: boolean }) {
  const t = useThemeTokens();
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 8px",
        borderRadius: 4,
        fontSize: 11,
        background: overridden ? "rgba(245,158,11,0.06)" : t.inputBg,
        border: overridden ? "1px solid rgba(245,158,11,0.2)" : `1px solid transparent`,
      }}
    >
      <span style={{ color: t.textDim, fontSize: 10 }}>{label}</span>
      <span style={{ fontFamily: "monospace", color: overridden ? "#f59e0b" : t.text }}>
        {String(value)}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function IndexingOverview({ workspaceId }: { workspaceId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useWorkspaceIndexing(workspaceId);
  const { data: indexStatus } = useWorkspaceIndexStatus(workspaceId);

  // Aggregate chunk counts per bot from index-status data
  const botChunkCounts: Record<string, number> = {};
  if (indexStatus?.indexed_files) {
    for (const entry of Object.values(indexStatus.indexed_files)) {
      for (const b of entry.bots) {
        botChunkCounts[b.bot_id] = (botChunkCounts[b.bot_id] ?? 0) + entry.chunk_count;
      }
    }
  }

  if (isLoading) {
    return <ActivityIndicator color="#14b8a6" style={{ alignSelf: "flex-start", marginVertical: 8 }} />;
  }

  if (!data?.bots?.length) {
    return (
      <Text style={{ color: t.textDim, fontSize: 12 }}>
        No bots connected to this workspace.
      </Text>
    );
  }

  const enabledCount = data.bots.filter((b) => b.indexing_enabled).length;
  const totalChunks = Object.values(botChunkCounts).reduce((a, b) => a + b, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Summary bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "10px 14px",
          background: t.inputBg,
          borderRadius: 8,
          border: `1px solid ${t.surfaceOverlay}`,
          fontSize: 12,
        }}
      >
        <span style={{ color: t.text, fontWeight: 600 }}>
          {enabledCount}/{data.bots.length} bots indexing
        </span>
        {totalChunks > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4, color: t.textMuted }}>
            <Database size={12} color={t.textDim} />
            {totalChunks.toLocaleString()} chunks total
          </span>
        )}
        {data.global_defaults && (
          <span style={{ color: t.textDim, fontSize: 11 }}>
            defaults: k={data.global_defaults.top_k}, thresh={data.global_defaults.similarity_threshold}, model={data.global_defaults.embedding_model}
          </span>
        )}
      </div>

      {/* Bot cards */}
      {data.bots.map((bot) => (
        <BotIndexCard key={bot.bot_id} bot={bot} indexCounts={botChunkCounts} />
      ))}
    </div>
  );
}
