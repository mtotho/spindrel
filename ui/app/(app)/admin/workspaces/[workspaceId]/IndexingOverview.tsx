/**
 * Indexing overview panel for the workspace settings page.
 * Shows all bots' resolved indexing configs + actual indexed files
 * grouped by directory so you can audit why things are indexed.
 */
import { useState, useMemo } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { ChevronDown, ChevronRight, Database, EyeOff, FileText, Folder } from "lucide-react";
import {
  useWorkspaceIndexing, useWorkspaceIndexStatus,
  type BotIndexingInfo, type FileIndexEntry,
} from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Group indexed file paths by their first N directory segments. */
function buildDirTree(
  files: Record<string, FileIndexEntry>,
  botId: string,
): { path: string; files: { rel: string; chunks: number; lang: string | null }[] }[] {
  // Filter files that belong to this bot
  const botFiles: { rel: string; chunks: number; lang: string | null }[] = [];
  for (const [filePath, entry] of Object.entries(files)) {
    if (entry.bots.some((b) => b.bot_id === botId)) {
      botFiles.push({ rel: filePath, chunks: entry.chunk_count, lang: entry.language });
    }
  }

  // Group by top-level directory
  const groups = new Map<string, typeof botFiles>();
  for (const f of botFiles) {
    const parts = f.rel.split("/");
    const dir = parts.length > 1 ? parts.slice(0, -1).join("/") : ".";
    const existing = groups.get(dir);
    if (existing) existing.push(f);
    else groups.set(dir, [f]);
  }

  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, files]) => ({
      path,
      files: files.sort((a, b) => a.rel.localeCompare(b.rel)),
    }));
}

// ---------------------------------------------------------------------------
// Directory group (expandable)
// ---------------------------------------------------------------------------

