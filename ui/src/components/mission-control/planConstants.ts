import type { ThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Status styling — theme-aware, matches workflow RunHelpers pattern
// ---------------------------------------------------------------------------

export function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "draft":
      return { bg: t.warningSubtle, border: t.warningBorder, text: t.warning };
    case "approved":
      return { bg: t.accentSubtle, border: t.accentBorder, text: t.accent };
    case "executing":
      return { bg: t.successSubtle, border: t.successBorder, text: t.success };
    case "awaiting_approval":
      return { bg: "rgba(168,85,247,0.08)", border: "rgba(168,85,247,0.2)", text: "#a855f7" };
    case "complete":
      return { bg: t.codeBg, border: t.surfaceBorder, text: t.textDim };
    case "abandoned":
      return { bg: t.dangerSubtle, border: t.dangerBorder, text: t.danger };
    default:
      return { bg: t.codeBg, border: t.surfaceBorder, text: t.textDim };
  }
}

// Kept for backward compat — prefer getStatusStyle(status, t) for theme awareness
export const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  draft: { bg: "rgba(245,158,11,0.1)", border: "rgba(245,158,11,0.4)", text: "#f59e0b" },
  approved: { bg: "rgba(59,130,246,0.1)", border: "rgba(59,130,246,0.4)", text: "#3b82f6" },
  executing: { bg: "rgba(34,197,94,0.1)", border: "rgba(34,197,94,0.4)", text: "#22c55e" },
  awaiting_approval: { bg: "rgba(168,85,247,0.1)", border: "rgba(168,85,247,0.4)", text: "#a855f7" },
  complete: { bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.2)", text: "#6b7280" },
  abandoned: { bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.2)", text: "#ef4444" },
};

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  approved: "Approved",
  executing: "Executing",
  awaiting_approval: "Awaiting Approval",
  complete: "Complete",
  abandoned: "Abandoned",
};

export const STATUS_FILTERS = [
  "all",
  "draft",
  "executing",
  "awaiting_approval",
  "approved",
  "complete",
  "abandoned",
] as const;

// Step status helpers
export const STEP_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  in_progress: "Running",
  done: "Done",
  skipped: "Skipped",
  failed: "Failed",
};

export function getStepStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "done":
      return { bg: t.successSubtle, border: t.successBorder, text: t.success };
    case "in_progress":
      return { bg: t.accentSubtle, border: t.accentBorder, text: t.accent };
    case "failed":
      return { bg: t.dangerSubtle, border: t.dangerBorder, text: t.danger };
    case "skipped":
      return { bg: t.codeBg, border: t.surfaceBorder, text: t.textDim };
    default: // pending
      return { bg: t.codeBg, border: t.surfaceBorder, text: t.textDim };
  }
}
