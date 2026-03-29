/**
 * Indexing overview panel for the workspace settings page.
 * Shows all bots' resolved indexing configs + actual indexed files
 * grouped by directory so you can audit why things are indexed.
 *
 * For shared workspace bots, segments = "Indexed Directories" and are
 * editable inline (add/delete) without navigating to the bot edit page.
 */
import { useState, useMemo } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { ChevronDown, ChevronRight, Database, ExternalLink, EyeOff, FileText, Folder, Plus, RefreshCw, X } from "lucide-react";
import {
  useWorkspaceIndexing, useWorkspaceIndexStatus, useUpdateBotIndexing, useReindexWorkspace,
  type BotIndexingInfo, type FileIndexEntry,
} from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type DirSource = "memory" | "patterns" | "mixed";

interface DirFileInfo {
  rel: string;
  chunks: number;
  lang: string | null;
  source: "memory" | "patterns" | null;
}

/** Group indexed file paths by their first N directory segments. */
function buildDirTree(
  files: Record<string, FileIndexEntry>,
  botId: string,
): { path: string; files: DirFileInfo[]; source: DirSource }[] {
  const botFiles: DirFileInfo[] = [];
  for (const [filePath, entry] of Object.entries(files)) {
    if (entry.bots.some((b) => b.bot_id === botId)) {
      botFiles.push({ rel: filePath, chunks: entry.chunk_count, lang: entry.language, source: entry.source });
    }
  }

  const groups = new Map<string, DirFileInfo[]>();
  for (const f of botFiles) {
    const parts = f.rel.split("/");
    const dir = parts.length > 1 ? parts.slice(0, -1).join("/") : ".";
    const existing = groups.get(dir);
    if (existing) existing.push(f);
    else groups.set(dir, [f]);
  }

  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, dirFiles]) => {
      const sources = new Set(dirFiles.map((f) => f.source).filter(Boolean));
      const source: DirSource = sources.size > 1 ? "mixed" : sources.has("memory") ? "memory" : "patterns";
      return {
        path,
        files: dirFiles.sort((a, b) => a.rel.localeCompare(b.rel)),
        source,
      };
    });
}

// ---------------------------------------------------------------------------
// Directory group (expandable)
// ---------------------------------------------------------------------------

const SOURCE_STYLES: Record<DirSource, { bg: string; color: string; label: string }> = {
  memory: { bg: "rgba(139,92,246,0.1)", color: "#8b5cf6", label: "memory" },
  patterns: { bg: "rgba(59,130,246,0.08)", color: "#60a5fa", label: "patterns" },
  mixed: { bg: "rgba(20,184,166,0.1)", color: "#14b8a6", label: "mixed" },
};

