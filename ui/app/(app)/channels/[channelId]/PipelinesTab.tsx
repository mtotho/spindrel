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
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  SettingsControlRow,
  SettingsSearchBox,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
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
  const [query, setQuery] = useState("");
  const subscribedIds = useMemo(() => new Set(subs.map((s) => s.task_id)), [subs]);
  const available = useMemo(() => {
    const q = query.trim().toLowerCase();
    return defs.filter((d) => {
      if (subscribedIds.has(d.id)) return false;
      if (!q) return true;
      const description = String(d.execution_config?.description ?? "");
      return (
        d.id.toLowerCase().includes(q) ||
        (d.title ?? "").toLowerCase().includes(q) ||
        description.toLowerCase().includes(q)
      );
    });
  }, [defs, query, subscribedIds]);

  return (
    <div className="flex flex-col gap-5 pb-6">
      <div className="max-w-[65ch] text-[12px] leading-relaxed text-text-dim">
        Subscribe pipelines to this channel so they can be launched from its
        launchpad and optionally scheduled on their own cadence here. Pipelines
        are shared definitions — scheduling and featuring is per-channel.
      </div>

      <Section title="Subscribed" description="Pipelines this channel can run.">
        {subsQ.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="animate-spin text-text-dim" size={18} />
          </div>
        ) : subs.length === 0 ? (
          <EmptyState message="No pipelines subscribed yet. Pick one below to get started." />
        ) : (
          <div className="flex flex-col gap-2">
            {subs.map((s) => (
              <SubscriptionRow key={s.id} channelId={channelId} sub={s} />
            ))}
          </div>
        )}
      </Section>

      <Section
        title="Available"
        description="Pipelines you haven't subscribed to yet."
        action={defs.length > 6 ? (
          <SettingsSearchBox value={query} onChange={setQuery} placeholder="Filter pipelines..." className="w-64" />
        ) : undefined}
      >
        {defsQ.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="animate-spin text-text-dim" size={18} />
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
          <div className="flex flex-col gap-2">
            {available.map((d) => (
              <AvailableRow key={d.id} channelId={channelId} def={d} />
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
}: {
  channelId: string;
  sub: ChannelPipelineSubscription;
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
    <SettingsControlRow disabled={!sub.enabled} className="flex flex-wrap items-center gap-3">
      {/* Featured star */}
      <button
        title={sub.featured ? "Unfeature" : "Feature on launchpad"}
        onClick={() =>
          update.mutate({
            subscriptionId: sub.id,
            patch: { featured_override: sub.featured ? false : true },
          })
        }
        className={`inline-flex items-center p-1 transition-colors ${sub.featured ? "text-warning-muted" : "text-text-dim hover:text-text-muted"}`}
      >
        <Star size={16} fill={sub.featured ? "currentColor" : "none"} />
      </button>

      {/* Title + description */}
      <div className="min-w-[220px] flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-semibold text-text">
            {p?.title ?? sub.task_id}
          </span>
          {p?.source === "system" && <StatusBadge label="system" variant="info" />}
          {!sub.enabled && <StatusBadge label="off" variant="neutral" />}
        </div>
        {p?.description && (
          <div className="mt-0.5 truncate text-[11px] text-text-dim">
            {p.description}
          </div>
        )}
      </div>

      {/* Schedule */}
      <button
        onClick={() => setScheduleOpen(true)}
        title="Edit schedule"
        className={`inline-flex min-h-[32px] items-center gap-1.5 rounded-md px-2.5 text-[11px] transition-colors hover:bg-surface-overlay/45 ${sub.schedule ? "font-mono text-text-muted" : "text-text-dim"}`}
      >
        <CalendarClock size={12} />
        <span>{scheduleLabel}</span>
        {nextFire && <span className="text-text-dim">· next {nextFire}</span>}
      </button>

      {/* Enable toggle */}
      <label
        title={sub.enabled ? "Disable" : "Enable"}
        className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] text-text-muted"
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
        className="inline-flex items-center p-1 text-text-dim transition-colors hover:text-accent"
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
        className="inline-flex items-center p-1 text-text-dim transition-colors hover:text-danger"
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
    </SettingsControlRow>
  );
}

// ---------------------------------------------------------------------------
// Available row — compact, single "Subscribe" button
// ---------------------------------------------------------------------------

function AvailableRow({
  channelId,
  def,
}: {
  channelId: string;
  def: TasksListResponse["tasks"][number];
}) {
  const subscribe = useSubscribePipeline(channelId);
  const description = def.execution_config?.description ?? null;

  return (
    <SettingsControlRow className="flex flex-wrap items-center gap-3">
      <Clock size={14} className="shrink-0 text-text-dim" />
      <div className="min-w-[220px] flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[13px] font-medium text-text">
            {def.title ?? def.id}
          </span>
          {def.source === "system" && <StatusBadge label="system" variant="info" />}
        </div>
        {description && (
          <div className="mt-0.5 truncate text-[11px] text-text-dim">
            {description}
          </div>
        )}
      </div>
      <ActionButton
        label={subscribe.isPending ? "Subscribing..." : "Subscribe"}
        onPress={() => subscribe.mutate({ task_id: def.id })}
        disabled={subscribe.isPending}
        size="small"
        icon={<Zap size={12} />}
      />
    </SettingsControlRow>
  );
}
