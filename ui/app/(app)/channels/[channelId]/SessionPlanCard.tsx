import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  PauseCircle,
  PlayCircle,
  type LucideIcon,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { TERMINAL_FONT_STACK } from "@/src/components/chat/CodePreviewRenderer";
import type { SessionPlan, SessionPlanRevisionDiff, SessionPlanStep } from "./useSessionPlanMode";

type PlanCardChatMode = "default" | "terminal";

type Tone = "neutral" | "accent" | "warning" | "danger" | "success";

const MODE_META: Record<SessionPlan["mode"], { Icon: LucideIcon; label: string; tone: Tone }> = {
  chat: { Icon: Circle, label: "chat", tone: "neutral" },
  planning: { Icon: CircleDashed, label: "planning", tone: "warning" },
  executing: { Icon: PlayCircle, label: "executing", tone: "accent" },
  blocked: { Icon: PauseCircle, label: "blocked", tone: "danger" },
  done: { Icon: CheckCircle2, label: "done", tone: "success" },
};

const STEP_META: Record<SessionPlanStep["status"], { Icon: LucideIcon; tone: Tone; label: string }> = {
  pending: { Icon: Circle, tone: "neutral", label: "pending" },
  in_progress: { Icon: PlayCircle, tone: "accent", label: "in progress" },
  done: { Icon: CheckCircle2, tone: "success", label: "done" },
  blocked: { Icon: PauseCircle, tone: "danger", label: "blocked" },
};

function toneText(tone: Tone): string {
  switch (tone) {
    case "accent":
      return "text-accent";
    case "warning":
      return "text-warning-muted";
    case "danger":
      return "text-danger-muted";
    case "success":
      return "text-success";
    default:
      return "text-text-muted";
  }
}

function tonePill(tone: Tone): string {
  switch (tone) {
    case "accent":
      return "bg-accent/10 text-accent";
    case "warning":
      return "bg-warning/10 text-warning-muted";
    case "danger":
      return "bg-danger/10 text-danger-muted";
    case "success":
      return "bg-success/10 text-success";
    default:
      return "bg-surface-overlay text-text-muted";
  }
}

function actionClass(tone: Tone, terminal: boolean, disabled = false): string {
  const size = terminal ? "h-7 rounded-sm px-2 text-[11px]" : "h-8 rounded-md px-2.5 text-xs";
  const color = tone === "accent"
    ? "text-accent hover:bg-accent/[0.08]"
    : tone === "warning"
      ? "text-warning-muted hover:bg-warning/10"
      : tone === "danger"
        ? "text-danger-muted hover:bg-danger/10"
        : tone === "success"
          ? "text-success hover:bg-success/10"
          : "text-text-muted hover:bg-surface-overlay/60 hover:text-text";
  return [
    "inline-flex items-center gap-1.5 border-0 bg-transparent font-medium transition-colors duration-100",
    size,
    disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
    color,
  ].join(" ");
}

function Section({
  title,
  children,
  terminal,
  quiet = false,
}: {
  title: string;
  children: ReactNode;
  terminal: boolean;
  quiet?: boolean;
}) {
  return (
    <section className={terminal ? "flex flex-col gap-1.5" : "flex flex-col gap-2"}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        {title}
      </div>
      <div
        className={
          quiet
            ? "flex flex-col gap-2"
            : terminal
              ? "flex flex-col gap-1.5 rounded-sm bg-surface-overlay/20 px-2 py-1.5"
              : "flex flex-col gap-2 rounded-md bg-surface-overlay/30 px-3 py-2.5"
        }
      >
        {children}
      </div>
    </section>
  );
}

function DetailLine({
  label,
  value,
  terminal,
}: {
  label: string;
  value: ReactNode;
  terminal: boolean;
}) {
  return (
    <div className={terminal ? "flex gap-2 text-[11px]" : "flex gap-2 text-xs"}>
      <span className="shrink-0 text-text-dim">{label}</span>
      <span className="min-w-0 text-text-muted">{value}</span>
    </div>
  );
}

function ListSection({
  title,
  items,
  terminal,
  emptyLabel,
}: {
  title: string;
  items?: string[];
  terminal: boolean;
  emptyLabel?: string;
}) {
  const visibleItems = (items ?? []).filter((item) => item.trim().length > 0);
  if (!visibleItems.length && !emptyLabel) return null;
  return (
    <Section title={title} terminal={terminal} quiet>
      <div className="flex flex-col gap-1.5">
        {visibleItems.length ? visibleItems.map((item) => (
          <div key={item} className="flex min-w-0 items-start gap-2">
            <span className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-surface-border" />
            <span className={terminal ? "text-[11px] text-text-muted" : "text-xs text-text-muted"}>{item}</span>
          </div>
        )) : (
          <div className={terminal ? "text-[11px] text-text-dim" : "text-xs text-text-dim"}>{emptyLabel}</div>
        )}
      </div>
    </Section>
  );
}

