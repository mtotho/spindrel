export const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  draft: { bg: "rgba(245,158,11,0.1)", border: "rgba(245,158,11,0.4)", text: "#f59e0b" },
  approved: { bg: "rgba(59,130,246,0.1)", border: "rgba(59,130,246,0.4)", text: "#3b82f6" },
  executing: { bg: "rgba(34,197,94,0.1)", border: "rgba(34,197,94,0.4)", text: "#22c55e" },
  awaiting_approval: { bg: "rgba(168,85,247,0.1)", border: "rgba(168,85,247,0.4)", text: "#a855f7" },
  complete: { bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.2)", text: "#6b7280" },
  abandoned: { bg: "rgba(239,68,68,0.08)", border: "rgba(239,68,68,0.2)", text: "#ef4444" },
};

export const STATUS_LABELS: Record<string, string> = {
  awaiting_approval: "Awaiting Approval",
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
