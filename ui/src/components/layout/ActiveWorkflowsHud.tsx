import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Activity, X, ChevronDown, ChevronUp } from "lucide-react";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import {
  useActiveWorkflowRuns,
  useCancelWorkflowRun,
} from "../../api/hooks/useWorkflows";
import { useThemeTokens } from "../../theme/tokens";
import type { WorkflowRun } from "../../types/api";

function elapsed(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function stepProgress(run: WorkflowRun): string {
  const done = run.step_states.filter(
    (s) => s.status === "done" || s.status === "skipped" || s.status === "failed",
  ).length;
  return `${done}/${run.step_states.length}`;
}

function statusColor(
  run: WorkflowRun,
  t: ReturnType<typeof useThemeTokens>,
): string {
  if (run.status === "awaiting_approval") return t.warning;
  const hasFailed = run.step_states.some((s) => s.status === "failed");
  if (hasFailed) return t.danger;
  return t.accent;
}

export function ActiveWorkflowsHud() {
  const { data: runs } = useActiveWorkflowRuns();
  const cancelMut = useCancelWorkflowRun();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const t = useThemeTokens();

  const [expanded, setExpanded] = useState(false);
  const [visible, setVisible] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<string | null>(null);

  // Force re-render every second for elapsed time
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!runs || runs.length === 0) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [runs?.length]);

  const activeRuns = runs ?? [];
  const hasRuns = activeRuns.length > 0;

  // Skip if already on workflows admin page
  const onWorkflowsPage = pathname.includes("/admin/workflows");

  // Mount/unmount with transition
  useEffect(() => {
    if (hasRuns && !onWorkflowsPage) {
      setMounted(true);
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
      setExpanded(false);
      const timer = setTimeout(() => setMounted(false), 200);
      return () => clearTimeout(timer);
    }
  }, [hasRuns, onWorkflowsPage]);

  if (!mounted) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: 16,
        right: 16,
        zIndex: 60,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          pointerEvents: "auto",
          background: t.surfaceRaised,
          border: `1px solid ${t.accentBorder}`,
          borderRadius: 10,
          overflow: "hidden",
          opacity: visible ? 1 : 0,
          transform: `translateY(${visible ? 0 : 8}px)`,
          transition: "opacity 200ms ease-out, transform 200ms ease-out",
          boxShadow: "0 4px 16px rgba(0,0,0,0.2)",
          minWidth: 280,
          maxWidth: 380,
        }}
      >
        {/* Header bar -- always visible */}
        <button
          className="hud-fab"
          onClick={() => setExpanded(!expanded)}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            paddingLeft: 12,
            paddingRight: 12,
            paddingTop: 8,
            paddingBottom: 8,
            width: "100%",
            border: "none",
            background: "transparent",
            cursor: "pointer",
            textAlign: "left",
            color: "inherit",
            font: "inherit",
          }}
        >
          <Activity size={14} color={t.accent} />
          <span
            style={{
              flex: 1,
              fontSize: 12,
              fontWeight: 600,
              color: t.text,
            }}
          >
            {activeRuns.length} workflow{activeRuns.length !== 1 ? "s" : ""}{" "}
            running
          </span>
          {expanded ? (
            <ChevronUp size={14} color={t.textDim} />
          ) : (
            <ChevronDown size={14} color={t.textDim} />
          )}
        </button>

        {/* Compact: mini progress bars */}
        {!expanded && (
          <div
            style={{
              display: "flex", flexDirection: "row",
              gap: 3,
              padding: "0 12px 8px",
            }}
          >
            {activeRuns.slice(0, 5).map((run) => (
              <div
                key={run.id}
                style={{
                  flex: 1,
                  height: 4,
                  borderRadius: 2,
                  background: t.surfaceBorder,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    borderRadius: 2,
                    background: statusColor(run, t),
                    width: `${Math.max(
                      10,
                      (run.step_states.filter(
                        (s) =>
                          s.status === "done" ||
                          s.status === "skipped" ||
                          s.status === "failed",
                      ).length /
                        Math.max(run.step_states.length, 1)) *
                        100,
                    )}%`,
                    transition: "width 0.3s",
                  }}
                />
              </div>
            ))}
          </div>
        )}

        {/* Expanded: run details */}
        {expanded && (
          <div
            style={{
              borderTop: `1px solid ${t.surfaceBorder}`,
              maxHeight: 300,
              overflowY: "auto",
            }}
          >
            {activeRuns.map((run) => (
              <RunRow
                key={run.id}
                run={run}
                t={t}
                onNavigate={() => {
                  navigate(
                    `/admin/workflows/${run.workflow_id}?runId=${run.id}`,
                  );
                  setExpanded(false);
                }}
                onCancel={() => setCancelTarget(run.id)}
              />
            ))}
          </div>
        )}
      </div>
      <ConfirmDialog
        open={cancelTarget !== null}
        title="Cancel Workflow"
        message="Cancel this workflow run? In-flight steps will be abandoned."
        confirmLabel="Cancel Run"
        variant="danger"
        onConfirm={() => {
          if (cancelTarget) cancelMut.mutate(cancelTarget);
          setCancelTarget(null);
        }}
        onCancel={() => setCancelTarget(null)}
      />
    </div>
  );
}

function RunRow({
  run,
  t,
  onNavigate,
  onCancel,
}: {
  run: WorkflowRun;
  t: ReturnType<typeof useThemeTokens>;
  onNavigate: () => void;
  onCancel: () => void;
}) {
  const color = statusColor(run, t);

  return (
    <button
      type="button"
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
        cursor: "pointer",
        background: "none",
        border: "none",
        width: "100%",
        textAlign: "left",
        font: "inherit",
        color: "inherit",
      }}
      onClick={onNavigate}
    >
      {/* Status dot */}
      <div
        style={{
          width: 8,
          height: 8,
          borderRadius: 4,
          background: color,
          flexShrink: 0,
          animation:
            run.status === "running"
              ? "pulse 2s ease-in-out infinite"
              : undefined,
        }}
      />

      {/* Info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: t.text,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {run.workflow_id}
        </div>
        <div style={{ display: "flex", flexDirection: "row", gap: 8, fontSize: 11, color: t.textDim }}>
          <span>{stepProgress(run)} steps</span>
          <span>{elapsed(run.created_at)}</span>
          {run.status === "awaiting_approval" && (
            <span style={{ color: t.warning, fontWeight: 600 }}>
              needs approval
            </span>
          )}
        </div>
      </div>

      {/* Step mini bar */}
      <div
        style={{
          display: "flex", flexDirection: "row",
          gap: 2,
          width: 48,
          flexShrink: 0,
        }}
      >
        {run.step_states.map((s, i) => {
          const c =
            s.status === "done"
              ? t.success
              : s.status === "running"
                ? t.accent
                : s.status === "failed"
                  ? t.danger
                  : s.status === "skipped"
                    ? t.surfaceBorder
                    : t.inputBorder;
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: 4,
                borderRadius: 1,
                background: c,
              }}
            />
          );
        })}
      </div>

      {/* Cancel button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onCancel();
        }}
        style={{
          padding: 4,
          borderRadius: 4,
          flexShrink: 0,
          border: "none",
          background: "transparent",
          cursor: "pointer",
          display: "flex", flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <X size={12} color={t.textDim} />
      </button>
    </button>
  );
}