export function SessionPlanCard({
  plan,
  sessionId,
  busy,
  showPath = false,
  currentRevision,
  acceptedRevision,
  staleMessage,
  chatMode = "default",
  onApprove,
  onExit,
  onStepStatus,
  onReplan,
  onReviewLatestOutcome,
}: {
  plan: SessionPlan;
  sessionId?: string;
  busy?: boolean;
  showPath?: boolean;
  currentRevision?: number | null;
  acceptedRevision?: number | null;
  staleMessage?: string | null;
  chatMode?: PlanCardChatMode;
  onApprove: () => void;
  onExit: () => void;
  onStepStatus: (stepId: string, status: "pending" | "in_progress" | "done" | "blocked") => void;
  onReplan?: () => void;
  onReviewLatestOutcome?: (correlationId?: string) => void;
}) {
  const terminal = chatMode === "terminal";
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
  const latestSemanticReview = adherence?.latest_semantic_review ?? runtime?.latest_semantic_review;
  const latestOutcomeNeedsReview = !!latestOutcome?.correlation_id
    && latestSemanticReview?.correlation_id !== latestOutcome.correlation_id;
  const modeMeta = MODE_META[plan.mode] ?? MODE_META.chat;
  const ModeIcon = modeMeta.Icon;
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

  const runtimeBits = [
    runtime?.next_action ? `next ${runtime.next_action}` : null,
    runtime?.current_step_id ? `current ${runtime.current_step_id}` : null,
    runtime?.next_step_id && runtime.next_step_id !== runtime.current_step_id ? `up next ${runtime.next_step_id}` : null,
    runtime?.accepted_revision ? `accepted rev ${runtime.accepted_revision}` : null,
    runtime?.adherence_status ? `adherence ${runtime.adherence_status}` : null,
    pendingOutcome?.reason ? `pending ${pendingOutcome.reason}` : null,
    runtime?.replan?.reason ? `replan ${runtime.replan.reason}` : null,
  ].filter((bit): bit is string => !!bit);

  return (
    <div
      data-plan-card-mode={chatMode}
      className={
        terminal
          ? "flex max-w-full flex-col gap-2 text-[12px] leading-relaxed text-text-muted"
          : "flex max-w-full flex-col gap-3 rounded-md bg-surface-raised/60 p-3 text-sm text-text ring-1 ring-surface-border/60"
      }
      style={terminal ? { fontFamily: TERMINAL_FONT_STACK } : undefined}
    >
      <div className={terminal ? "flex flex-col gap-1.5" : "flex flex-col gap-2"}>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className={terminal ? "min-w-0 text-[13px] font-semibold text-text" : "min-w-0 text-[15px] font-semibold text-text"}>
            {plan.title}
          </span>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${tonePill(modeMeta.tone)}`}>
            <ModeIcon size={12} />
            {modeMeta.label}
          </span>
          <span className="text-[11px] text-text-dim">
            rev {plan.revision}
            {acceptedRevision && acceptedRevision === plan.revision ? " · accepted" : ""}
            {historical && currentRevision ? ` · current rev ${currentRevision}` : ""}
          </span>
        </div>
        <div className={terminal ? "text-[12px] text-text-muted" : "text-sm text-text-muted"}>
          {plan.summary}
        </div>
        {showPath && plan.path ? (
          <div className="text-[11px] text-text-dim" style={{ fontFamily: TERMINAL_FONT_STACK }}>{plan.path}</div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-1">
        {plan.mode === "planning" && !historical && (
          <button
            type="button"
            onClick={onApprove}
            disabled={busy || approvalBlocked}
            className={actionClass("accent", terminal, !!busy || approvalBlocked)}
            title={approvalBlocked ? "Resolve plan validation issues before approval." : undefined}
          >
            Approve & Execute
          </button>
        )}
        {(plan.mode === "executing" || plan.mode === "blocked") && !historical && onReplan ? (
          <button
            type="button"
            onClick={onReplan}
            disabled={busy}
            className={actionClass("warning", terminal, !!busy)}
          >
            Request Replan
          </button>
        ) : null}
        {(plan.mode === "executing" || plan.mode === "blocked" || plan.mode === "done") && !historical && latestOutcome && onReviewLatestOutcome ? (
          <button
            type="button"
            onClick={() => onReviewLatestOutcome(latestOutcome.correlation_id ?? undefined)}
            disabled={busy}
            className={actionClass(latestOutcomeNeedsReview ? "accent" : "neutral", terminal, !!busy)}
          >
            Review Last Outcome
          </button>
        ) : null}
        <button
          type="button"
          onClick={onExit}
          disabled={busy}
          className={actionClass("neutral", terminal, !!busy)}
        >
          Exit Plan Mode
        </button>
      </div>

      {(historical || staleMessage) ? (
        <div className={terminal ? "rounded-sm bg-warning/10 px-2 py-1.5 text-[11px] text-warning-muted" : "rounded-md bg-warning/10 px-3 py-2 text-xs text-warning-muted"}>
          {staleMessage ?? `This card is showing historical revision ${plan.revision}. Current planning state is on revision ${currentRevision}.`}
        </div>
      ) : null}

      {(runtime || validationIssues.length > 0) ? (
        <Section title="Runtime" terminal={terminal}>
          {runtimeBits.length > 0 ? (
            <div className="flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-text-dim">
              {runtimeBits.map((bit) => <span key={bit}>{bit}</span>)}
            </div>
          ) : null}
          {pendingOutcome ? (
            <div className="text-xs text-warning-muted">
              Pending outcome: record progress, verification, blocker, replan, or no-progress before more execution.
            </div>
          ) : null}
          {latestOutcome ? (
            <DetailLine
              label="latest"
              terminal={terminal}
              value={`${latestOutcome.outcome ?? "recorded"}${latestOutcome.summary ? `: ${latestOutcome.summary}` : ""}`}
            />
          ) : null}
          {latestOutcomeNeedsReview ? (
            <div className="text-xs text-warning-muted">
              Latest outcome has not been semantically reviewed yet.
            </div>
          ) : null}
          {latestSemanticReview ? (
            <DetailLine
              label="review"
              terminal={terminal}
              value={(
                <span className={toneText(latestSemanticReview.semantic_status === "ok" ? "success" : latestSemanticReview.semantic_status === "needs_replan" ? "warning" : "neutral")}>
                  {latestSemanticReview.verdict ?? "recorded"}
                  {latestSemanticReview.reason ? `: ${latestSemanticReview.reason}` : ""}
                  {typeof latestSemanticReview.confidence === "number" ? ` (${Math.round(latestSemanticReview.confidence * 100)}%)` : ""}
                </span>
              )}
            />
          ) : null}
          {adherence?.latest_evidence ? (
            <DetailLine
              label="evidence"
              terminal={terminal}
              value={adherence.latest_evidence.summary ?? adherence.latest_evidence.tool_name ?? "recorded"}
            />
          ) : null}
          {validationIssues.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              <div className={`flex items-center gap-1.5 text-xs font-medium ${approvalBlocked ? "text-warning-muted" : "text-text-muted"}`}>
                <AlertTriangle size={13} />
                {approvalBlocked ? `${blockingIssues.length} issue${blockingIssues.length === 1 ? "" : "s"} before approval` : `${warningIssues.length} warning${warningIssues.length === 1 ? "" : "s"}`}
              </div>
              {validationIssues.slice(0, 4).map((issue) => (
                <div key={`${issue.code}-${issue.field}-${issue.message}`} className={issue.severity === "error" ? "text-xs text-warning-muted" : "text-xs text-text-dim"}>
                  {issue.severity === "error" ? "Required" : "Warning"}: {issue.message}
                </div>
              ))}
            </div>
          ) : null}
        </Section>
      ) : null}

      {planningStateItems.length > 0 ? (
        <Section title="Planning Notes" terminal={terminal}>
          {planningStateItems.slice(0, 4).map((section) => (
            <div key={section.label} className="flex flex-col gap-1">
              <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim/70">
                {section.label}
              </div>
              {section.items.slice(-3).map((item, idx) => (
                <div key={`${section.label}-${idx}-${item.text}`} className={terminal ? "text-[11px] text-text-muted" : "text-xs text-text-muted"}>
                  {item.text}
                </div>
              ))}
            </div>
          ))}
        </Section>
      ) : null}

      <Section title="Scope" terminal={terminal} quiet>
        <div className={terminal ? "text-[12px] text-text-muted" : "text-sm text-text-muted"}>{plan.scope}</div>
      </Section>

      <ListSection title="Key Changes" items={plan.key_changes} terminal={terminal} />
      <ListSection title="Interfaces" items={plan.interfaces} terminal={terminal} />
      <ListSection title="Assumptions & Defaults" items={(plan.assumptions_and_defaults?.length ? plan.assumptions_and_defaults : plan.assumptions)} terminal={terminal} />

      <Section title="Checklist" terminal={terminal} quiet>
        <div className="flex flex-col gap-1.5">
          {plan.steps.map((step) => {
            const stepMeta = STEP_META[step.status] ?? STEP_META.pending;
            const StepIcon = stepMeta.Icon;
            return (
              <div
                key={step.id}
                className={terminal ? "rounded-sm bg-surface-overlay/20 px-2 py-1.5" : "rounded-md bg-surface/70 px-3 py-2"}
              >
                <div className="flex items-start gap-2">
                  <StepIcon size={14} className={`mt-0.5 shrink-0 ${toneText(stepMeta.tone)}`} />
                  <div className="min-w-0 flex-1">
                    <div className={terminal ? "text-[12px] text-text" : "text-sm text-text"}>{step.label}</div>
                    <div className="text-[11px] text-text-dim" style={{ fontFamily: TERMINAL_FONT_STACK }}>
                      {step.id} · {stepMeta.label}
                    </div>
                    {step.note ? <div className="mt-1 text-xs text-text-muted">{step.note}</div> : null}
                  </div>
                </div>
                {plan.mode !== "planning" && !historical ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {step.status !== "in_progress" && (
                      <button type="button" onClick={() => onStepStatus(step.id, "in_progress")} disabled={busy} className={actionClass("neutral", terminal, !!busy)}>
                        In Progress
                      </button>
                    )}
                    {step.status !== "done" && (
                      <button type="button" onClick={() => onStepStatus(step.id, "done")} disabled={busy} className={actionClass("success", terminal, !!busy)}>
                        Done
                      </button>
                    )}
                    {step.status !== "blocked" && (
                      <button type="button" onClick={() => onStepStatus(step.id, "blocked")} disabled={busy} className={actionClass("danger", terminal, !!busy)}>
                        Blocked
                      </button>
                    )}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </Section>

      {plan.open_questions.length > 0 ? (
        <Section title="Open Questions" terminal={terminal} quiet>
          <div className="flex flex-col gap-1">
            {plan.open_questions.map((item) => (
              <div key={item} className={terminal ? "text-[11px] text-text-muted" : "text-xs text-text-muted"}>{item}</div>
            ))}
          </div>
        </Section>
      ) : null}

      <ListSection title="Test Plan" items={plan.test_plan} terminal={terminal} />
      <ListSection title="Acceptance Criteria" items={plan.acceptance_criteria} terminal={terminal} />
      <ListSection title="Risks" items={plan.risks} terminal={terminal} />

      {revisionEntries.length > 1 ? (
        <Section title="Revision History" terminal={terminal} quiet>
          <div className="flex flex-col gap-1.5">
            {revisionEntries.map((entry) => {
              const selected = effectiveCompareRevision === entry.revision;
              return (
                <button
                  key={`${entry.revision}-${entry.source}`}
                  type="button"
                  onClick={() => setCompareRevision(selected ? null : entry.revision)}
                  className={[
                    terminal ? "rounded-sm px-2 py-1.5 text-left text-[11px]" : "rounded-md px-3 py-2 text-left text-xs",
                    selected ? "bg-accent/[0.08]" : "bg-surface-overlay/25 hover:bg-surface-overlay/50",
                    "transition-colors duration-100",
                  ].join(" ")}
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-semibold text-text">rev {entry.revision}</span>
                    {entry.is_active ? <span className="text-accent">current</span> : null}
                    {entry.is_accepted ? <span className="text-success">accepted</span> : null}
                    <span className="text-text-dim">{entry.status}</span>
                    {entry.created_at ? <span className="text-text-dim">{new Date(entry.created_at).toLocaleString()}</span> : null}
                  </div>
                  <div className="mt-1 text-text-muted">{entry.summary}</div>
                  {entry.changed_sections.length > 0 ? (
                    <div className="mt-1 text-text-dim">
                      Changed: {entry.changed_sections.join(", ")}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>
          {diffQuery.data ? (
            <div className={terminal ? "rounded-sm bg-surface-overlay/20 px-2 py-1.5" : "rounded-md bg-surface-overlay/30 px-3 py-2"}>
              <div className="text-xs font-semibold text-text">
                Diff rev {diffQuery.data.from_revision} to rev {diffQuery.data.to_revision}
              </div>
              {diffQuery.data.changed_sections.length > 0 ? (
                <div className="mt-1 text-[11px] text-text-dim">
                  Changed: {diffQuery.data.changed_sections.join(", ")}
                </div>
              ) : null}
              <pre
                className={terminal ? "mt-2 max-h-64 overflow-x-auto whitespace-pre-wrap rounded-sm bg-surface-raised/60 p-2 text-[11px] text-text-muted" : "mt-2 max-h-64 overflow-x-auto whitespace-pre-wrap rounded-md bg-surface-raised/70 p-3 text-[11px] text-text-muted"}
                style={{ fontFamily: TERMINAL_FONT_STACK }}
              >
                {diffQuery.data.diff || "No textual diff."}
              </pre>
            </div>
          ) : null}
        </Section>
      ) : null}
    </div>
  );
}
