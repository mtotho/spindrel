import { useState, useEffect } from "react";
import { Pressable } from "react-native";
import { type ThemeTokens } from "@/src/theme/tokens";
import {
  Clock,
  CheckCircle2, XCircle, Loader2, ShieldCheck, CircleDot, Minus,
  X,
} from "lucide-react";
import type { WorkflowStepState } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status styling
// ---------------------------------------------------------------------------

export function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { bg: t.accentSubtle, border: t.accentBorder, text: t.accent, icon: Loader2 };
    case "complete":
    case "done":
      return { bg: t.successSubtle, border: t.successBorder, text: t.success, icon: CheckCircle2 };
    case "failed":
      return { bg: t.dangerSubtle, border: t.dangerBorder, text: t.danger, icon: XCircle };
    case "cancelled":
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: X };
    case "awaiting_approval":
      return { bg: t.warningSubtle, border: t.warningBorder, text: t.warning, icon: ShieldCheck };
    case "skipped":
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: Minus };
    case "pending":
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: Clock };
    default:
      return { bg: t.surfaceRaised, border: t.surfaceBorder, text: t.textDim, icon: CircleDot };
  }
}

export function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
  const s = getStatusStyle(status, t);
  const Icon = s.icon;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: s.bg, border: `1px solid ${s.border}`, color: s.text,
    }}>
      <Icon size={12} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Condition -> human-readable explanation
// ---------------------------------------------------------------------------

export function describeCondition(when: any): string {
  if (!when) return "";
  if (when.step && when.status) return `Requires step "${when.step}" to be ${when.status}`;
  if (when.step && when.output_contains) return `Requires "${when.step}" output to contain "${when.output_contains}"`;
  if (when.step && when.output_not_contains) return `Requires "${when.step}" output to NOT contain "${when.output_not_contains}"`;
  if (when.param) return `Requires param "${when.param}" ${when.equals != null ? `= "${when.equals}"` : when.not_equals != null ? `!= "${when.not_equals}"` : "to be set"}`;
  if (when.all) return (when.all as any[]).map(describeCondition).join(" AND ");
  if (when.any) return (when.any as any[]).map(describeCondition).join(" OR ");
  if (when.not) return `NOT (${describeCondition(when.not)})`;
  return JSON.stringify(when);
}

// ---------------------------------------------------------------------------
// Elapsed time for running steps
// ---------------------------------------------------------------------------

export function useElapsed(startedAt?: string | null, isRunning?: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!isRunning || !startedAt) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [isRunning, startedAt]);

  if (!startedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = isRunning ? now : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 60000) return "just now";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function MetaItem({ label, value, t, mono }: { label: string; value: string; t: ThemeTokens; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 12, color: t.text, fontFamily: mono ? "monospace" : undefined, marginTop: 1 }}>{value}</div>
    </div>
  );
}

export function formatStepDuration(startedAt?: string | null, completedAt?: string | null): string | null {
  if (!startedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

// ---------------------------------------------------------------------------
// Step nav item (left sidebar)
// ---------------------------------------------------------------------------

const STATUS_DOT_COLORS: Record<string, (t: ThemeTokens) => string> = {
  done: (t) => t.success,
  complete: (t) => t.success,
  running: (t) => t.accent,
  failed: (t) => t.danger,
  awaiting_approval: (t) => t.warning,
  skipped: (t) => t.textDim,
  pending: (t) => t.inputBorder,
};

function dotColor(status: string, t: ThemeTokens): string {
  return (STATUS_DOT_COLORS[status] || STATUS_DOT_COLORS.pending)(t);
}

export function StepNavItem({
  stepId, state, isActive, onPress, t,
}: {
  stepId: string;
  state: WorkflowStepState;
  isActive: boolean;
  onPress: () => void;
  t: ThemeTokens;
}) {
  const isRunning = state.status === "running";
  const duration = formatStepDuration(state.started_at, state.completed_at);
  const color = dotColor(state.status, t);

  return (
    <Pressable
      onPress={onPress}
      style={{
        flexDirection: "row", alignItems: "center", gap: 8,
        paddingVertical: 6, paddingHorizontal: 10,
        borderLeftWidth: 2,
        borderLeftColor: isActive ? t.accent : color + "40",
        backgroundColor: isActive ? t.accentSubtle : "transparent",
      }}
    >
      {/* Status dot */}
      <div style={{
        width: 8, height: 8, borderRadius: 4, flexShrink: 0,
        background: color,
        animation: isRunning ? "pulse 1.5s ease-in-out infinite" : undefined,
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 12, color: isActive ? t.text : t.textDim,
          fontWeight: isActive ? 600 : 400,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {stepId}
        </div>
        {duration && (
          <div style={{ fontSize: 10, color: t.textMuted, marginTop: 1 }}>
            {duration}
          </div>
        )}
      </div>
    </Pressable>
  );
}

