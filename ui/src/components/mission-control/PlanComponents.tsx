import { View, Text } from "react-native";
import {
  Circle,
  CheckCircle2,
  Loader2,
  MinusCircle,
  AlertCircle,
  Clock,
  FileEdit,
  Play,
  ShieldAlert,
  CheckCheck,
  XCircle,
} from "lucide-react";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import type { MCPlanStep } from "@/src/api/hooks/useMissionControl";
import { getStatusStyle, getStepStatusStyle, STATUS_LABELS, STEP_STATUS_LABELS } from "./planConstants";

// ---------------------------------------------------------------------------
// Step status icon — themed
// ---------------------------------------------------------------------------

export function StepIcon({ status, size = 15 }: { status: string; size?: number }) {
  const t = useThemeTokens();
  const s = getStepStatusStyle(status, t);
  switch (status) {
    case "done":
      return <CheckCircle2 size={size} color={s.text} />;
    case "in_progress":
      return <Loader2 size={size} color={s.text} />;
    case "skipped":
      return <MinusCircle size={size} color={s.text} />;
    case "failed":
      return <AlertCircle size={size} color={s.text} />;
    default:
      return <Circle size={size} color={s.text} />;
  }
}

// ---------------------------------------------------------------------------
// Plan status icon
// ---------------------------------------------------------------------------

export function PlanStatusIcon({ status, size = 13 }: { status: string; size?: number }) {
  const t = useThemeTokens();
  const s = getStatusStyle(status, t);
  switch (status) {
    case "draft":
      return <FileEdit size={size} color={s.text} />;
    case "approved":
      return <Play size={size} color={s.text} />;
    case "executing":
      return <Loader2 size={size} color={s.text} />;
    case "awaiting_approval":
      return <ShieldAlert size={size} color={s.text} />;
    case "complete":
      return <CheckCheck size={size} color={s.text} />;
    case "abandoned":
      return <XCircle size={size} color={s.text} />;
    default:
      return <Clock size={size} color={s.text} />;
  }
}

// ---------------------------------------------------------------------------
// Status badge — themed, matches workflow StatusBadge pattern
// ---------------------------------------------------------------------------

export function StatusBadge({ status }: { status: string }) {
  const t = useThemeTokens();
  const s = getStatusStyle(status, t);
  const label = STATUS_LABELS[status] || status;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: s.bg,
        border: `1px solid ${s.border}`,
        color: s.text,
        whiteSpace: "nowrap",
      }}
    >
      <PlanStatusIcon status={status} size={12} />
      {label}
    </span>
  );
}

// Step status badge (smaller, inline)
export function StepStatusBadge({ status }: { status: string }) {
  const t = useThemeTokens();
  const s = getStepStatusStyle(status, t);
  const label = STEP_STATUS_LABELS[status] || status;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        background: s.bg,
        border: `1px solid ${s.border}`,
        color: s.text,
      }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Progress bar — bigger, segmented, with status breakdown
// ---------------------------------------------------------------------------

export function ProgressBar({ steps, compact }: { steps: MCPlanStep[]; compact?: boolean }) {
  const t = useThemeTokens();
  const total = steps.length;
  if (total === 0) return null;

  const done = steps.filter((s) => s.status === "done").length;
  const failed = steps.filter((s) => s.status === "failed").length;
  const skipped = steps.filter((s) => s.status === "skipped").length;
  const inProgress = steps.filter((s) => s.status === "in_progress").length;
  const completed = done + failed + skipped;
  const pct = Math.round((completed / total) * 100);

  const barHeight = compact ? 4 : 6;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: compact ? 60 : 100 }}>
      {/* Segmented bar */}
      <div
        style={{
          flex: 1,
          height: barHeight,
          borderRadius: barHeight / 2,
          backgroundColor: t.surfaceBorder,
          overflow: "hidden",
          display: "flex",
          flexDirection: "row",
        }}
      >
        {done > 0 && (
          <div style={{ width: `${(done / total) * 100}%`, height: barHeight, backgroundColor: t.success }} />
        )}
        {inProgress > 0 && (
          <div style={{ width: `${(inProgress / total) * 100}%`, height: barHeight, backgroundColor: t.accent }} />
        )}
        {failed > 0 && (
          <div style={{ width: `${(failed / total) * 100}%`, height: barHeight, backgroundColor: t.danger }} />
        )}
        {skipped > 0 && (
          <div style={{ width: `${(skipped / total) * 100}%`, height: barHeight, backgroundColor: t.textDim }} />
        )}
      </div>
      {/* Count */}
      <span style={{ fontSize: 11, color: t.textMuted, fontWeight: 500, whiteSpace: "nowrap" }}>
        {completed}/{total}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Metadata item (like workflow MetaItem)
// ---------------------------------------------------------------------------

export function MetaItem({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  const t = useThemeTokens();
  return (
    <div>
      <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 12, color: t.text, fontFamily: mono ? "monospace" : undefined, marginTop: 1 }}>
        {value}
      </div>
    </div>
  );
}