function DirGroup({ dir }: {
  dir: { path: string; files: { rel: string; chunks: number; lang: string | null }[] };
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const totalChunks = dir.files.reduce((s, f) => s + f.chunks, 0);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          width: "100%", padding: "5px 0",
          background: "none", border: "none", cursor: "pointer", textAlign: "left",
        }}
      >
        {open
          ? <ChevronDown size={11} color={t.textDim} />
          : <ChevronRight size={11} color={t.textDim} />}
        <Folder size={12} color="#60a5fa" />
        <span style={{ fontSize: 11, fontFamily: "monospace", color: t.text, flex: 1 }}>
          {dir.path}
        </span>
        <span style={{ fontSize: 10, color: t.textDim }}>
          {dir.files.length} file{dir.files.length !== 1 ? "s" : ""}, {totalChunks} chunks
        </span>
      </button>
      {open && (
        <div style={{ marginLeft: 24, display: "flex", flexDirection: "column", gap: 1 }}>
          {dir.files.map((f) => {
            const name = f.rel.split("/").pop() || f.rel;
            return (
              <div key={f.rel} style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 0" }}>
                <FileText size={10} color={t.textDim} />
                <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, flex: 1 }}>
                  {name}
                </span>
                {f.lang && (
                  <span style={{ fontSize: 9, color: t.textDim, background: t.inputBg, padding: "1px 5px", borderRadius: 3 }}>
                    {f.lang}
                  </span>
                )}
                <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                  {f.chunks}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-bot indexing card
// ---------------------------------------------------------------------------

function BotIndexCard({
  bot,
  indexedFiles,
}: {
  bot: BotIndexingInfo;
  indexedFiles: Record<string, FileIndexEntry>;
}) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const r = bot.resolved;
  const overrideKeys = Object.keys(bot.explicit_overrides).filter((k) => k !== "enabled");

  const dirTree = useMemo(
    () => (showFiles ? buildDirTree(indexedFiles, bot.bot_id) : []),
    [showFiles, indexedFiles, bot.bot_id],
  );

  const totalFiles = useMemo(() => {
    let count = 0;
    for (const entry of Object.values(indexedFiles)) {
      if (entry.bots.some((b) => b.bot_id === bot.bot_id)) count++;
    }
    return count;
  }, [indexedFiles, bot.bot_id]);

  const totalChunks = useMemo(() => {
    let count = 0;
    for (const entry of Object.values(indexedFiles)) {
      if (entry.bots.some((b) => b.bot_id === bot.bot_id)) count += entry.chunk_count;
    }
    return count;
  }, [indexedFiles, bot.bot_id]);

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
          display: "flex", alignItems: "center", gap: 8,
          width: "100%", padding: "10px 14px",
          background: "none", border: "none", cursor: "pointer", textAlign: "left",
        }}
      >
        <ChevronDown
          size={13}
          color={t.textMuted}
          style={{ transform: expanded ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s", flexShrink: 0 } as any}
        />
        <span style={{ width: 8, height: 8, borderRadius: 4, background: bot.indexing_enabled ? "#14b8a6" : t.surfaceBorder, flexShrink: 0 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>{bot.bot_name}</span>
        <span style={{
          padding: "2px 7px", borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: bot.role === "orchestrator" ? "rgba(168,85,247,0.12)" : "rgba(59,130,246,0.08)",
          color: bot.role === "orchestrator" ? "#8b5cf6" : "#60a5fa",
        }}>
          {bot.role}
        </span>
        {bot.indexing_enabled && totalChunks > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Database size={11} color={t.textDim} />
            <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
              {totalFiles} files / {totalChunks} chunks
            </span>
          </span>
        )}
        {overrideKeys.length > 0 && (
          <span style={{ padding: "2px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600, background: "rgba(245,158,11,0.1)", color: "#f59e0b" }}>
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
          {/* Config chips */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <ConfigChip label="top_k" value={r.top_k} overridden={!!bot.explicit_overrides.top_k} />
            <ConfigChip label="threshold" value={r.similarity_threshold} overridden={!!bot.explicit_overrides.similarity_threshold} />
            <ConfigChip label="cooldown" value={`${r.cooldown_seconds}s`} overridden={!!bot.explicit_overrides.cooldown_seconds} />
            <ConfigChip label="watch" value={r.watch ? "on" : "off"} overridden={!!bot.explicit_overrides.watch} />
            <ConfigChip label="model" value={r.embedding_model} overridden={!!bot.explicit_overrides.embedding_model} />
          </div>

          {/* Patterns — this is the key "why is it indexed" info */}
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
              Patterns
              {bot.explicit_overrides.patterns && (
                <span style={{ color: "#f59e0b", fontWeight: 600, marginLeft: 6, textTransform: "none" }}>overridden</span>
              )}
              {!bot.explicit_overrides.patterns && (
                <span style={{ fontWeight: 400, color: t.textDim, textTransform: "none", marginLeft: 6 }}>inherited from defaults</span>
              )}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {(r.patterns || []).map((pat, i) => (
                <span key={i} style={{
                  padding: "2px 8px", borderRadius: 4, fontSize: 11,
                  fontFamily: "monospace", background: t.inputBg, color: "#60a5fa",
                }}>
                  {pat}
                </span>
              ))}
            </div>
            <div style={{ fontSize: 10, color: t.textDim, marginTop: 4 }}>
              Files matching these globs under the workspace root are indexed. Excluded: .git, node_modules, __pycache__, .venv, .history, and .gitignore rules.
            </div>
          </div>

          {/* Segments */}
          {r.segments && r.segments.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
                Segments <span style={{ fontWeight: 400, textTransform: "none" }}>per-path-prefix overrides</span>
              </div>
              {r.segments.map((seg: any, i: number) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "4px 8px", background: t.inputBg, borderRadius: 4, fontSize: 11, marginBottom: 4,
                }}>
                  <span style={{ fontFamily: "monospace", color: "#60a5fa" }}>{seg.path_prefix}</span>
                  {seg.embedding_model && (
                    <span style={{ color: t.textMuted }}>model: <span style={{ color: "#a78bfa", fontFamily: "monospace" }}>{seg.embedding_model}</span></span>
                  )}
                  {seg.channel_id && (
                    <span style={{ color: "#f59e0b", fontSize: 10 }}>channel-gated</span>
                  )}
                  {seg.patterns && <span style={{ color: t.textDim }}>patterns: {seg.patterns.length}</span>}
                  {seg.similarity_threshold != null && <span style={{ color: t.textDim }}>thresh: {seg.similarity_threshold}</span>}
                  {seg.top_k != null && <span style={{ color: t.textDim }}>k: {seg.top_k}</span>}
                </div>
              ))}
            </div>
          )}

          {/* Indexed files drilldown */}
          {bot.indexing_enabled && totalFiles > 0 && (
            <div>
              <button
                onClick={() => setShowFiles(!showFiles)}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "6px 10px", background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 6, cursor: "pointer", fontSize: 11, fontWeight: 600, color: t.textMuted,
                }}
              >
                {showFiles
                  ? <ChevronDown size={11} color={t.textMuted} />
                  : <ChevronRight size={11} color={t.textMuted} />}
                Indexed Files ({totalFiles} files in {dirTree.length || "..."} directories)
              </button>
              {showFiles && dirTree.length > 0 && (
                <div style={{
                  marginTop: 6, padding: "8px 10px",
                  background: t.inputBg, borderRadius: 6, border: `1px solid ${t.surfaceBorder}`,
                  maxHeight: 400, overflowY: "auto",
                }}>
                  {dirTree.map((dir) => (
                    <DirGroup key={dir.path} dir={dir} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config chip
// ---------------------------------------------------------------------------

function ConfigChip({ label, value, overridden }: { label: string; value: any; overridden: boolean }) {
  const t = useThemeTokens();
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "3px 8px", borderRadius: 4, fontSize: 11,
      background: overridden ? "rgba(245,158,11,0.06)" : t.inputBg,
      border: overridden ? "1px solid rgba(245,158,11,0.2)" : "1px solid transparent",
    }}>
      <span style={{ color: t.textDim, fontSize: 10 }}>{label}</span>
      <span style={{ fontFamily: "monospace", color: overridden ? "#f59e0b" : t.text }}>{String(value)}</span>
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
  const indexedFiles = indexStatus?.indexed_files ?? {};

  if (isLoading) {
    return <ActivityIndicator color="#14b8a6" style={{ alignSelf: "flex-start", marginVertical: 8 }} />;
  }

  if (!data?.bots?.length) {
    return <Text style={{ color: t.textDim, fontSize: 12 }}>No bots connected to this workspace.</Text>;
  }

  const enabledCount = data.bots.filter((b) => b.indexing_enabled).length;
  const totalFiles = Object.keys(indexedFiles).length;
  const totalChunks = Object.values(indexedFiles).reduce((s, e) => s + e.chunk_count, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Summary bar */}
      <div style={{
        display: "flex", alignItems: "center", flexWrap: "wrap", gap: 16,
        padding: "10px 14px", background: t.inputBg, borderRadius: 8,
        border: `1px solid ${t.surfaceOverlay}`, fontSize: 12,
      }}>
        <span style={{ color: t.text, fontWeight: 600 }}>
          {enabledCount}/{data.bots.length} bots indexing
        </span>
        {totalChunks > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 4, color: t.textMuted }}>
            <Database size={12} color={t.textDim} />
            {totalFiles} files / {totalChunks.toLocaleString()} chunks
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
        <BotIndexCard key={bot.bot_id} bot={bot} indexedFiles={indexedFiles} />
      ))}
    </div>
  );
}
