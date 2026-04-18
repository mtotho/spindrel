import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CalendarClock,
  Clock,
  ExternalLink,
  Loader2,
  Star,
  Trash2,
  Zap,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import { apiFetch } from "@/src/api/client";
import { useQuery } from "@tanstack/react-query";
import {
  useChannelPipelines,
  useSubscribePipeline,
  useUpdateSubscription,
  useUnsubscribePipeline,
  type ChannelPipelineSubscription,
} from "@/src/api/hooks/useChannelPipelines";
import { CronScheduleModal } from "@/src/components/shared/CronScheduleModal";
import { humanLabelFor } from "@/src/components/shared/CronInput";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";

interface TasksListResponse {
  tasks: Array<{
    id: string;
    title?: string | null;
    bot_id: string;
    source?: "user" | "system";
    task_type: string;
    execution_config?: Record<string, any> | null;
  }>;
  schedules: TasksListResponse["tasks"];
  total: number;
}

function relTime(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!then) return "";
  const diffMs = then - Date.now();
  const abs = Math.abs(diffMs);
  const sec = Math.floor(abs / 1000);
  const prefix = diffMs >= 0 ? "in " : "";
  const suffix = diffMs >= 0 ? "" : " ago";
  if (sec < 60) return `${prefix}${sec}s${suffix}`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${prefix}${min}m${suffix}`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${prefix}${hr}h${suffix}`;
  const day = Math.floor(hr / 24);
  return `${prefix}${day}d${suffix}`;
}

export function PipelinesTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const subsQ = useChannelPipelines(channelId);
  // All pipeline definitions (user + system) — so we can offer "available to subscribe".
  const defsQ = useQuery({
    queryKey: ["pipeline-definitions-all"],
    queryFn: () =>
      apiFetch<TasksListResponse>(
        "/api/v1/admin/tasks?task_type=pipeline&definitions_only=true&limit=200",
      ),
  });

  const subs = subsQ.data?.subscriptions ?? [];
  const defs = defsQ.data?.tasks ?? [];
  const subscribedIds = useMemo(() => new Set(subs.map((s) => s.task_id)), [subs]);
  const available = useMemo(
    () => defs.filter((d) => !subscribedIds.has(d.id)),
    [defs, subscribedIds],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, paddingBottom: 24 }}>
      <div style={{ fontSize: 12, color: t.textDim, lineHeight: 1.5 }}>
        Subscribe pipelines to this channel so they can be launched from its
        launchpad and optionally scheduled on their own cadence here. Pipelines
        are shared definitions — scheduling and featuring is per-channel.
      </div>

      <Section title="Subscribed" description="Pipelines this channel can run.">
        {subsQ.isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
            <Loader2 className="animate-spin" size={18} color={t.textDim} />
          </div>
        ) : subs.length === 0 ? (
          <EmptyState message="No pipelines subscribed yet. Pick one below to get started." />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {subs.map((s) => (
              <SubscriptionRow key={s.id} channelId={channelId} sub={s} t={t} />
            ))}
          </div>
        )}
      </Section>

      <Section title="Available" description="Pipelines you haven't subscribed to yet.">
        {defsQ.isLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
            <Loader2 className="animate-spin" size={18} color={t.textDim} />
          </div>
        ) : available.length === 0 ? (
          <EmptyState
            message={
              defs.length === 0
                ? "No pipeline definitions exist yet. Create one in Admin → Tasks."
                : "This channel is subscribed to every known pipeline."
            }
          />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {available.map((d) => (
              <AvailableRow key={d.id} channelId={channelId} def={d} t={t} />
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subscribed row — enable toggle + featured star + schedule button + remove
// ---------------------------------------------------------------------------

function SubscriptionRow({
  channelId,
  sub,
  t,
}: {
  channelId: string;
  sub: ChannelPipelineSubscription;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const update = useUpdateSubscription(channelId);
  const unsub = useUnsubscribePipeline(channelId);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const p = sub.pipeline;

  const scheduleLabel = sub.schedule
    ? humanLabelFor(sub.schedule) ?? sub.schedule
    : "—";
  const nextFire = sub.enabled ? relTime(sub.next_fire_at) : "";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        padding: "10px 12px",
        background: sub.enabled ? t.surfaceRaised : t.surface,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        opacity: sub.enabled ? 1 : 0.7,
      }}
    >
      {/* Featured star */}
      <button
        title={sub.featured ? "Unfeature" : "Feature on launchpad"}
        onClick={() =>
          update.mutate({
            subscriptionId: sub.id,
            patch: { featured_override: sub.featured ? false : true },
          })
        }
        style={{
          background: "transparent",
          border: "none",
          padding: 2,
          cursor: "pointer",
          color: sub.featured ? t.warning : t.textDim,
          display: "flex",
          alignItems: "center",
        }}
      >
        <Star size={16} fill={sub.featured ? "currentColor" : "none"} />
      </button>

      {/* Title + description */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
            {p?.title ?? sub.task_id}
          </span>
          {p?.source === "system" && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: t.accent,
                background: t.accentSubtle,
                border: `1px solid ${t.accentBorder}`,
                padding: "1px 6px",
                borderRadius: 4,
                letterSpacing: 0.5,
              }}
            >
              SYSTEM
            </span>
          )}
        </div>
        {p?.description && (
          <div
            style={{
              fontSize: 11,
              color: t.textDim,
              marginTop: 2,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {p.description}
          </div>
        )}
      </div>

      {/* Schedule */}
      <button
        onClick={() => setScheduleOpen(true)}
        title="Edit schedule"
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          background: "transparent",
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6,
          padding: "4px 10px",
          cursor: "pointer",
          color: sub.schedule ? t.text : t.textDim,
          fontSize: 11,
          fontFamily: sub.schedule
            ? "ui-monospace, SFMono-Regular, Menlo, monospace"
            : undefined,
        }}
      >
        <CalendarClock size={12} />
        <span>{scheduleLabel}</span>
        {nextFire && <span style={{ color: t.textDim }}>· next {nextFire}</span>}
      </button>

      {/* Enable toggle */}
      <label
        title={sub.enabled ? "Disable" : "Enable"}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          cursor: "pointer",
          color: t.textMuted,
          fontSize: 11,
        }}
      >
        <input
          type="checkbox"
          checked={sub.enabled}
          onChange={(e) =>
            update.mutate({
              subscriptionId: sub.id,
              patch: { enabled: e.target.checked },
            })
          }
        />
        {sub.enabled ? "On" : "Off"}
      </label>

      {/* Overflow actions */}
      <Link
        to={`/admin/tasks/${sub.task_id}`}
        title="View pipeline definition"
        style={{
          color: t.textDim,
          display: "flex",
          alignItems: "center",
          padding: 4,
        }}
      >
        <ExternalLink size={14} />
      </Link>
      <button
        title="Unsubscribe"
        onClick={async () => {
          const ok = await confirm(
            `Unsubscribe this channel from "${p?.title ?? "pipeline"}"?`,
            { title: "Unsubscribe", confirmLabel: "Unsubscribe", variant: "danger" },
          );
          if (!ok) return;
          unsub.mutate(sub.id);
        }}
        style={{
          background: "transparent",
          border: "none",
          padding: 4,
          cursor: "pointer",
          color: t.textDim,
          display: "flex",
          alignItems: "center",
        }}
      >
        <Trash2 size={14} />
      </button>

      {scheduleOpen && (
        <CronScheduleModal
          title={`Schedule "${p?.title ?? "pipeline"}"`}
          initial={sub.schedule}
          onClose={() => setScheduleOpen(false)}
          onSave={async (expr) => {
            await update.mutateAsync({
              subscriptionId: sub.id,
              patch: expr === null ? { clear_schedule: true } : { schedule: expr },
            });
          }}
        />
      )}
      <ConfirmDialogSlot />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Available row — compact, single "Subscribe" button
