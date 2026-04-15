/**
 * Simplified indexing section for the workspace settings page.
 * Shows summary stats, workspace defaults editor, and a compact per-bot table.
 */
import { Spinner } from "@/src/components/shared/Spinner";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Database, ExternalLink, RefreshCw } from "lucide-react";
import {
  useWorkspaceIndexing, useWorkspaceIndexStatus, useReindexWorkspace,
  type BotIndexingInfo, type FileIndexEntry,
} from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";
import { WorkspaceDefaultsEditor } from "./WorkspaceDefaultsEditor";

// ---------------------------------------------------------------------------
// Compact bot indexing table
// ---------------------------------------------------------------------------

function BotIndexTable({
  bots,
  indexedFiles,
}: {
  bots: BotIndexingInfo[];
  indexedFiles: Record<string, FileIndexEntry>;
}) {
  const t = useThemeTokens();
  const navigate = useNavigate();

  const botStats = useMemo(() => {
    return bots.map((bot) => {
      let files = 0;
      let chunks = 0;
      for (const entry of Object.values(indexedFiles)) {
        if (entry.bots.some((b) => b.bot_id === bot.bot_id)) {
          files++;
          chunks += entry.chunk_count;
        }
      }
      const overrideCount = Object.keys(bot.explicit_overrides).filter((k) => k !== "enabled").length;
      return { bot, files, chunks, overrideCount };
    });
  }, [bots, indexedFiles]);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex flex-row items-center gap-3 px-2 py-1.5 text-xs font-semibold"
        style={{ color: t.textDim, borderBottom: `1px solid ${t.surfaceBorder}` }}>
        <span className="flex-1 min-w-0">Bot</span>
        <span className="w-20 text-center">Status</span>
        <span className="w-16 text-center">Segments</span>
        <span className="w-20 text-center">Files</span>
        <span className="w-16 text-center">Overrides</span>
      </div>

      {/* Rows */}
      {botStats.map(({ bot, files, chunks, overrideCount }) => {
        const status = bot.indexing_enabled
          ? (bot.memory_scheme === "workspace-files" ? "memory + files" : "enabled")
          : (bot.memory_scheme === "workspace-files" ? "memory only" : "disabled");
        const statusColor = bot.indexing_enabled
          ? "#14b8a6"
          : (bot.memory_scheme === "workspace-files" ? t.purple : t.textDim);

        return (
          <div key={bot.bot_id}
            className="flex flex-row items-center gap-3 px-2 py-2"
            style={{
              borderBottom: `1px solid ${t.surfaceBorder}`,
              opacity: bot.indexing_enabled || bot.memory_scheme === "workspace-files" ? 1 : 0.5,
            }}>
            {/* Bot name — clickable link to bot edit */}
            <button
              onClick={() => navigate(`/admin/bots/${bot.bot_id}`)}
              className="flex flex-row items-center gap-1 flex-1 min-w-0 text-xs font-medium bg-transparent border-none cursor-pointer p-0 truncate"
              style={{ color: t.text, textDecoration: "none" }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.textDecoration = "underline"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.textDecoration = "none"; }}
            >
              <span className="truncate">{bot.bot_name}</span>
              <ExternalLink size={9} className="flex-shrink-0 opacity-40" style={{ color: t.textDim }} />
            </button>

            {/* Status */}
            <span className="w-20 text-center text-xs font-semibold" style={{ color: statusColor, fontSize: 10 }}>
              {status}
            </span>

            {/* Segments count */}
            <span className="w-16 text-center text-xs font-mono" style={{ color: t.textMuted }}>
              {(bot.resolved.segments || []).length}
            </span>

            {/* Files */}
            <span className="w-20 text-center text-xs font-mono" style={{ color: t.textMuted }}>
              {files > 0 ? `${files} / ${chunks}` : "\u2014"}
            </span>

            {/* Overrides badge */}
            <span className="w-16 text-center">
              {overrideCount > 0 ? (
                <span className="text-xs font-semibold px-1.5 py-0.5 rounded"
                  style={{ background: t.warningSubtle, color: t.warning, fontSize: 10 }}>
                  {overrideCount}
                </span>
              ) : (
                <span className="text-xs" style={{ color: t.textDim }}>{"\u2014"}</span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

export function IndexingSection({ workspaceId }: { workspaceId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useWorkspaceIndexing(workspaceId);
  const { data: indexStatus, refetch: refetchStatus } = useWorkspaceIndexStatus(workspaceId);
  const reindex = useReindexWorkspace(workspaceId);
  const indexedFiles = indexStatus?.indexed_files ?? {};

  const handleReindex = () => {
    reindex.mutate(undefined, { onSuccess: () => refetchStatus() });
  };

  if (isLoading) {
    return <Spinner />;
  }

  if (!data?.bots?.length) {
    return <span className="text-xs" style={{ color: t.textDim }}>No bots connected to this workspace.</span>;
  }

  const enabledCount = data.bots.filter((b) => b.indexing_enabled).length;
  const memoryOnlyCount = data.bots.filter((b) => !b.indexing_enabled && b.memory_scheme === "workspace-files").length;
  const totalFiles = Object.keys(indexedFiles).length;
  const totalChunks = Object.values(indexedFiles).reduce((s, e) => s + e.chunk_count, 0);

  return (
    <div className="flex flex-col gap-3">
      {/* Summary bar */}
      <div className="flex flex-row items-center flex-wrap gap-4 px-3 py-2.5 rounded-lg text-xs"
        style={{ background: t.inputBg, border: `1px solid ${t.surfaceOverlay}` }}>
        <span className="font-semibold" style={{ color: t.text }}>
          {enabledCount}/{data.bots.length} bots indexing
          {memoryOnlyCount > 0 && (
            <span className="font-normal ml-1.5" style={{ color: t.purple, fontSize: 11 }}>
              +{memoryOnlyCount} memory only
            </span>
          )}
        </span>
        {totalChunks > 0 && (
          <span className="flex flex-row items-center gap-1" style={{ color: t.textMuted }}>
            <Database size={12} style={{ color: t.textDim }} />
            {totalFiles} files / {totalChunks.toLocaleString()} chunks
          </span>
        )}
        <button
          onClick={handleReindex}
          disabled={reindex.isPending}
          className="flex flex-row items-center gap-1.5 text-xs font-semibold ml-auto"
          style={{
            padding: "4px 12px",
            borderRadius: 5,
            background: reindex.isPending ? t.inputBg : t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            cursor: reindex.isPending ? "default" : "pointer",
            color: reindex.isPending ? t.textDim : t.text,
            opacity: reindex.isPending ? 0.6 : 1,
          }}
        >
          <RefreshCw size={11} style={reindex.isPending ? { animation: "spin 1s linear infinite" } as any : undefined} />
          {reindex.isPending ? "Reindexing\u2026" : "Reindex"}
        </button>
        {reindex.isSuccess && <span className="text-xs" style={{ color: "#14b8a6" }}>Done</span>}
        {reindex.isError && <span className="text-xs" style={{ color: t.dangerMuted }}>Failed</span>}
      </div>

      {/* Workspace defaults editor */}
      <WorkspaceDefaultsEditor workspaceId={workspaceId} />

      {/* Per-bot compact table */}
      <div className="flex flex-col gap-1 mt-1">
        <span className="text-xs font-semibold" style={{ color: t.textMuted }}>Per-bot indexing</span>
        <BotIndexTable bots={data.bots} indexedFiles={indexedFiles} />
      </div>
    </div>
  );
}
