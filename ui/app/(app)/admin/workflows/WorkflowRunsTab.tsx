import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useMemo } from "react";

import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { useWorkflowRuns } from "@/src/api/hooks/useWorkflows";
import { Play, ListX } from "lucide-react";
import type { WorkflowRun } from "@/src/types/api";

import { StatusBadge, fmtTime, getStatusStyle, useElapsed, formatStepDuration } from "./WorkflowRunHelpers";
import WorkflowRunDetail from "./WorkflowRunDetail";
import WorkflowTriggerModal from "./WorkflowTriggerModal";
import { StatusFilterChips, filterRuns, type RunStatusFilter } from "./StatusFilterChips";

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function WorkflowRunsTab({ workflowId, initialRunId }: { workflowId: string; initialRunId?: string }) {
  const t = useThemeTokens();
  const { width } = useWindowSize();
  const isMobile = width < 768;

  const { data: runs, isLoading } = useWorkflowRuns(workflowId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null);
  const [showTrigger, setShowTrigger] = useState(false);
  const [statusFilter, setStatusFilter] = useState<RunStatusFilter>("all");

  const filteredRuns = useMemo(
    () => (runs ? filterRuns(runs, statusFilter) : []),
    [runs, statusFilter],
  );

  // Desktop auto-select: pick first run if nothing is selected,
  // or if the current selection isn't visible in the filtered list.
  const effectiveSelectedRunId = useMemo(() => {
    if (isMobile) return selectedRunId;
    if (selectedRunId && filteredRuns.some((r) => r.id === selectedRunId)) return selectedRunId;
    return filteredRuns.length > 0 ? filteredRuns[0].id : null;
  }, [isMobile, selectedRunId, filteredRuns]);

  // Mobile: full-page navigation (current behavior)
  if (isMobile && selectedRunId) {
    return (
      <WorkflowRunDetail
        runId={selectedRunId}
        workflowId={workflowId}
        onBack={() => setSelectedRunId(null)}
        onNavigateToRun={(id) => setSelectedRunId(id)}
      />
    );
  }

  // -- Shared pieces --

  const header = (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
      <span style={{ color: t.textMuted, fontSize: 12 }}>
        {runs ? `${runs.length} run${runs.length !== 1 ? "s" : ""}` : ""}
      </span>
      <button
        onClick={() => setShowTrigger(true)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 5,
          padding: "5px 12px", fontSize: 12, fontWeight: 600,
          border: "none", borderRadius: 6,
          background: t.accent, color: "#fff", cursor: "pointer",
        }}
      >
        <Play size={13} />
        Trigger Run
      </button>
    </div>
  );

  const filters = runs && runs.length > 0 ? (
    <StatusFilterChips runs={runs} active={statusFilter} onChange={setStatusFilter} />
  ) : null;

  const runList = isLoading ? (
    <div style={{ alignItems: "center", padding: 24 }}>
      <Spinner />
    </div>
  ) : !runs || runs.length === 0 ? (
    <div style={{
      padding: 32, textAlign: "center", color: t.textMuted, fontSize: 13,
      background: t.codeBg, borderRadius: 8, border: `1px solid ${t.surfaceBorder}`,
    }}>
      No runs yet. Trigger one to get started.
    </div>
  ) : (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {filteredRuns.map((run) => (
        <RunCard
          key={run.id}
          run={run}
          t={t}
          selected={run.id === effectiveSelectedRunId}
          onSelect={() => setSelectedRunId(run.id)}
        />
      ))}
      {filteredRuns.length === 0 && statusFilter !== "all" && (
        <div style={{
          padding: 24, textAlign: "center", color: t.textDim, fontSize: 12,
        }}>
          No {statusFilter.replace(/_/g, " ")} runs.
        </div>
      )}
    </div>
  );

  const triggerModal = showTrigger ? (
    <WorkflowTriggerModal
      workflowId={workflowId}
      onTriggered={(runId) => {
        setShowTrigger(false);
        setSelectedRunId(runId);
      }}
      onClose={() => setShowTrigger(false)}
    />
  ) : null;

  // Mobile: just list view
  if (isMobile) {
    return (
      <div style={{ gap: 12 }}>
        {header}
        {filters}
        {runList}
        {triggerModal}
      </div>
    );
  }

  // Desktop: two-pane layout
  return (
    <>
      <div style={{
        display: "flex", flexDirection: "row", flex: 1, minHeight: 0, gap: 16,
      }}>
        {/* Left pane: header + filters + run list */}
        <div style={{
          width: 320, flexShrink: 0, overflow: "auto",
          display: "flex", flexDirection: "column", gap: 10,
          paddingRight: 4,
        }}>
          {header}
          {filters}
          {runList}
        </div>

        {/* Right pane: run detail or empty state */}
        <div style={{
          flex: 1, minWidth: 0, overflow: "auto",
          display: "flex", flexDirection: "column",
          background: t.codeBg,
          borderRadius: 10,
          border: `1px solid ${t.surfaceBorder}`,
          padding: 16,
        }}>
          {effectiveSelectedRunId ? (
            <WorkflowRunDetail
              runId={effectiveSelectedRunId}
              workflowId={workflowId}
              onBack={() => setSelectedRunId(null)}
              onNavigateToRun={(id) => setSelectedRunId(id)}
              embedded
            />
          ) : (
            <RunDetailEmptyState t={t} />
          )}
        </div>
      </div>
      {triggerModal}
    </>
  );
}

