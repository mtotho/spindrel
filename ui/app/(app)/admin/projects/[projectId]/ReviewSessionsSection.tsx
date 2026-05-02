import { Link } from "react-router-dom";
import { ExternalLink, GitMerge } from "lucide-react";

import { ActionButton, EmptyState, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Section } from "@/src/components/shared/FormControls";
import type { ProjectCodingRunReviewSessionLedger } from "@/src/types/api";

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["finalized", "reviewed", "completed", "complete", "accepted"].includes(status)) return "success";
  if (["active", "running", "pending", "partially_reviewed", "needs_review", "blocked"].includes(status)) return "warning";
  if (["failed", "rejected"].includes(status)) return "danger";
  return "neutral";
}

function formatTime(value?: string | null) {
  if (!value) return "No timestamp";
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function shortId(value?: string | null) {
  return value ? value.slice(0, 8) : "unknown";
}

function sourceLine(session: ProjectCodingRunReviewSessionLedger) {
  const packs = session.source_work_packs ?? [];
  if (packs.length > 0) {
    return packs.slice(0, 2).map((pack) => pack.title).join(", ") + (packs.length > 2 ? ` +${packs.length - 2}` : "");
  }
  const batches = session.launch_batch_ids ?? [];
  if (batches.length > 0) return `Batch ${batches.map(shortId).join(", ")}`;
  return "Direct run selection";
}

function outcomeLine(session: ProjectCodingRunReviewSessionLedger) {
  const counts = session.outcome_counts ?? {};
  const parts = Object.entries(counts)
    .filter(([, count]) => Number(count) > 0)
    .map(([status, count]) => `${count} ${status.replaceAll("_", " ")}`);
  return parts.length > 0 ? parts.join(", ") : "No final decisions yet";
}

function evidenceLine(session: ProjectCodingRunReviewSessionLedger) {
  const evidence = session.evidence ?? {};
  return `${evidence.tests_count ?? 0} tests · ${evidence.screenshots_count ?? 0} screenshots · ${evidence.changed_files_count ?? 0} files`;
}

function mergeLine(session: ProjectCodingRunReviewSessionLedger) {
  const merge = session.merge ?? {};
  const method = merge.method ? String(merge.method) : "squash";
  const requested = Number(merge.requested_count ?? 0);
  if (requested <= 0) return `${method} merge not requested`;
  return `${method} merge ${Number(merge.completed_count ?? 0)}/${requested}`;
}

function RowLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text"
    >
      <ExternalLink size={13} />
      {children}
    </Link>
  );
}

export function ReviewSessionsSection({
  sessions,
  disabled,
  onSelectRuns,
}: {
  sessions: ProjectCodingRunReviewSessionLedger[];
  disabled: boolean;
  onSelectRuns: (runIds: string[]) => void;
}) {
  return (
    <Section
      title="Agent Review Sessions"
      description="Review agents that were launched from this Project. Open the active task to watch or guide the review."
    >
      <div data-testid="project-workspace-review-ledger" className="flex flex-col gap-2">
        {sessions.length === 0 ? (
          <EmptyState message="No Project review sessions have been launched yet." />
        ) : (
          sessions.map((session) => (
            <SettingsControlRow
              key={session.id}
              leading={<GitMerge size={14} />}
              title={session.title || `Review ${shortId(session.task_id)}`}
              description={
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span>
                    {session.run_count} run{session.run_count === 1 ? "" : "s"} · {outcomeLine(session)} · {mergeLine(session)}
                  </span>
                  <span className="truncate text-[11px] text-text-dim">Sources: {sourceLine(session)}</span>
                  <span className="truncate text-[11px] text-text-dim">Evidence: {evidenceLine(session)}</span>
                  {session.latest_summary && (
                    <span className="truncate text-[11px] text-text-dim">Summary: {session.latest_summary}</span>
                  )}
                  <span className="truncate text-[11px] text-text-dim">
                    Latest activity: {formatTime(session.latest_activity_at || session.created_at)}
                  </span>
                </span>
              }
              meta={<StatusBadge label={session.status} variant={statusTone(session.status)} />}
              action={
                <div className="flex flex-wrap justify-end gap-1">
                  <ActionButton
                    label="Select reviewed runs"
                    size="small"
                    variant="ghost"
                    disabled={disabled || !(session.selected_run_ids?.length)}
                    onPress={() => onSelectRuns(session.selected_run_ids ?? [])}
                  />
                  <RowLink to={`/admin/tasks/${session.task_id}`}>
                    {session.actions?.active ? "Open active review" : "View summary"}
                  </RowLink>
                </div>
              }
            />
          ))
        )}
      </div>
    </Section>
  );
}