function DirGroup({ dir }: {
  dir: { path: string; files: DirFileInfo[]; source: DirSource };
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const totalChunks = dir.files.reduce((s, f) => s + f.chunks, 0);
  const ss = SOURCE_STYLES[dir.source];

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
        <span style={{
          padding: "1px 5px", borderRadius: 3, fontSize: 9, fontWeight: 600,
          background: ss.bg, color: ss.color,
        }}>
          {ss.label}
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
// Inline segment editor (add/remove segments from workspace overview)
// ---------------------------------------------------------------------------

function SegmentEditor({
  bot,
  workspaceId,
}: {
  bot: BotIndexingInfo;
  workspaceId: string;
}) {
  const t = useThemeTokens();
  const updateIndexing = useUpdateBotIndexing(workspaceId);
  const segments: any[] = bot.resolved.segments || [];
  const explicitSegments: any[] = bot.explicit_overrides.segments || segments;
  const [newPrefix, setNewPrefix] = useState("");
  const [newModel, setNewModel] = useState("");

  const removeSegment = (idx: number) => {
    const updated = explicitSegments.filter((_: any, i: number) => i !== idx);
    updateIndexing.mutate({ bot_id: bot.bot_id, indexing: { segments: updated } });
  };

  const addSegment = () => {
    const prefix = newPrefix.trim();
    if (!prefix) return;
    const seg: any = { path_prefix: prefix };
    if (newModel.trim()) seg.embedding_model = newModel.trim();
    updateIndexing.mutate({
      bot_id: bot.bot_id,
      indexing: { segments: [...explicitSegments, seg] },
    });
    setNewPrefix("");
    setNewModel("");
  };

  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
        Indexed Directories
      </div>
      <div style={{ fontSize: 10, color: t.textDim, marginBottom: 6 }}>
        Only these directories are indexed for RAG retrieval. Memory files are always indexed separately.
      </div>
      {segments.map((seg: any, i: number) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "4px 8px", background: t.inputBg, borderRadius: 4, fontSize: 11, marginBottom: 4,
        }}>
          <span style={{ fontFamily: "monospace", color: "#60a5fa", flex: 1 }}>{seg.path_prefix}</span>
          {seg.embedding_model && (
            <span style={{ color: t.textMuted, fontSize: 10 }}>model: <span style={{ color: "#a78bfa", fontFamily: "monospace" }}>{seg.embedding_model}</span></span>
          )}
          {seg.patterns && <span style={{ color: t.textDim, fontSize: 10 }}>patterns: {seg.patterns.length}</span>}
          {seg.similarity_threshold != null && <span style={{ color: t.textDim, fontSize: 10 }}>thresh: {seg.similarity_threshold}</span>}
          {seg.top_k != null && <span style={{ color: t.textDim, fontSize: 10 }}>k: {seg.top_k}</span>}
          <button
            onClick={() => removeSegment(i)}
            style={{ background: "none", border: "none", cursor: "pointer", padding: "0 2px", color: "#f87171", fontSize: 12, lineHeight: 1 }}
            title="Remove directory"
          >
            <X size={12} />
          </button>
        </div>
      ))}
      {segments.length === 0 && (
        <div style={{ fontSize: 10, color: t.textDim, fontStyle: "italic", marginBottom: 6 }}>
          No directories configured — only memory files are indexed.
        </div>
      )}
      <div style={{ display: "flex", gap: 4, marginTop: 4, alignItems: "center" }}>
        <input
          type="text" value={newPrefix} onChange={(e) => setNewPrefix(e.target.value)}
          placeholder="directory (e.g. common/)"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSegment(); } }}
          style={{
            background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            padding: "4px 8px", fontSize: 11, color: t.text, outline: "none", flex: 1, minWidth: 100,
          }}
        />
        <input
          type="text" value={newModel} onChange={(e) => setNewModel(e.target.value)}
          placeholder="embedding model (optional)"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSegment(); } }}
          style={{
            background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            padding: "4px 8px", fontSize: 11, color: t.text, outline: "none", flex: 1, minWidth: 100,
          }}
        />
        <button
          onClick={addSegment}
          disabled={!newPrefix.trim() || updateIndexing.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 10px", fontSize: 11, fontWeight: 600,
            background: newPrefix.trim() ? t.surfaceRaised : t.inputBg,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            color: newPrefix.trim() ? t.text : t.textDim,
            cursor: newPrefix.trim() ? "pointer" : "default",
            opacity: updateIndexing.isPending ? 0.5 : 1,
          }}
        >
          <Plus size={11} /> Add
        </button>
      </div>
      {updateIndexing.isPending && (
        <div style={{ fontSize: 10, color: "#8b5cf6", marginTop: 4 }}>Saving...</div>
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
  workspaceId,
}: {
  bot: BotIndexingInfo;
  indexedFiles: Record<string, FileIndexEntry>;
  workspaceId: string;
}) {
  const t = useThemeTokens();
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const [showFiles, setShowFiles] = useState(false);
  const r = bot.resolved;
  const overrideKeys = Object.keys(bot.explicit_overrides).filter((k) => k !== "enabled");
  const isSharedWs = bot.role === "member" || bot.role === "orchestrator";

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
        opacity: (bot.indexing_enabled || bot.memory_scheme === "workspace-files") ? 1 : 0.5,
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
        <span style={{
          width: 8, height: 8, borderRadius: 4, flexShrink: 0,
          background: bot.indexing_enabled ? "#14b8a6"
            : bot.memory_scheme === "workspace-files" ? "#8b5cf6"
            : t.surfaceBorder,
        }} />
        {/* Clickable bot name → bot edit page */}
        <span
          onClick={(e) => { e.stopPropagation(); router.push(`/admin/bots/${bot.bot_id}` as any); }}
          style={{
            fontSize: 13, fontWeight: 600, color: t.text, flex: 1,
            cursor: "pointer", textDecoration: "none",
          }}
          onMouseEnter={(e) => { (e.target as HTMLElement).style.textDecoration = "underline"; }}
          onMouseLeave={(e) => { (e.target as HTMLElement).style.textDecoration = "none"; }}
        >
          {bot.bot_name}
          <ExternalLink size={10} color={t.textDim} style={{ marginLeft: 4, verticalAlign: "middle", opacity: 0.6 } as any} />
        </span>
        <span style={{
          padding: "2px 7px", borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: bot.role === "orchestrator" ? "rgba(168,85,247,0.12)" : "rgba(59,130,246,0.08)",
          color: bot.role === "orchestrator" ? "#8b5cf6" : "#60a5fa",
        }}>
          {bot.role}
        </span>
        {(bot.indexing_enabled || bot.memory_scheme === "workspace-files") && totalChunks > 0 && (
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
        {bot.indexing_enabled && bot.memory_scheme === "workspace-files" && (
          <span style={{ padding: "2px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600, background: "rgba(20,184,166,0.1)", color: "#14b8a6" }}>
            memory + files
          </span>
        )}
        {!bot.indexing_enabled && bot.memory_scheme === "workspace-files" && (
          <span style={{ padding: "2px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600, background: "rgba(139,92,246,0.1)", color: "#8b5cf6" }}>
            memory only
          </span>
        )}
        {!bot.indexing_enabled && bot.memory_scheme !== "workspace-files" && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <EyeOff size={11} color={t.textDim} />
            <span style={{ fontSize: 10, color: t.textDim }}>disabled</span>
          </span>
        )}
      </button>

      {/* Expanded details */}
      {expanded && (
        <div style={{ padding: "0 14px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Memory auto-indexing note */}
          {bot.memory_scheme === "workspace-files" && (
            <div style={{
              padding: "8px 12px", background: "rgba(139,92,246,0.06)",
              border: "1px solid rgba(139,92,246,0.12)", borderRadius: 6,
              fontSize: 11, color: t.textMuted, lineHeight: 1.5,
            }}>
              <span style={{ fontWeight: 600, color: "#8b5cf6" }}>Memory auto-indexed</span>
              {" "}&mdash; <span style={{ fontFamily: "monospace" }}>memory/**/*.md</span> is always indexed for search_memory, independent of the settings below.
            </div>
          )}

          {/* Config chips */}
          {bot.indexing_enabled && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <ConfigChip label="top_k" value={r.top_k} overridden={!!bot.explicit_overrides.top_k} />
              <ConfigChip label="threshold" value={r.similarity_threshold} overridden={!!bot.explicit_overrides.similarity_threshold} />
              <ConfigChip label="cooldown" value={`${r.cooldown_seconds}s`} overridden={!!bot.explicit_overrides.cooldown_seconds} />
              <ConfigChip label="watch" value={r.watch ? "on" : "off"} overridden={!!bot.explicit_overrides.watch} />
              <ConfigChip label="model" value={r.embedding_model} overridden={!!bot.explicit_overrides.embedding_model} />
            </div>
          )}

          {/* Shared workspace bots: inline segment editor */}
          {isSharedWs && bot.indexing_enabled && (
            <SegmentEditor bot={bot} workspaceId={workspaceId} />
          )}

          {/* Standalone bots: show patterns (read-only summary) */}
          {!isSharedWs && bot.indexing_enabled && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
                Indexed File Patterns
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
                {(r.patterns || []).length === 0 && (
                  <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>No patterns configured</span>
                )}
              </div>
            </div>
          )}

          {/* Segments for standalone bots (read-only) */}
          {!isSharedWs && r.segments && r.segments.length > 0 && (
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
          {(bot.indexing_enabled || bot.memory_scheme === "workspace-files") && totalFiles > 0 && (
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
  const { data: indexStatus, refetch: refetchStatus } = useWorkspaceIndexStatus(workspaceId);
  const reindex = useReindexWorkspace(workspaceId);
  const indexedFiles = indexStatus?.indexed_files ?? {};

  const handleReindex = () => {
    reindex.mutate(undefined, { onSuccess: () => refetchStatus() });
  };

  if (isLoading) {
    return <ActivityIndicator color="#14b8a6" style={{ alignSelf: "flex-start", marginVertical: 8 }} />;
  }

  if (!data?.bots?.length) {
    return <Text style={{ color: t.textDim, fontSize: 12 }}>No bots connected to this workspace.</Text>;
  }

  const enabledCount = data.bots.filter((b) => b.indexing_enabled).length;
  const memoryOnlyCount = data.bots.filter((b) => !b.indexing_enabled && b.memory_scheme === "workspace-files").length;
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
          {memoryOnlyCount > 0 && (
            <span style={{ fontWeight: 400, color: "#8b5cf6", marginLeft: 6, fontSize: 11 }}>
              +{memoryOnlyCount} memory only
            </span>
          )}
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
        <button
          onClick={handleReindex}
          disabled={reindex.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 5,
            padding: "4px 12px", borderRadius: 5, fontSize: 11, fontWeight: 600,
            background: reindex.isPending ? t.inputBg : t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`, cursor: reindex.isPending ? "default" : "pointer",
            color: reindex.isPending ? t.textDim : t.text, marginLeft: "auto",
            opacity: reindex.isPending ? 0.6 : 1,
          }}
        >
          <RefreshCw size={11} style={reindex.isPending ? { animation: "spin 1s linear infinite" } as any : undefined} />
          {reindex.isPending ? "Reindexing…" : "Reindex Files"}
        </button>
        {reindex.isSuccess && (
          <span style={{ fontSize: 10, color: "#14b8a6" }}>Done</span>
        )}
        {reindex.isError && (
          <span style={{ fontSize: 10, color: "#f87171" }}>Failed</span>
        )}
      </div>

      {/* Bot cards */}
      {data.bots.map((bot) => (
        <BotIndexCard key={bot.bot_id} bot={bot} indexedFiles={indexedFiles} workspaceId={workspaceId} />
      ))}
    </div>
  );
}
