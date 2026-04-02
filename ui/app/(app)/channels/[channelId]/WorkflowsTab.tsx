import { useState } from "react";
import { ActivityIndicator, Text, Pressable } from "react-native";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { EmptyState } from "@/src/components/shared/FormControls";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import { Link } from "expo-router";
import {
  Loader2, CheckCircle2, XCircle, ShieldCheck, Clock, X, Minus,
  CircleDot, ChevronRight, ExternalLink,
} from "lucide-react";
import type { WorkflowRun, WorkflowStepState } from "@/src/types/api";

type StatusFilter = "active" | "all";

function getStatusStyle(status: string, t: ThemeTokens) {
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

function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
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

function fmtTime(iso: string): string {
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

export function WorkflowsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const [filter, setFilter] = useState<StatusFilter>("active");

  const { data: runs, isLoading } = useQuery({
    queryKey: ["channel-workflow-runs", channelId, filter],
    queryFn: () =>
      apiFetch<WorkflowRun[]>(
        `/api/v1/admin/channels/${channelId}/workflow-runs${filter === "all" ? "?all=true" : ""}`
      ),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && data.some((r) => r.status === "running" || r.status === "awaiting_approval")) return 3000;
      return false;
    },
  });

  return (
    <>
      {/* Filter pills */}
      <div style={{
        display: "flex", alignItems: "center", gap: 4, marginBottom: 12,
      }}>
        {(["active", "all"] as const).map((key) => {
          const active = filter === key;
          return (
            <button
              key={key}
              onClick={() => setFilter(key)}
              style={{
                padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                border: `1px solid ${active ? t.accent : t.surfaceBorder}`,
                background: active ? t.accentMuted : t.surfaceRaised,
                color: active ? t.accent : t.textMuted,
                cursor: "pointer", textTransform: "capitalize",
              }}
            >
              {key === "active" ? "Active" : "All History"}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <ActivityIndicator color={t.accent} />
      ) : !runs || runs.length === 0 ? (
        <EmptyState message={filter === "active" ? "No active workflow runs." : "No workflow runs for this channel."} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {runs.map((run) => (
            <RunCard key={run.id} run={run} t={t} />
          ))}
        </div>
      )}
    </>
  );
}

function RunCard({ run, t }: { run: WorkflowRun; t: ThemeTokens }) {
  const done = run.step_states.filter((s) =>
    s.status === "done" || s.status === "skipped" || s.status === "failed"
  ).length;
  const total = run.step_states.length;

  return (
    <div style={{
      backgroundColor: t.surfaceRaised, borderRadius: 8,
      border: `1px solid ${t.surfaceBorder}`, padding: 12,
    }}>
      {/* Top row: workflow id + status + step count */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Link href={`/admin/workflows/${run.workflow_id}` as any}>
            <Text style={{ fontSize: 13, fontWeight: 600, color: t.accent }}>{run.workflow_id}</Text>
          </Link>
          <StatusBadge status={run.status} t={t} />
        </div>
        <span style={{ fontSize: 11, color: t.textDim }}>
          {done}/{total} steps
        </span>
      </div>

      {/* Meta row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
          {run.id.slice(0, 8)}
        </span>
        {run.triggered_by && (
          <span style={{ fontSize: 11, color: t.textDim }}>via {run.triggered_by}</span>
        )}
        <span style={{ fontSize: 11, color: t.textDim }}>{fmtTime(run.created_at)}</span>
        {run.completed_at && (
          <span style={{ fontSize: 11, color: t.textDim }}>completed {fmtTime(run.completed_at)}</span>
        )}
      </div>

      {/* Mini step bar */}
      <div style={{ display: "flex", gap: 2, marginTop: 8, height: 4, borderRadius: 2, overflow: "hidden" }}>
        {run.step_states.map((s, i) => {
          const color =
            s.status === "done" ? t.success :
            s.status === "running" ? t.accent :
            s.status === "failed" ? t.danger :
            s.status === "skipped" ? t.surfaceBorder :
            t.surfaceOverlay;
          return <div key={i} style={{ flex: 1, background: color, borderRadius: 1 }} />;
        })}
      </div>

      {/* Error */}
      {run.error && (
        <div style={{
          marginTop: 8, padding: 6, borderRadius: 6,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          fontSize: 11, color: t.danger, fontFamily: "monospace",
          whiteSpace: "pre-wrap", maxHeight: 60, overflow: "auto",
        }}>
          {run.error}
        </div>
      )}

      {/* Links row */}
      <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
        <Link href={`/admin/workflows/${run.workflow_id}` as any}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, color: t.accent }}>
            <ExternalLink size={10} />
            Workflow
          </span>
        </Link>
        {run.step_states.some((s) => s.task_id) && (
          <Link href={`/admin/tasks/${run.step_states.find((s) => s.task_id)?.task_id}` as any}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, color: t.accent }}>
              <ExternalLink size={10} />
              Task
            </span>
          </Link>
        )}
      </div>
    </div>
  );
}
