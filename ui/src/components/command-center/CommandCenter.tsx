import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock,
  ExternalLink,
  ListChecks,
  Plus,
  Radar,
} from "lucide-react";

import {
  useCommandCenter,
  useCreateCommandCenterIntake,
  type CommandCenterBotRow,
  type CommandCenterRecentEvent,
} from "../../api/hooks/useCommandCenter";
import type { AttentionSeverity, WorkspaceAttentionItem } from "../../api/hooks/useWorkspaceAttention";
import { useBots } from "../../api/hooks/useBots";
import { useChannels } from "../../api/hooks/useChannels";
import { BotPicker } from "../shared/BotPicker";
import { ChannelPicker } from "../shared/ChannelPicker";
import { StatusBadge } from "../shared/SettingsControls";
import { openTraceInspector } from "../../stores/traceInspector";

type AssignmentMode = "none" | "next_heartbeat" | "run_now";

const SEVERITY_VARIANT: Record<AttentionSeverity, "danger" | "warning" | "info"> = {
  critical: "danger",
  error: "danger",
  warning: "warning",
  info: "info",
};

function formatRelative(value?: string | null): string {
  if (!value) return "unscheduled";
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return "unknown";
  const minutes = Math.round((ts - Date.now()) / 60000);
  if (minutes < -60) return `${Math.abs(Math.round(minutes / 60))}h ago`;
  if (minutes < 0) return `${Math.abs(minutes)}m ago`;
  if (minutes < 1) return "now";
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

function eventLabel(event: CommandCenterRecentEvent): string {
  if (event.type === "assignment_report") return "Report";
  if (event.type === "heartbeat") return "Heartbeat";
  if (event.type === "task") return "Task";
  return "Attention";
}

function itemStatus(item: WorkspaceAttentionItem): string {
  if (item.assignment_status === "running") return "running";
  if (item.assignment_status === "assigned") return "queued";
  if (item.assignment_status === "reported") return "reported";
  return item.status;
}

function automationHref() {
  return "/admin/automations?view=list";
}

export function CommandCenter({
  embedded = false,
  initialItemId = null,
}: {
  embedded?: boolean;
  initialItemId?: string | null;
}) {
  const { data, isLoading, isError } = useCommandCenter();
  const [selectedId, setSelectedId] = useState<string | null>(initialItemId);
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  useEffect(() => {
    setSelectedId(initialItemId);
  }, [initialItemId]);
  const selected = useMemo(() => {
    if (!data || !selectedId) return null;
    return data.attention.find((item) => item.id === selectedId) ?? null;
  }, [data, selectedId]);

  if (isLoading) {
    return <div className="p-4 text-sm text-text-dim">Loading Command Center...</div>;
  }
  if (isError || !data) {
    return <div className="p-4 text-sm text-text-muted">Command Center is unavailable.</div>;
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${embedded ? "" : "h-full"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Radar size={14} />
            Command Center
          </div>
          <div className="mt-1 text-xs text-text-muted">
            {data.summary.assigned} assigned · {data.summary.upcoming} upcoming · {data.summary.recent} recent
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Link
            to={automationHref()}
            className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text"
          >
            Automations
          </Link>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-accent hover:bg-accent/[0.08]"
            onClick={() => setQuickAddOpen((open) => !open)}
          >
            <Plus size={14} />
            Add
          </button>
        </div>
      </div>

      {quickAddOpen ? (
        <QuickAddForm
          onCreated={(item) => {
            setQuickAddOpen(false);
            setSelectedId(item.id);
          }}
        />
      ) : selected ? (
        <CommandCenterDetail item={selected} onBack={() => setSelectedId(null)} />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto px-3 pb-4">
          <SummaryStrip data={data.summary} />
          <section className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Bot Board</div>
              <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{data.bots.length}</span>
            </div>
            <div className="grid gap-2">
              {data.bots.length ? data.bots.map((bot) => (
                <BotBoardRow key={bot.bot_id} bot={bot} onSelectItem={setSelectedId} />
              )) : (
                <div className="rounded-md border border-dashed border-surface-border px-3 py-6 text-center text-sm text-text-dim">
                  No assigned or scheduled work in the current window.
                </div>
              )}
            </div>
          </section>
          <section className="mt-5 grid gap-4 lg:grid-cols-2">
            <RecentActivity events={data.recent.slice(0, 8)} />
            <UpcomingActivity items={data.upcoming.slice(0, 8)} />
          </section>
        </div>
      )}
    </div>
  );
}

function SummaryStrip({ data }: { data: { active_attention: number; assigned: number; blocked: number; upcoming: number; recent: number } }) {
  const stats = [
    { label: "Assigned", value: data.assigned, Icon: ListChecks },
    { label: "Blocked", value: data.blocked, Icon: AlertTriangle },
    { label: "Upcoming", value: data.upcoming, Icon: Clock },
    { label: "Recent", value: data.recent, Icon: Activity },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {stats.map(({ label, value, Icon }) => (
        <div key={label} className="rounded-md bg-surface-raised/45 px-3 py-2">
          <div className="flex items-center gap-2 text-xs text-text-dim">
            <Icon size={13} />
            {label}
          </div>
          <div className="mt-1 text-lg font-semibold text-text">{value}</div>
        </div>
      ))}
    </div>
  );
}

function BotBoardRow({ bot, onSelectItem }: { bot: CommandCenterBotRow; onSelectItem: (id: string) => void }) {
  const active = bot.active_assignment;
  const blocked = Boolean(active?.queue_state?.blocked);
  return (
    <article className="rounded-md bg-surface-raised/45 px-3 py-3 hover:bg-surface-overlay/35">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/[0.1] text-accent">
              <Bot size={15} />
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-text">{bot.bot_name}</div>
              <div className="truncate text-xs text-text-dim">
                {bot.harness_runtime ? `${bot.harness_runtime} harness` : "Spindrel bot"}
                {bot.heartbeat_channel_name ? ` · ${bot.heartbeat_channel_name}` : ""}
              </div>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className={`rounded-full px-2 py-0.5 ${blocked ? "bg-warning/10 text-warning-muted" : "bg-surface-overlay text-text-muted"}`}>
            {blocked ? "blocked" : formatRelative(bot.next_heartbeat_at)}
          </span>
          <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-text-muted">
            {bot.queue_depth} queued
          </span>
        </div>
      </div>
      {active ? (
        <button
          type="button"
          className="mt-3 flex w-full items-start gap-3 rounded-md bg-surface/45 px-3 py-2 text-left hover:bg-surface-overlay/55"
          onClick={() => onSelectItem(active.id)}
        >
          <StatusBadge label={active.severity} variant={SEVERITY_VARIANT[active.severity]} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-text">{active.title}</span>
            <span className="mt-1 block truncate text-xs text-text-dim">
              {itemStatus(active)}
              {active.queue_state?.next_run_at ? ` · ${formatRelative(active.queue_state.next_run_at)}` : ""}
              {active.queue_state?.blocked ? ` · ${active.queue_state.blocked_reason}` : ""}
            </span>
          </span>
        </button>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-surface-border px-3 py-3 text-xs text-text-dim">
          No active assignment.
        </div>
      )}
    </article>
  );
}

function RecentActivity({ events }: { events: CommandCenterRecentEvent[] }) {
  return (
    <section>
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Recently Happened</div>
      <div className="space-y-1">
        {events.length ? events.map((event, index) => (
          <div key={`${event.type}-${event.occurred_at}-${index}`} className="rounded-md bg-surface-raised/45 px-3 py-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-text">{event.title}</div>
                <div className="mt-1 truncate text-xs text-text-dim">
                  {eventLabel(event)}
                  {event.channel_name ? ` · ${event.channel_name}` : ""}
                  {event.bot_name ? ` · ${event.bot_name}` : ""}
                </div>
              </div>
              <span className="shrink-0 text-xs tabular-nums text-text-dim">{formatRelative(event.occurred_at)}</span>
            </div>
            {event.summary ? <div className="mt-2 line-clamp-2 text-xs text-text-muted">{event.summary}</div> : null}
          </div>
        )) : (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-6 text-center text-sm text-text-dim">
            No recent run reports.
          </div>
        )}
      </div>
    </section>
  );
}

function UpcomingActivity({ items }: { items: Array<{ type: string; title: string; scheduled_at: string; channel_name?: string | null; bot_name?: string | null }> }) {
  return (
    <section>
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Upcoming</div>
      <div className="space-y-1">
        {items.length ? items.map((item, index) => (
          <div key={`${item.type}-${item.scheduled_at}-${index}`} className="flex items-center gap-3 rounded-md bg-surface-raised/45 px-3 py-2">
            <Clock size={14} className="shrink-0 text-text-dim" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-text">{item.title}</div>
              <div className="truncate text-xs text-text-dim">
                {item.type}
                {item.channel_name ? ` · ${item.channel_name}` : ""}
                {!item.channel_name && item.bot_name ? ` · ${item.bot_name}` : ""}
              </div>
            </div>
            <span className="shrink-0 text-xs tabular-nums text-text-dim">{formatRelative(item.scheduled_at)}</span>
          </div>
        )) : (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-6 text-center text-sm text-text-dim">
            Nothing scheduled in the next 24 hours.
          </div>
        )}
      </div>
    </section>
  );
}

function CommandCenterDetail({ item, onBack }: { item: WorkspaceAttentionItem; onBack: () => void }) {
  return (
    <div className="min-h-0 flex-1 overflow-auto px-4 pb-4">
      <button type="button" className="mb-3 rounded-md px-2 py-1 text-xs text-text-dim hover:bg-surface-overlay/60 hover:text-text" onClick={onBack}>
        Back to board
      </button>
      <section className="rounded-md bg-surface-raised/50 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Attention Work</div>
            <h2 className="mt-1 text-lg font-semibold text-text">{item.title}</h2>
            <div className="mt-1 text-xs text-text-muted">
              {item.channel_name ?? item.channel_id ?? item.target_kind} · {itemStatus(item)}
            </div>
          </div>
          <StatusBadge label={item.severity} variant={SEVERITY_VARIANT[item.severity]} />
        </div>
        {item.message ? <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-text-muted">{item.message}</p> : null}
        {item.queue_state?.blocked ? (
          <div className="mt-4 rounded-md bg-warning/10 px-3 py-2 text-sm text-warning-muted">
            {item.queue_state.blocked_reason}
          </div>
        ) : null}
        {item.assignment_report ? (
          <div className="mt-4 rounded-md bg-accent/[0.08] p-3">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Bot Findings</div>
            <p className="whitespace-pre-wrap text-sm text-text-muted">{item.assignment_report}</p>
          </div>
        ) : null}
        <div className="mt-4 grid gap-2 text-xs text-text-dim md:grid-cols-2">
          <span>Assigned: {item.assigned_bot_id ?? "none"}</span>
          <span>Next run: {formatRelative(item.queue_state?.next_run_at)}</span>
          <span>Occurrences: {item.occurrence_count}</span>
          <span>Last seen: {item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : "unknown"}</span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {item.latest_correlation_id ? (
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm text-accent hover:bg-accent/10"
              onClick={() => openTraceInspector({ correlationId: item.latest_correlation_id!, title: item.title })}
            >
              <ExternalLink size={14} />
              Open trace
            </button>
          ) : null}
          {item.channel_id ? (
            <Link to={`/channels/${item.channel_id}`} className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm text-text-muted hover:bg-surface-overlay hover:text-text">
              <CheckCircle2 size={14} />
              Open channel
            </Link>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function QuickAddForm({ onCreated }: { onCreated: (item: WorkspaceAttentionItem) => void }) {
  const { data: channels = [] } = useChannels();
  const { data: bots = [] } = useBots();
  const create = useCreateCommandCenterIntake();
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [severity, setSeverity] = useState<AttentionSeverity>("warning");
  const [mode, setMode] = useState<AssignmentMode>("next_heartbeat");
  const [botId, setBotId] = useState("");
  const [instructions, setInstructions] = useState("");
  const selectedChannel = channels.find((channel) => channel.id === channelId);
  const canSubmit = Boolean(channelId && title.trim());

  return (
    <form
      className="mx-3 mb-3 rounded-md bg-surface-raised/55 p-3"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const item = await create.mutateAsync({
          channel_id: channelId,
          title,
          message,
          severity,
          assignment_mode: mode === "none" ? null : mode,
          assign_bot_id: mode === "run_now" ? botId || null : null,
          assignment_instructions: instructions || null,
        });
        onCreated(item);
      }}
    >
      <div className="grid gap-3 md:grid-cols-2">
        <ChannelPicker value={channelId} onChange={setChannelId} channels={channels} bots={bots} placeholder="Target channel" />
        <select className="rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text" value={severity} onChange={(event) => setSeverity(event.target.value as AttentionSeverity)}>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
      </div>
      <input className="mt-3 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Task title" value={title} onChange={(event) => setTitle(event.target.value)} />
      <textarea className="mt-3 min-h-24 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="What should be investigated?" value={message} onChange={(event) => setMessage(event.target.value)} />
      <div className="mt-3 grid grid-cols-3 gap-1 rounded-md bg-surface-overlay/35 p-1">
        {[
          ["next_heartbeat", "Next heartbeat"],
          ["run_now", "Run now"],
          ["none", "Unassigned"],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={`rounded px-2 py-1.5 text-xs ${mode === value ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/70 hover:text-text"}`}
            onClick={() => setMode(value as AssignmentMode)}
          >
            {label}
          </button>
        ))}
      </div>
      {mode === "next_heartbeat" && (
        <div className="mt-2 text-xs text-text-dim">
          Queues one item for {selectedChannel ? selectedChannel.name : "the channel"}'s heartbeat bot.
        </div>
      )}
      {mode === "run_now" && (
        <div className="mt-3">
          <BotPicker value={botId} onChange={setBotId} bots={bots} allowNone={false} />
        </div>
      )}
      {mode !== "none" && (
        <textarea className="mt-3 min-h-20 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Assignment instructions" value={instructions} onChange={(event) => setInstructions(event.target.value)} />
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <Link to={automationHref()} className="text-xs text-text-dim hover:text-text">Need a real schedule? Open Automations</Link>
        <button type="submit" disabled={!canSubmit || create.isPending} className="rounded-md px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.08] disabled:opacity-50">
          Create
        </button>
      </div>
    </form>
  );
}
