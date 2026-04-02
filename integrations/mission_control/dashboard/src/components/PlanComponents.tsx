/**
 * Shared plan UI components: StepIcon, ProgressBar, StatusBadge.
 * Adapted from ui/src/components/mission-control/PlanComponents.tsx for web.
 */
import { CheckCircle2, Loader2, MinusCircle, AlertCircle, Circle } from "lucide-react";
import { STATUS_COLORS, STATUS_LABELS } from "../lib/planConstants";
import type { PlanStep } from "../lib/types";

export function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={14} color="#22c55e" />;
    case "in_progress":
      return <Loader2 size={14} color="#3b82f6" />;
    case "skipped":
      return <MinusCircle size={14} color="#9ca3af" />;
    case "failed":
      return <AlertCircle size={14} color="#ef4444" />;
    default:
      return <Circle size={14} color="#d1d5db" />;
  }
}

export function ProgressBar({ steps }: { steps: PlanStep[] }) {
  const total = steps.length;
  if (total === 0) return null;
  const done = steps.filter(
    (s) => s.status === "done" || s.status === "skipped" || s.status === "failed",
  ).length;
  const pct = Math.round((done / total) * 100);

  return (
    <div className="flex items-center gap-2 flex-shrink-0">
      <div className="w-20 h-1.5 bg-surface-3 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            backgroundColor: pct === 100 ? "#22c55e" : "#3b82f6",
          }}
        />
      </div>
      <span className="text-[10px] text-content-dim w-12">
        {done}/{total} ({pct}%)
      </span>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.draft;
  const label = STATUS_LABELS[status] || status.replace(/_/g, " ");
  return (
    <span
      className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase whitespace-nowrap"
      style={{
        backgroundColor: colors.bg,
        border: `1px solid ${colors.border}`,
        color: colors.text,
      }}
    >
      {label}
    </span>
  );
}
