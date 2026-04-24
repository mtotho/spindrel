import { useEffect, useMemo, useState } from "react";
import { PreviewCard, useNativeEnvelopeState, type NativeAppRendererProps } from "./shared";

type StandingOrderStatus = "running" | "paused" | "done" | "failed" | "cancelled";

interface StandingOrderLogEntry {
  at?: string;
  text?: string;
}

interface StandingOrderState {
  goal?: string;
  status?: StandingOrderStatus;
  strategy?: string;
  strategy_state?: Record<string, unknown>;
  interval_seconds?: number;
  iterations?: number;
  max_iterations?: number;
  completion?: { kind?: string } & Record<string, unknown>;
  log?: StandingOrderLogEntry[];
  message_on_complete?: string | null;
  owning_bot_id?: string;
  next_tick_at?: string | null;
  last_tick_at?: string | null;
  terminal_reason?: string | null;
}

function statusLabel(status: StandingOrderStatus | undefined): string {
  switch (status) {
    case "running":
      return "Running";
    case "paused":
      return "Paused";
    case "done":
      return "Done";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Unknown";
  }
}

function statusColor(
  status: StandingOrderStatus | undefined,
  t: NativeAppRendererProps["t"],
): { bg: string; fg: string } {
  switch (status) {
    case "running":
      return { bg: t.accentSubtle, fg: t.accent };
    case "paused":
      return { bg: t.surfaceRaised, fg: t.textMuted };
    case "done":
      return { bg: t.successSubtle, fg: t.success };
    case "failed":
      return { bg: t.dangerSubtle, fg: t.danger };
    case "cancelled":
      return { bg: t.surfaceRaised, fg: t.textDim };
    default:
      return { bg: t.surfaceRaised, fg: t.textMuted };
  }
}

function formatRelative(iso: string | null | undefined, now: number): string {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return "";
  const delta = Math.round((ts - now) / 1000);
  if (delta >= 0) {
    if (delta < 5) return "any moment";
    if (delta < 60) return `in ${delta}s`;
    if (delta < 3600) return `in ${Math.round(delta / 60)}m`;
    return `in ${Math.round(delta / 3600)}h`;
  }
  const ago = Math.abs(delta);
  if (ago < 60) return `${ago}s ago`;
  if (ago < 3600) return `${Math.round(ago / 60)}m ago`;
  if (ago < 86400) return `${Math.round(ago / 3600)}h ago`;
  return `${Math.round(ago / 86400)}d ago`;
}

