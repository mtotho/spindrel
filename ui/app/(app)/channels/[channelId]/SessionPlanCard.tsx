import React from "react";
import { CheckCircle2, Circle, CircleDashed, PauseCircle, PlayCircle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { SessionPlan } from "./useSessionPlanMode";

export function SessionPlanCard({
  plan,
  busy,
  showPath = false,
  onApprove,
  onExit,
  onStepStatus,
}: {
  plan: SessionPlan;
  busy?: boolean;
  showPath?: boolean;
  onApprove: () => void;
  onExit: () => void;
  onStepStatus: (stepId: string, status: "pending" | "in_progress" | "done" | "blocked") => void;
}) {
  const t = useThemeTokens();

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
            <span style={{ fontSize: 11, color: t.textDim }}>rev {plan.revision}</span>
          </div>
          <div style={{ fontSize: 13, color: t.textMuted }}>{plan.summary}</div>
          {showPath && plan.path ? (
            <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>{plan.path}</div>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {plan.mode === "planning" && (
            <button
              type="button"
              onClick={onApprove}
              disabled={busy}
              className="inline-flex h-9 items-center gap-2 rounded-full border px-3 text-[12px] font-medium transition-colors"
              style={{ borderColor: t.accent, color: t.text, background: t.surface }}
            >
              Approve & Execute
            </button>
          )}
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
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {step.status !== "in_progress" && plan.mode !== "planning" && (
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
      </div>
    </div>
  );
}