// ---------------------------------------------------------------------------

function AvailableRow({
  channelId,
  def,
  t,
}: {
  channelId: string;
  def: TasksListResponse["tasks"][number];
  t: ReturnType<typeof useThemeTokens>;
}) {
  const subscribe = useSubscribePipeline(channelId);
  const description = def.execution_config?.description ?? null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        padding: "8px 12px",
        border: `1px dashed ${t.surfaceBorder}`,
        borderRadius: 8,
      }}
    >
      <Clock size={14} color={t.textDim} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>
            {def.title ?? def.id}
          </span>
          {def.source === "system" && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: t.accent,
                background: t.accentSubtle,
                border: `1px solid ${t.accentBorder}`,
                padding: "1px 6px",
                borderRadius: 4,
                letterSpacing: 0.5,
              }}
            >
              SYSTEM
            </span>
          )}
        </div>
        {description && (
          <div
            style={{
              fontSize: 11,
              color: t.textDim,
              marginTop: 2,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {description}
          </div>
        )}
      </div>
      <button
        onClick={() => subscribe.mutate({ task_id: def.id })}
        disabled={subscribe.isPending}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          background: t.accent,
          border: "none",
          color: "#fff",
          borderRadius: 6,
          padding: "4px 10px",
          fontSize: 11,
          fontWeight: 600,
          cursor: subscribe.isPending ? "default" : "pointer",
          opacity: subscribe.isPending ? 0.6 : 1,
        }}
      >
        <Zap size={12} />
        Subscribe
      </button>
    </div>
  );
}