// ---------------------------------------------------------------------------
// Run card (list item) — enhanced with selected state + status border
// ---------------------------------------------------------------------------

function RunCard({ run, t, selected, onSelect }: {
  run: WorkflowRun;
  t: ThemeTokens;
  selected: boolean;
  onSelect: () => void;
}) {
  const isActive = run.status === "running" || run.status === "awaiting_approval";
  const elapsed = useElapsed(run.created_at, isActive);
  const duration = run.completed_at ? formatStepDuration(run.created_at, run.completed_at) : null;
  const statusStyle = getStatusStyle(run.status, t);

  const doneSteps = run.step_states.filter((s) =>
    s.status === "done" || s.status === "skipped" || s.status === "failed"
  ).length;
  const totalSteps = run.step_states.length;

  return (
    <button type="button"
      onClick={onSelect}
      style={{
        backgroundColor: selected ? t.accentSubtle : t.codeBg,
        borderRadius: 8,
        borderWidth: 1,
        borderColor: selected ? t.accentBorder : t.surfaceBorder,
        borderLeftWidth: 3,
        borderLeftColor: statusStyle.text,
        padding: 10,
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <StatusBadge status={run.status} t={t} />
          <span style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>
            {run.id.slice(0, 8)}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          {(duration || elapsed) && (
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {duration || elapsed}
            </span>
          )}
          <span style={{ fontSize: 10, color: t.textDim }}>
            {doneSteps}/{totalSteps}
          </span>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginTop: 5 }}>
        <span style={{ fontSize: 11, color: t.textDim }}>
          {run.bot_id}
        </span>
        {run.triggered_by && (
          <span style={{ fontSize: 11, color: t.textDim }}>
            via {run.triggered_by}
          </span>
        )}
        {run.session_mode === "shared" && (
          <span style={{
            fontSize: 10, color: t.purple, background: t.purpleSubtle,
            border: `1px solid ${t.purpleBorder}`, borderRadius: 4,
            padding: "0 4px",
          }}>
            shared
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textDim, marginLeft: "auto" }}>
          {fmtTime(run.created_at)}
        </span>
      </div>
      {/* Mini step bar */}
      <div style={{ display: "flex", flexDirection: "row", gap: 2, marginTop: 6, height: 3, borderRadius: 2, overflow: "hidden" }}>
        {run.step_states.map((s, i) => {
          const color =
            s.status === "done" ? t.success :
            s.status === "running" ? t.accent :
            s.status === "failed" ? t.danger :
            s.status === "skipped" ? t.surfaceBorder :
            t.inputBorder;
          return <div key={i} style={{ flex: 1, background: color, borderRadius: 1 }} />;
        })}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Empty state for right pane
// ---------------------------------------------------------------------------

function RunDetailEmptyState({ t }: { t: ThemeTokens }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      flex: 1, padding: 32, color: t.textDim,
    }}>
      <ListX size={28} color={t.surfaceBorder} />
      <span style={{ color: t.textDim, fontSize: 13, marginTop: 12, textAlign: "center" }}>
        Select a run to view its details.
      </span>
    </div>
  );
}