export function StandingOrderWidget({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: NativeAppRendererProps) {
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/standing_order_native",
    channelId,
    dashboardPinId,
  );

  const state = (currentPayload.state ?? {}) as StandingOrderState;
  const status: StandingOrderStatus = (state.status ?? "running") as StandingOrderStatus;
  const isTerminal = status === "done" || status === "failed" || status === "cancelled";
  const canPause = status === "running";
  const canResume = status === "paused";
  const canCancel = !isTerminal;

  const [goalDraft, setGoalDraft] = useState(state.goal ?? "");
  const [editingGoal, setEditingGoal] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!editingGoal) setGoalDraft(state.goal ?? "");
  }, [state.goal, editingGoal]);

  useEffect(() => {
    const handle = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(handle);
  }, []);

  const widgetInstanceId = currentPayload.widget_instance_id;
  if (!widgetInstanceId) {
    return (
      <PreviewCard
        title="Standing order"
        description="A bot-spawned durable work item that ticks on a schedule."
        t={t}
      />
    );
  }

  const pill = statusColor(status, t);
  const iterations = state.iterations ?? 0;
  const maxIterations = state.max_iterations ?? 0;
  const log = (state.log ?? []).slice().reverse().slice(0, 5);

  const nextTickLabel =
    status === "running" && state.next_tick_at
      ? `next tick ${formatRelative(state.next_tick_at, now)}`
      : status === "paused"
        ? "paused"
        : status === "done"
          ? state.terminal_reason
            ? `done — ${state.terminal_reason}`
            : "done"
          : status === "failed"
            ? state.terminal_reason
              ? `failed — ${state.terminal_reason}`
              : "failed"
            : status === "cancelled"
              ? "cancelled"
              : "";

  const runAction = async (action: string, args: Record<string, unknown> = {}) => {
    if (busyAction) return;
    setBusyAction(action);
    setActionError(null);
    try {
      await dispatchNativeAction(action, args);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : `${action} failed`);
    } finally {
      setBusyAction(null);
    }
  };

  const saveGoal = async () => {
    const next = goalDraft.trim();
    setEditingGoal(false);
    if (!next || next === state.goal) return;
    await runAction("edit_goal", { goal: next });
  };

  const completionLabel = useMemo(() => {
    const kind = state.completion?.kind;
    if (!kind) return null;
    if (kind === "after_n_iterations") {
      const n = state.completion?.n;
      return `stops after ${n} iteration${n === 1 ? "" : "s"}`;
    }
    if (kind === "state_field_equals") {
      const path = state.completion?.path;
      const value = state.completion?.value;
      return `stops when ${path} = ${JSON.stringify(value)}`;
    }
    if (kind === "deadline_passed") {
      const at = state.completion?.at;
      return `stops ${formatRelative(typeof at === "string" ? at : null, now)}`;
    }
    return kind;
  }, [state.completion, now]);

  const strategyLabel =
    state.strategy === "poll_url"
      ? "polling URL"
      : state.strategy === "timer"
        ? "timer"
        : state.strategy ?? "strategy";

  return (
    <div
      className="flex flex-col gap-3"
      style={{ color: t.text, minHeight: "100%" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          {editingGoal ? (
            <input
              type="text"
              value={goalDraft}
              autoFocus
              onChange={(e) => setGoalDraft(e.target.value)}
              onBlur={saveGoal}
              onKeyDown={(e) => {
                if (e.key === "Enter") void saveGoal();
                if (e.key === "Escape") {
                  setGoalDraft(state.goal ?? "");
                  setEditingGoal(false);
                }
              }}
              className="text-sm font-semibold outline-none"
              style={{
                background: "transparent",
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                padding: "4px 8px",
                color: t.text,
              }}
            />
          ) : (
            <button
              type="button"
              onClick={() => {
                if (!isTerminal) setEditingGoal(true);
              }}
              className="text-sm font-semibold text-left truncate"
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                color: t.text,
                cursor: isTerminal ? "default" : "text",
              }}
              title={state.goal ?? ""}
            >
              {state.goal || "(no goal)"}
            </button>
          )}
          <div className="text-xs" style={{ color: t.textMuted }}>
            {strategyLabel}
            {completionLabel ? ` · ${completionLabel}` : ""}
          </div>
        </div>
        <span
          className="text-xs font-medium px-2 py-1 rounded"
          style={{ background: pill.bg, color: pill.fg }}
        >
          {statusLabel(status)}
        </span>
      </div>

      <div
        className="flex items-center justify-between text-xs"
        style={{ color: t.textMuted }}
      >
        <span>
          {iterations} tick{iterations === 1 ? "" : "s"}
          {maxIterations ? ` / ${maxIterations}` : ""}
        </span>
        <span>{nextTickLabel}</span>
      </div>

      {log.length > 0 && (
        <div
          className="flex flex-col gap-1 text-xs rounded"
          style={{
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            padding: 8,
            maxHeight: 140,
            overflowY: "auto",
            color: t.textMuted,
          }}
        >
          {log.map((entry, idx) => (
            <div key={idx} className="flex gap-2">
              <span style={{ color: t.textDim, flexShrink: 0 }}>
                {formatRelative(entry.at, now)}
              </span>
              <span style={{ color: t.text, wordBreak: "break-word" }}>
                {entry.text ?? ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {actionError && (
        <div className="text-xs" style={{ color: t.danger }}>
          {actionError}
        </div>
      )}

      {!isTerminal && (
        <div className="flex gap-2">
          {canPause && (
            <button
              type="button"
              onClick={() => void runAction("pause")}
              disabled={busyAction !== null}
              className="text-xs px-2 py-1 rounded"
              style={{
                background: t.surfaceRaised,
                border: `1px solid ${t.surfaceBorder}`,
                color: t.text,
                cursor: busyAction !== null ? "wait" : "pointer",
                opacity: busyAction !== null ? 0.6 : 1,
              }}
            >
              Pause
            </button>
          )}
          {canResume && (
            <button
              type="button"
              onClick={() => void runAction("resume")}
              disabled={busyAction !== null}
              className="text-xs px-2 py-1 rounded"
              style={{
                background: t.surfaceRaised,
                border: `1px solid ${t.surfaceBorder}`,
                color: t.text,
                cursor: busyAction !== null ? "wait" : "pointer",
                opacity: busyAction !== null ? 0.6 : 1,
              }}
            >
              Resume
            </button>
          )}
          {canCancel && (
            <button
              type="button"
              onClick={() => void runAction("cancel")}
              disabled={busyAction !== null}
              className="text-xs px-2 py-1 rounded ml-auto"
              style={{
                background: "transparent",
                border: `1px solid ${t.surfaceBorder}`,
                color: t.danger,
                cursor: busyAction !== null ? "wait" : "pointer",
                opacity: busyAction !== null ? 0.6 : 1,
              }}
            >
              Cancel
            </button>
          )}
        </div>
      )}
    </div>
  );
}
