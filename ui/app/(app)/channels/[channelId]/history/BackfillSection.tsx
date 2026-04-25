import { useCallback, useState } from "react";
import { AlertTriangle, Play, RotateCw } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { ActionButton, InfoBanner, SaveStatusPill, SettingsStatGrid } from "@/src/components/shared/SettingsControls";

export type SectionsStats = {
  scope?: "current" | "all";
  coverage_mode?: "current" | "inventory";
  total_messages: number;
  covered_messages: number;
  estimated_remaining: number;
  all_section_count?: number;
  other_session_section_count?: number;
  files_ok: number;
  files_missing: number;
  files_none: number;
  periods_missing: number;
};

export function BackfillButton({ channelId, historyMode }: { channelId: string; historyMode: string }) {
  const [running, setRunning] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<{ repaired: number } | null>(null);
  const [progress, setProgress] = useState<{ section: number; total: number; title?: string } | null>(null);
  const [result, setResult] = useState<{ sections: number; error?: string } | null>(null);
  const queryClient = useQueryClient();
  const { data: sectionsData } = useQuery({
    queryKey: ["channel-sections", channelId, "current"],
    queryFn: () => apiFetch<{ total: number; stats: SectionsStats }>(`/api/v1/admin/channels/${channelId}/sections?scope=current`),
  });
  const existingSections = sectionsData?.total ?? 0;
  const stats = sectionsData?.stats;

  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const doRunBackfill = useCallback(async (clearExisting: boolean) => {

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

  const runBackfill = useCallback((clearExisting: boolean) => {
    if (clearExisting && existingSections > 0) {
      setShowClearConfirm(true);
      return;
    }
    doRunBackfill(clearExisting);
  }, [doRunBackfill, existingSections]);

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
    ? Math.min(100, Math.round((stats.covered_messages / stats.total_messages) * 100)) : 0;
  const progressPct = progress && progress.total > 0
    ? Math.round((progress.section / progress.total) * 100) : 0;

  return (
    <div className="flex flex-col gap-3 py-1">
      {/* Coverage bar — shown when sections exist and stats are available */}
      {stats && stats.coverage_mode !== "inventory" && existingSections > 0 && (
        <div className="flex flex-col gap-2">
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-overlay">
            <div
              className={`h-full rounded-full transition-[width] ${pct >= 100 ? "bg-success" : "bg-warning"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <SettingsStatGrid
            items={[
              { label: "Covered", value: `${stats.covered_messages}/${stats.total_messages}`, tone: pct >= 100 ? "success" : "warning" },
              { label: "Sections", value: existingSections.toLocaleString() },
              { label: "Remaining", value: stats.estimated_remaining > 0 ? `~${stats.estimated_remaining}` : "0", tone: stats.estimated_remaining > 0 ? "warning" : "success" },
              { label: "Transcript files", value: stats.files_missing > 0 ? `${stats.files_missing} missing` : "OK", tone: stats.files_missing > 0 ? "warning" : "success" },
            ]}
          />
          {stats.files_missing > 0 && (
            <InfoBanner variant="warning" icon={<AlertTriangle size={12} />}>
              {stats.files_missing} section{stats.files_missing !== 1 ? "s" : ""} missing transcript files — re-run backfill to regenerate
            </InfoBanner>
          )}
          {stats.periods_missing > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-warning-muted">
              <AlertTriangle size={12} className="shrink-0" />
              <span className="min-w-0">
                {stats.periods_missing} section{stats.periods_missing !== 1 ? "s" : ""} missing timestamps
              </span>
              <ActionButton
                label={repairing ? "Repairing..." : "Repair"}
                onPress={runRepairPeriods}
                disabled={repairing}
                variant="secondary"
                size="small"
              />
              {repairResult && (
                <SaveStatusPill tone={repairResult.repaired >= 0 ? "saved" : "error"} label={repairResult.repaired >= 0 ? `Fixed ${repairResult.repaired}` : "Failed"} />
              )}
            </div>
          )}
        </div>
      )}

      {stats && existingSections === 0 && (stats.other_session_section_count ?? 0) > 0 && (
        <InfoBanner variant="info">
          This session has no archived sections yet. {stats.other_session_section_count} section{stats.other_session_section_count === 1 ? "" : "s"} exist in other sessions for this channel.
        </InfoBanner>
      )}

      {/* Buttons */}
      <div className="flex flex-wrap items-center gap-2">
        {existingSections > 0 && stats && stats.estimated_remaining > 0 && (
          <ActionButton
            label={running ? "Resuming..." : "Resume Backfill"}
            onPress={() => runBackfill(false)}
            disabled={running}
            icon={<Play size={12} />}
            size="small"
          />
        )}
        {existingSections > 0 ? (
          <ActionButton
            label="Re-chunk from Scratch"
            onPress={() => runBackfill(true)}
            disabled={running}
            icon={<RotateCw size={12} />}
            variant="secondary"
            size="small"
          />
        ) : (
          <ActionButton
            label={running ? "Backfilling..." : "Backfill Sections"}
            onPress={() => runBackfill(false)}
            disabled={running}
            icon={<Play size={12} />}
            size="small"
          />
        )}
        <span className="min-w-[220px] flex-1 text-[11px] leading-snug text-text-dim">
          {existingSections > 0 && stats && stats.estimated_remaining > 0
            ? "Resume adds new sections for uncovered messages in the current session. Re-chunk deletes this session's sections and starts fresh."
            : existingSections > 0
            ? "Current session messages are covered. Re-chunk to regenerate this session with different settings."
            : "Chunk the current session into navigable sections with .md transcripts."
          }
        </span>
      </div>

      {/* Progress bar during backfill */}
      {progress && progress.total > 0 && (
        <div className="flex flex-col gap-1">
          <div className="text-[11px] text-text-muted">
            Section {progress.section}/{progress.total}{progress.title ? `: "${progress.title}"` : ""}
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-surface-overlay">
            <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${progressPct}%` }} />
          </div>
        </div>
      )}
      {result && !result.error && (
        <SaveStatusPill tone="saved" label={`Done - ${result.sections} section${result.sections !== 1 ? "s" : ""} created`} />
      )}
      {result?.error && (
        <InfoBanner variant="danger">{result.error}</InfoBanner>
      )}
      <ConfirmDialog
        open={showClearConfirm}
        title="Re-chunk Sections"
        message={`This will delete all ${existingSections} existing section${existingSections !== 1 ? "s" : ""} for the current session (DB + .history files) and re-chunk it from scratch. Continue?`}
        confirmLabel="Re-chunk"
        variant="warning"
        onConfirm={() => { setShowClearConfirm(false); doRunBackfill(true); }}
        onCancel={() => setShowClearConfirm(false)}
      />
    </div>
  );
}
