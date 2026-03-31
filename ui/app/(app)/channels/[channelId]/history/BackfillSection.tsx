import { useCallback, useState } from "react";
import { AlertTriangle, Play, RotateCw } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";

export type SectionsStats = {
  total_messages: number;
  covered_messages: number;
  estimated_remaining: number;
  files_ok: number;
  files_missing: number;
  files_none: number;
  periods_missing: number;
};

export function BackfillButton({ channelId, historyMode }: { channelId: string; historyMode: string }) {
  const t = useThemeTokens();
  const [running, setRunning] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<{ repaired: number } | null>(null);
  const [progress, setProgress] = useState<{ section: number; total: number; title?: string } | null>(null);
  const [result, setResult] = useState<{ sections: number; error?: string } | null>(null);
  const queryClient = useQueryClient();
  const { data: sectionsData } = useQuery({
    queryKey: ["channel-sections", channelId],
    queryFn: () => apiFetch<{ total: number; stats: SectionsStats }>(`/api/v1/admin/channels/${channelId}/sections`),
  });
  const existingSections = sectionsData?.total ?? 0;
  const stats = sectionsData?.stats;

  const runBackfill = useCallback(async (clearExisting: boolean) => {
    if (clearExisting && existingSections > 0 && !window.confirm(
      `This will delete all ${existingSections} existing section${existingSections !== 1 ? "s" : ""} (DB + .history files) and re-chunk everything from scratch. Continue?`
    )) return;

    setRunning(true);
    setProgress(null);
    setResult(null);
    try {
      const { task_id } = await apiFetch<{ task_id: string }>(
        `/api/v1/admin/channels/${channelId}/backfill-sections`,
        { method: "POST", body: JSON.stringify({
          history_mode: historyMode,
          clear_existing: clearExisting,
        }) },
      );

      // Poll every 2s until complete or failed
      while (true) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await apiFetch<{
          status: string; sections_created: number; total_chunks: number;
          current_title?: string; error?: string;
        }>(`/api/v1/admin/channels/${channelId}/backfill-status/${task_id}`);

        if (job.status === "running") {
          setProgress({ section: job.sections_created, total: job.total_chunks, title: job.current_title });
        } else if (job.status === "complete") {
          setResult({ sections: job.sections_created });
          break;
        } else if (job.status === "failed") {
          setResult({ sections: job.sections_created, error: job.error || "Backfill failed" });
          break;
        }
      }
    } catch (e) {
      setResult({ sections: 0, error: e instanceof Error ? e.message : "Unknown error" });
    } finally {
      setRunning(false);
      queryClient.invalidateQueries({ queryKey: ["channel-sections", channelId] });
    }
  }, [channelId, historyMode, queryClient, existingSections]);

  const runRepairPeriods = useCallback(async () => {
    setRepairing(true);
    setRepairResult(null);
    try {
      const res = await apiFetch<{ repaired: number }>(
        `/api/v1/admin/channels/${channelId}/repair-section-periods`,
        { method: "POST" },
      );
      setRepairResult(res);
    } catch (e) {
      setRepairResult({ repaired: -1 });
    } finally {
      setRepairing(false);
      queryClient.invalidateQueries({ queryKey: ["channel-sections", channelId] });
    }
  }, [channelId, queryClient]);

  const pct = stats && stats.total_messages > 0
    ? Math.round((stats.covered_messages / stats.total_messages) * 100) : 0;
  const progressPct = progress && progress.total > 0
    ? Math.round((progress.section / progress.total) * 100) : 0;

  return (
    <div style={{ padding: "10px 0" }}>
      {/* Coverage bar — shown when sections exist and stats are available */}
      {stats && existingSections > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{
            height: 6, borderRadius: 3, background: t.surfaceOverlay, overflow: "hidden", marginBottom: 4,
          }}>
            <div style={{
              height: "100%", borderRadius: 3, transition: "width 0.3s",
              width: `${pct}%`,
              background: pct >= 100 ? t.success : t.warning,
            }} />
          </div>
          <div style={{ fontSize: 11, color: t.textMuted }}>
            {stats.covered_messages}/{stats.total_messages} messages
            {" \u00b7 "}{existingSections} section{existingSections !== 1 ? "s" : ""}
            {stats.estimated_remaining > 0 && ` \u00b7 ~${stats.estimated_remaining} remaining`}
          </div>
          {stats.files_missing > 0 && (
            <div style={{ fontSize: 11, color: t.warningMuted, marginTop: 2 }}>
              <AlertTriangle size={10} style={{ display: "inline", verticalAlign: "middle", marginRight: 4 }} />
              {stats.files_missing} section{stats.files_missing !== 1 ? "s" : ""} missing transcript files — re-run backfill to regenerate
            </div>
          )}
          {stats.periods_missing > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.warningMuted, marginTop: 2 }}>
              <AlertTriangle size={10} style={{ flexShrink: 0 }} />
              <span>
                {stats.periods_missing} section{stats.periods_missing !== 1 ? "s" : ""} missing timestamps
              </span>
              <button
                onClick={runRepairPeriods}
                disabled={repairing}
                style={{
                  padding: "1px 8px", fontSize: 11, fontWeight: 600,
                  border: "none", cursor: repairing ? "default" : "pointer", borderRadius: 4,
                  background: t.warningSubtle, color: t.warningMuted,
                  opacity: repairing ? 0.6 : 1,
                }}
              >
                {repairing ? "Repairing..." : "Repair"}
              </button>
              {repairResult && (
                <span style={{ color: repairResult.repaired >= 0 ? t.success : t.danger }}>
                  {repairResult.repaired >= 0 ? `Fixed ${repairResult.repaired}` : "Failed"}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Buttons */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {existingSections > 0 && stats && stats.estimated_remaining > 0 && (
          <button
            onClick={() => runBackfill(false)}
            disabled={running}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: running ? "default" : "pointer", borderRadius: 6,
              background: running ? t.surfaceBorder : t.warningSubtle,
              color: running ? t.textDim : t.warningMuted,
              opacity: running ? 0.7 : 1,
              minHeight: 36,
            }}
          >
            <Play size={12} color={running ? t.textDim : t.warningMuted} />
            {running ? "Resuming..." : "Resume Backfill"}
          </button>
        )}
        {existingSections > 0 ? (
          <button
            onClick={() => runBackfill(true)}
            disabled={running}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: `1px solid ${t.surfaceBorder}`, cursor: running ? "default" : "pointer", borderRadius: 6,
              background: "transparent",
              color: running ? t.textDim : t.textMuted,
              opacity: running ? 0.7 : 1,
              minHeight: 36,
            }}
          >
            <RotateCw size={12} color={running ? t.textDim : t.textMuted} />
            Re-chunk from Scratch
          </button>
        ) : (
          <button
            onClick={() => runBackfill(false)}
            disabled={running}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: running ? "default" : "pointer", borderRadius: 6,
              background: running ? t.surfaceBorder : t.warningSubtle,
              color: running ? t.textDim : t.warningMuted,
              opacity: running ? 0.7 : 1,
              minHeight: 36,
            }}
          >
            <Play size={12} color={running ? t.textDim : t.warningMuted} />
            {running ? "Backfilling..." : "Backfill Sections"}
          </button>
        )}
        <span style={{ fontSize: 11, color: t.textDim, flex: 1, minWidth: 0 }}>
          {existingSections > 0 && stats && stats.estimated_remaining > 0
            ? "Resume adds new sections for uncovered messages. Re-chunk deletes everything and starts fresh."
            : existingSections > 0
            ? "All messages covered. Re-chunk to regenerate with different settings."
            : "Chunk existing messages into navigable sections with .md transcripts."
          }
        </span>
      </div>

      {/* Progress bar during backfill */}
      {progress && progress.total > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
            Section {progress.section}/{progress.total}{progress.title ? `: "${progress.title}"` : ""}
          </div>
          <div style={{
            height: 4, borderRadius: 2, background: t.surfaceOverlay, overflow: "hidden",
          }}>
            <div style={{
              height: "100%", borderRadius: 2, transition: "width 0.3s",
              width: `${progressPct}%`, background: t.accent,
            }} />
          </div>
        </div>
      )}
      {result && !result.error && (
        <div style={{ marginTop: 8, fontSize: 11, color: t.success }}>
          Done — {result.sections} section{result.sections !== 1 ? "s" : ""} created
        </div>
      )}
      {result?.error && (
        <div style={{ marginTop: 8, fontSize: 11, color: t.danger }}>
          {result.error}
        </div>
      )}
    </div>
  );
}
