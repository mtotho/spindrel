import { AlertTriangle, Clock, History, Play, Radio } from "lucide-react";
import type { WorkspaceMapObjectState } from "../../api/types/workspaceMapState";

export function mapStateLabel(state?: WorkspaceMapObjectState | null): string | null {
  if (!state) return null;
  if (state.status === "error") return state.primary_signal || "Error";
  if (state.status === "warning") return state.primary_signal || "Warning";
  if (state.status === "running") return state.primary_signal || "Running";
  if (state.status === "scheduled") return state.next?.title || state.primary_signal || "Scheduled";
  if (state.status === "recent") return state.primary_signal || "Recent";
  return null;
}

export function mapStateMeta(state?: WorkspaceMapObjectState | null): string | null {
  if (!state) return null;
  const parts: string[] = [];
  if (state.counts.upcoming > 0) parts.push(`${state.counts.upcoming} next`);
  if (state.counts.recent > 0) parts.push(`${state.counts.recent} recent`);
  if (state.counts.warnings > 0) parts.push(`${state.counts.warnings} warning${state.counts.warnings === 1 ? "" : "s"}`);
  return parts.join(" · ") || null;
}

export function mapStateTone(state?: WorkspaceMapObjectState | null): "danger" | "warning" | "accent" | "muted" {
  if (!state) return "muted";
  if (state.status === "error" || state.severity === "critical" || state.severity === "error") return "danger";
  if (state.status === "warning" || state.severity === "warning") return "warning";
  if (state.status === "running" || state.status === "scheduled" || state.status === "active") return "accent";
  return "muted";
}

export function statusRingClass(state?: WorkspaceMapObjectState | null): string {
  const tone = mapStateTone(state);
  if (tone === "danger") return "ring-2 ring-danger/80";
  if (tone === "warning") return "ring-2 ring-warning/70";
  if (tone === "accent") return "ring-2 ring-accent/45";
  return "";
}

export function ObjectStatusPill({
  state,
  compact = false,
  iconOnly = false,
}: {
  state?: WorkspaceMapObjectState | null;
  compact?: boolean;
  iconOnly?: boolean;
}) {
  const label = mapStateLabel(state);
  if (!state || !label) return null;
  const tone = mapStateTone(state);
  const Icon =
    tone === "danger" || tone === "warning"
      ? AlertTriangle
      : state.status === "running"
        ? Play
        : state.status === "scheduled"
          ? Clock
          : state.status === "recent"
            ? History
            : Radio;
  const cls =
    tone === "danger"
      ? "bg-danger/10 text-danger"
      : tone === "warning"
        ? "bg-warning/10 text-warning"
        : tone === "accent"
          ? "bg-accent/10 text-accent"
          : "bg-surface-overlay text-text-muted";
  return (
    <span
      className={`inline-flex min-w-0 max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${cls}`}
      title={label}
    >
      <Icon size={compact ? 9 : 10} className="shrink-0" />
      {iconOnly ? <span className="sr-only">{label}</span> : <span className="truncate">{label}</span>}
    </span>
  );
}
