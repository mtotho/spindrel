import { useEffect, useRef, useState } from "react";
import { View, Text, Pressable } from "react-native";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { useChannelWorkflowRuns, useCancelWorkflowRun } from "@/src/api/hooks/useWorkflows";
import { Link } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  Loader2, CheckCircle2, XCircle, ShieldCheck, ExternalLink, X,
} from "lucide-react";
import type { WorkflowRun } from "@/src/types/api";

const TERMINAL_STATUSES = new Set(["complete", "failed", "cancelled"]);

export function ActiveWorkflowStrip({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const qc = useQueryClient();
  const { data: runs } = useChannelWorkflowRuns(channelId);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // Track runs that just completed so we can auto-dismiss after 5s
  const prevRunsRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    if (!runs) return;
    const prev = prevRunsRef.current;
    for (const run of runs) {
      const wasActive = prev.get(run.id);
      if (wasActive && (wasActive === "running" || wasActive === "awaiting_approval") &&
          TERMINAL_STATUSES.has(run.status)) {
        // Run just finished — auto-dismiss after 5s
        const id = run.id;
        setTimeout(() => {
          setDismissed((s) => new Set(s).add(id));
          qc.invalidateQueries({ queryKey: ["channel-workflow-runs", channelId] });
        }, 5000);
      }
    }
    prevRunsRef.current = new Map(runs.map((r) => [r.id, r.status]));
  }, [runs, channelId, qc]);

  // Reset dismissed set on channel switch
  useEffect(() => {
    setDismissed(new Set());
    prevRunsRef.current = new Map();
  }, [channelId]);

  if (!runs || runs.length === 0) return null;

  // Filter out dismissed AND any stale terminal runs (defensive against cached data)
  const visible = runs.filter((r) => !dismissed.has(r.id) && !TERMINAL_STATUSES.has(r.status));
  if (visible.length === 0) return null;

  return (
    <View style={{ borderTopWidth: 1, borderTopColor: t.surfaceBorder }}>
      {visible.map((run) => (
        <RunStrip
          key={run.id}
          run={run}
          t={t}
          onDismiss={() => setDismissed((s) => new Set(s).add(run.id))}
        />
      ))}
    </View>
  );
}

function RunStrip({ run, t, onDismiss }: { run: WorkflowRun; t: ThemeTokens; onDismiss: () => void }) {
  const cancelMut = useCancelWorkflowRun();
  const done = run.step_states.filter((s) => s.status === "done").length;
  const failed = run.step_states.filter((s) => s.status === "failed").length;
  const skipped = run.step_states.filter((s) => s.status === "skipped").length;
  const total = run.step_states.length;
  const isApproval = run.status === "awaiting_approval";
  const isActive = run.status === "running" || isApproval;

  const bgColor = isApproval ? t.warningSubtle : t.surfaceRaised;
  const borderColor = isApproval ? t.warningBorder : t.surfaceBorder;

  let StatusIcon = Loader2;
  let statusColor = t.accent;
  let statusLabel = "running";
  if (run.status === "complete") { StatusIcon = CheckCircle2; statusColor = t.success; statusLabel = "complete"; }
  else if (run.status === "failed") { StatusIcon = XCircle; statusColor = t.danger; statusLabel = "failed"; }
  else if (run.status === "cancelled") { StatusIcon = XCircle; statusColor = t.textDim; statusLabel = "cancelled"; }
  else if (isApproval) { StatusIcon = ShieldCheck; statusColor = t.warning; statusLabel = "needs approval"; }

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "6px 12px",
      background: bgColor,
      borderBottom: `1px solid ${borderColor}`,
      fontSize: 12,
    }}>
      <StatusIcon size={14} color={statusColor} />
      <span style={{ fontWeight: 600, color: t.text }}>
        {run.workflow_id}
      </span>
      <span style={{ color: t.textDim }}>
        {statusLabel}
      </span>

      {/* Mini step bar */}
      <div style={{
        display: "flex", gap: 1, height: 4, borderRadius: 2,
        overflow: "hidden", flex: 1, maxWidth: 120,
      }}>
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

      <span style={{ color: t.textDim, whiteSpace: "nowrap" }}>
        {done + failed + skipped}/{total}
      </span>

      <Link href={`/admin/workflows/${run.workflow_id}?tab=runs&run=${run.id}` as any}>
        <Pressable style={{ flexDirection: "row", alignItems: "center", gap: 3 }}>
          <ExternalLink size={11} color={t.accent} />
          <Text style={{ fontSize: 11, color: t.accent }}>View</Text>
        </Pressable>
      </Link>

      {/* Cancel button for active runs */}
      {isActive && (
        <Pressable
          onPress={() => cancelMut.mutate(run.id)}
          disabled={cancelMut.isPending}
          style={{
            flexDirection: "row", alignItems: "center", gap: 3,
            paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
            backgroundColor: t.dangerSubtle, borderWidth: 1, borderColor: t.dangerBorder,
            opacity: cancelMut.isPending ? 0.5 : 1,
          }}
        >
          <Text style={{ fontSize: 10, color: t.danger, fontWeight: "600" }}>Cancel</Text>
        </Pressable>
      )}

      {/* Dismiss button */}
      <Pressable
        onPress={onDismiss}
        style={{ padding: 2 }}
      >
        <X size={13} color={t.textDim} />
      </Pressable>
    </div>
  );
}
