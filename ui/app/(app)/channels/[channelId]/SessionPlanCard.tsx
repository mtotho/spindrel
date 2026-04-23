import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, CircleDashed, PauseCircle, PlayCircle } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useThemeTokens } from "@/src/theme/tokens";
import type { SessionPlan, SessionPlanRevisionDiff } from "./useSessionPlanMode";

export function SessionPlanCard({
  plan,
  sessionId,
  busy,
  showPath = false,
  currentRevision,
  acceptedRevision,
  staleMessage,
  onApprove,
  onExit,
  onStepStatus,
  onReplan,
}: {
  plan: SessionPlan;
  sessionId?: string;
  busy?: boolean;
  showPath?: boolean;
  currentRevision?: number | null;
  acceptedRevision?: number | null;
  staleMessage?: string | null;
  onApprove: () => void;
  onExit: () => void;
  onStepStatus: (stepId: string, status: "pending" | "in_progress" | "done" | "blocked") => void;
  onReplan?: () => void;
}) {
  const t = useThemeTokens();
  const historical = currentRevision != null && plan.revision !== currentRevision;
  const defaultCompareRevision = historical
    ? currentRevision
    : (acceptedRevision && acceptedRevision !== plan.revision ? acceptedRevision : null);
  const [compareRevision, setCompareRevision] = useState<number | null>(defaultCompareRevision ?? null);
  const effectiveCompareRevision = compareRevision ?? defaultCompareRevision ?? null;
  const revisionEntries = useMemo(
    () => (plan.revisions ?? []).slice().sort((a, b) => b.revision - a.revision),
    [plan.revisions],
  );
  const validationIssues = plan.validation?.issues ?? [];
  const blockingIssues = validationIssues.filter((issue) => issue.severity === "error");
  const warningIssues = validationIssues.filter((issue) => issue.severity === "warning");
  const approvalBlocked = !!blockingIssues.length;
  const runtime = plan.runtime;
  const planningState = plan.planning_state;
  const adherence = plan.adherence;
  const pendingOutcome = runtime?.pending_turn_outcome;
  const latestOutcome = adherence?.latest_outcome ?? runtime?.latest_outcome;
  const planningStateItems = [
    { label: "Decisions", items: planningState?.decisions ?? [] },
    { label: "Open questions", items: planningState?.open_questions ?? [] },
    { label: "Assumptions", items: planningState?.assumptions ?? [] },
    { label: "Constraints", items: planningState?.constraints ?? [] },
    { label: "Non-goals", items: planningState?.non_goals ?? [] },
    { label: "Evidence", items: planningState?.evidence ?? [] },
  ].filter((section) => section.items.length > 0);

  useEffect(() => {
    setCompareRevision(defaultCompareRevision ?? null);
  }, [defaultCompareRevision, plan.revision]);

  const diffQuery = useQuery({
    queryKey: ["session-plan-diff", sessionId, effectiveCompareRevision, plan.revision],
    enabled: !!sessionId && !!effectiveCompareRevision && effectiveCompareRevision !== plan.revision,
    queryFn: async () => {
      return apiFetch<SessionPlanRevisionDiff>(
        `/sessions/${sessionId}/plan/diff?from_revision=${effectiveCompareRevision}&to_revision=${plan.revision}`,
      );
    },
  });

  const statusTone = (() => {
    switch (plan.mode) {
      case "planning":
        return { bg: t.warningSubtle, border: t.warningBorder, text: t.warningMuted };
      case "executing":
        return { bg: t.surfaceOverlay, border: t.surfaceBorder, text: t.text };
      case "blocked":
        return { bg: t.dangerSubtle, border: t.dangerBorder, text: t.danger };
      case "done":
        return { bg: t.successSubtle, border: t.successBorder, text: t.success };
      default:
        return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textMuted };
    }
  })();

  const iconForStatus = (status: string) => {
    switch (status) {
      case "done":
        return <CheckCircle2 size={15} color={t.success} />;
      case "in_progress":
        return <PlayCircle size={15} color={t.accent} />;
      case "blocked":
        return <PauseCircle size={15} color={t.danger} />;
      default:
        return <Circle size={15} color={t.textDim} />;
    }
  };

  return (
    <div
      style={{
        border: `1px solid ${statusTone.border}`,
        background: t.surfaceRaised,
        borderRadius: 16,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{plan.title}</span>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                borderRadius: 999,
                padding: "4px 9px",
                fontSize: 11,
                fontWeight: 700,
                background: statusTone.bg,
                border: `1px solid ${statusTone.border}`,
                color: statusTone.text,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              <CircleDashed size={12} />
              {plan.mode}
            </span>
            <span style={{ fontSize: 11, color: t.textDim }}>
              rev {plan.revision}
              {acceptedRevision && acceptedRevision === plan.revision ? " • accepted" : ""}
              {historical && currentRevision ? ` • current rev ${currentRevision}` : ""}
            </span>
          </div>
          <div style={{ fontSize: 13, color: t.textMuted }}>{plan.summary}</div>
          {showPath && plan.path ? (
            <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>{plan.path}</div>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {plan.mode === "planning" && !historical && (
            <button
              type="button"
              onClick={onApprove}
              disabled={busy || approvalBlocked}
              className="inline-flex h-9 items-center gap-2 rounded-full border px-3 text-[12px] font-medium transition-colors"
              title={approvalBlocked ? "Resolve plan validation issues before approval." : undefined}
              style={{
                borderColor: approvalBlocked ? t.surfaceBorder : t.accent,
                color: approvalBlocked ? t.textDim : t.text,
                background: t.surface,
                opacity: approvalBlocked ? 0.65 : 1,
              }}
            >
              Approve & Execute
            </button>
          )}
          {(plan.mode === "executing" || plan.mode === "blocked") && !historical && onReplan ? (
            <button
              type="button"
              onClick={onReplan}
              disabled={busy}
              className="inline-flex h-9 items-center gap-2 rounded-full border px-3 text-[12px] font-medium transition-colors"
              style={{ borderColor: t.warningBorder, color: t.warningMuted, background: t.warningSubtle }}
            >
              Request Replan
            </button>
          ) : null}
          <button
            type="button"
            onClick={onExit}
            disabled={busy}
            className="inline-flex h-9 items-center gap-2 rounded-full border px-3 text-[12px] font-medium transition-colors"
            style={{ borderColor: t.surfaceBorder, color: t.textMuted, background: t.surface }}
          >
            Exit Plan Mode
          </button>
        </div>
      </div>

      {(historical || staleMessage) ? (
        <div
          style={{
            border: `1px solid ${t.warningBorder}`,
            background: t.warningSubtle,
            color: t.warningMuted,
            borderRadius: 12,
            padding: "10px 12px",
            fontSize: 12,
          }}
        >
          {staleMessage ?? `This card is showing historical revision ${plan.revision}. Current planning state is on revision ${currentRevision}.`}
        </div>
      ) : null}

      {(runtime || validationIssues.length > 0) ? (
        <section
          style={{
            border: `1px solid ${approvalBlocked ? t.warningBorder : t.surfaceBorder}`,
            background: approvalBlocked ? t.warningSubtle : t.surface,
            borderRadius: 12,
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {runtime ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: t.textDim }}>
              <span style={{ fontWeight: 700, color: t.textMuted }}>Runtime</span>
              {runtime.next_action ? <span>next: {runtime.next_action}</span> : null}
              {runtime.current_step_id ? <span>current: {runtime.current_step_id}</span> : null}
              {runtime.next_step_id && runtime.next_step_id !== runtime.current_step_id ? <span>up next: {runtime.next_step_id}</span> : null}
              {runtime.accepted_revision ? <span>accepted rev {runtime.accepted_revision}</span> : null}
              {runtime.adherence_status ? <span>adherence: {runtime.adherence_status}</span> : null}
              {pendingOutcome?.reason ? <span>pending outcome: {pendingOutcome.reason}</span> : null}
              {runtime.replan?.reason ? <span>replan: {runtime.replan.reason}</span> : null}
            </div>
          ) : null}
          {pendingOutcome ? (
            <div style={{ fontSize: 12, color: t.warningMuted }}>
              Pending outcome: record progress, verification, blocker, replan, or no-progress before more execution.
            </div>
          ) : null}
          {latestOutcome ? (
            <div style={{ fontSize: 12, color: t.textDim }}>
              Latest outcome: {latestOutcome.outcome ?? "recorded"}{latestOutcome.summary ? ` - ${latestOutcome.summary}` : ""}
            </div>
          ) : null}
          {adherence?.latest_evidence ? (
            <div style={{ fontSize: 12, color: adherence.status === "warning" ? t.warningMuted : t.textDim }}>
              Latest evidence: {adherence.latest_evidence.summary ?? adherence.latest_evidence.tool_name ?? "recorded"}
            </div>
          ) : null}
          {validationIssues.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700, color: approvalBlocked ? t.warningMuted : t.textMuted }}>
                <AlertTriangle size={14} />
                {approvalBlocked ? `${blockingIssues.length} issue${blockingIssues.length === 1 ? "" : "s"} before approval` : `${warningIssues.length} warning${warningIssues.length === 1 ? "" : "s"}`}
              </div>
              {validationIssues.slice(0, 4).map((issue) => (
                <div key={`${issue.code}-${issue.field}-${issue.message}`} style={{ fontSize: 12, color: issue.severity === "error" ? t.warningMuted : t.textDim }}>
                  {issue.severity === "error" ? "Required" : "Warning"}: {issue.message}
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {planningStateItems.length > 0 ? (
        <section
          style={{
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surface,
            borderRadius: 12,
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Planning Notes</div>
          {planningStateItems.slice(0, 4).map((section) => (
            <div key={section.label} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ fontSize: 11, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {section.label}
              </div>
              {section.items.slice(-3).map((item, idx) => (
                <div key={`${section.label}-${idx}-${item.text}`} style={{ fontSize: 12, color: t.textMuted }}>
                  {item.text}
                </div>
              ))}
            </div>
          ))}
        </section>
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr)", gap: 10 }}>
        <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Scope</div>
          <div style={{ fontSize: 13, color: t.textMuted }}>{plan.scope}</div>
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Checklist</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {plan.steps.map((step) => (
              <div
                key={step.id}
                style={{
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 12,
                  padding: 10,
                  background: t.surface,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                  <span style={{ marginTop: 1 }}>{iconForStatus(step.status)}</span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 13, color: t.text }}>{step.label}</div>
                    <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>{step.id}</div>
                    {step.note && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 4 }}>{step.note}</div>}
                  </div>
                </div>
                {plan.mode !== "planning" && !historical ? (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {step.status !== "in_progress" && (
                      <button
                        type="button"
                        onClick={() => onStepStatus(step.id, "in_progress")}
                        disabled={busy}
                        className="inline-flex h-8 items-center rounded-full border px-3 text-[11px] font-medium"
                        style={{ borderColor: t.surfaceBorder, background: t.surfaceRaised, color: t.textMuted }}
                      >
                        In Progress
                      </button>
                    )}
                    {step.status !== "done" && (
                      <button
                        type="button"
                        onClick={() => onStepStatus(step.id, "done")}
                        disabled={busy}
                        className="inline-flex h-8 items-center rounded-full border px-3 text-[11px] font-medium"
                        style={{ borderColor: t.successBorder, background: t.successSubtle, color: t.success }}
                      >
                        Done
                      </button>
                    )}
                    {step.status !== "blocked" && (
                      <button
                        type="button"
                        onClick={() => onStepStatus(step.id, "blocked")}
                        disabled={busy}
                        className="inline-flex h-8 items-center rounded-full border px-3 text-[11px] font-medium"
                        style={{ borderColor: t.dangerBorder, background: t.dangerSubtle, color: t.danger }}
                      >
                        Blocked
                      </button>
                    )}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        {plan.open_questions.length > 0 && (
          <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Open Questions</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {plan.open_questions.map((item) => (
                <div key={item} style={{ fontSize: 13, color: t.textMuted }}>{`\u2022 ${item}`}</div>
              ))}
            </div>
          </section>
        )}

        {revisionEntries.length > 1 && (
          <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Revision History</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {revisionEntries.map((entry) => {
                const selected = effectiveCompareRevision === entry.revision;
                return (
                  <button
                    key={`${entry.revision}-${entry.source}`}
                    type="button"
                    onClick={() => setCompareRevision(selected ? null : entry.revision)}
                    style={{
                      border: `1px solid ${selected ? t.accent : t.surfaceBorder}`,
                      background: selected ? t.surfaceRaised : t.surface,
                      borderRadius: 12,
                      padding: 10,
                      textAlign: "left",
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>rev {entry.revision}</span>
                      {entry.is_active ? <span style={{ fontSize: 11, color: t.accent }}>current</span> : null}
                      {entry.is_accepted ? <span style={{ fontSize: 11, color: t.success }}>accepted</span> : null}
                      <span style={{ fontSize: 11, color: t.textDim }}>{entry.status}</span>
                      {entry.created_at ? (
                        <span style={{ fontSize: 11, color: t.textDim }}>{new Date(entry.created_at).toLocaleString()}</span>
                      ) : null}
                    </div>
                    <div style={{ fontSize: 12, color: t.textMuted }}>{entry.summary}</div>
                    {entry.changed_sections.length > 0 ? (
                      <div style={{ fontSize: 11, color: t.textDim }}>
                        Changed: {entry.changed_sections.join(", ")}
                      </div>
                    ) : null}
                  </button>
                );
              })}
            </div>
            {diffQuery.data ? (
              <div
                style={{
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 12,
                  background: t.surface,
                  padding: 10,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>
                  Diff rev {diffQuery.data.from_revision} → rev {diffQuery.data.to_revision}
                </div>
                {diffQuery.data.changed_sections.length > 0 ? (
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    Changed: {diffQuery.data.changed_sections.join(", ")}
                  </div>
                ) : null}
                <pre
                  style={{
                    margin: 0,
                    padding: 12,
                    borderRadius: 10,
                    background: t.surfaceRaised,
                    color: t.textMuted,
                    fontSize: 11,
                    whiteSpace: "pre-wrap",
                    overflowX: "auto",
                    maxHeight: 260,
                  }}
                >
                  {diffQuery.data.diff || "No textual diff."}
                </pre>
              </div>
            ) : null}
          </section>
        )}
      </div>
    </div>
  );
}
