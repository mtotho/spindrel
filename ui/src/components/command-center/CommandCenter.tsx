import { useEffect, useMemo, useState } from "react";
import { Activity, Bot, CheckCircle2, Clock, ExternalLink, ListChecks, Pause, Play, Radar, Route, Settings2, Sparkles, Zap } from "lucide-react";

import { useBots } from "../../api/hooks/useBots";
import { useChannels } from "../../api/hooks/useChannels";
import {
  useCreateWorkspaceMission,
  useRunWorkspaceMissionNow,
  useSetWorkspaceMissionStatus,
  useWorkspaceMissions,
  type MissionScope,
  type WorkspaceMission,
  type WorkspaceMissionUpdate,
} from "../../api/hooks/useWorkspaceMissions";
import { BotPicker } from "../shared/BotPicker";
import { ChannelPicker } from "../shared/ChannelPicker";
import { LlmModelDropdown } from "../shared/LlmModelDropdown";
import { StatusBadge } from "../shared/SettingsControls";
import { openTraceInspector } from "../../stores/traceInspector";
import { useRuntimeCapabilities } from "../../api/hooks/useRuntimes";

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

function recurrenceLabel(value?: string | null): string {
  if (!value) return "manual";
  const match = /^\+(\d+)([smhdw])$/.exec(value);
  if (!match) return value;
  const count = Number(match[1]);
  const unit = { s: "sec", m: "min", h: "hr", d: "day", w: "week" }[match[2] as "s" | "m" | "h" | "d" | "w"];
  return `every ${count} ${unit}${count === 1 ? "" : "s"}`;
}

function missionStatusVariant(status: WorkspaceMission["status"]): "success" | "warning" | "info" {
  if (status === "active") return "success";
  if (status === "paused") return "warning";
  return "info";
}

function updateIcon(kind: WorkspaceMissionUpdate["kind"]) {
  if (kind === "error") return <Activity size={13} className="text-danger" />;
  if (kind === "created") return <Sparkles size={13} className="text-accent" />;
  if (kind === "kickoff") return <Zap size={13} className="text-warning-muted" />;
  return <CheckCircle2 size={13} className="text-success" />;
}

export function CommandCenter({
  embedded = false,
}: {
  embedded?: boolean;
  initialItemId?: string | null;
}) {
  const { data: missions, isLoading, isError } = useWorkspaceMissions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useMemo(() => missions?.find((mission) => mission.id === selectedId) ?? null, [missions, selectedId]);
  const activeCount = (missions ?? []).filter((mission) => mission.status === "active").length;
  const pausedCount = (missions ?? []).filter((mission) => mission.status === "paused").length;
  const updateCount = (missions ?? []).reduce((sum, mission) => sum + mission.updates.length, 0);

  if (isLoading) {
    return <div className="p-4 text-sm text-text-dim">Loading Mission Control...</div>;
  }
  if (isError || !missions) {
    return <div className="p-4 text-sm text-text-muted">Mission Control is unavailable.</div>;
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${embedded ? "" : "h-full"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Radar size={14} />
            Mission Control
          </div>
          <div className="mt-1 text-xs text-text-muted">
            {activeCount} active · {pausedCount} paused · {updateCount} recent updates
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-3 pb-4">
        {selected ? (
          <MissionDetail mission={selected} onBack={() => setSelectedId(null)} />
        ) : (
          <>
            <MissionComposer />
            <BotLanes missions={missions} onSelect={setSelectedId} />
            <section className="mt-5">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Mission Updates</div>
                <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{updateCount}</span>
              </div>
              <div className="space-y-1">
                {missions.flatMap((mission) => mission.updates.map((update) => ({ mission, update }))).slice(0, 10).map(({ mission, update }) => (
                  <MissionUpdateRow key={update.id} mission={mission} update={update} onSelect={() => setSelectedId(mission.id)} />
                ))}
                {!updateCount && (
                  <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-3 py-6 text-center text-sm text-text-dim">
                    No mission updates yet.
                  </div>
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function MissionComposer() {
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const create = useCreateWorkspaceMission();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [directive, setDirective] = useState("");
  const [scope, setScope] = useState<MissionScope>("workspace");
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [recurrence, setRecurrence] = useState("+4h");
  const [advanced, setAdvanced] = useState(false);
  const [model, setModel] = useState("");
  const [providerId, setProviderId] = useState<string | null>(null);
  const [harnessEffort, setHarnessEffort] = useState("");
  const botList = bots ?? [];
  const channelList = channels ?? [];
  const effectiveBotId = botId || channelList.find((channel) => channel.id === channelId)?.bot_id || botList[0]?.id || "";
  const selectedBot = botList.find((bot) => bot.id === effectiveBotId);
  const harnessRuntime = selectedBot?.harness_runtime ?? null;
  const { data: harnessCaps } = useRuntimeCapabilities(harnessRuntime);
  const harnessModelOptions = harnessCaps?.model_options ?? [];
  const harnessModels = harnessCaps?.available_models?.length
    ? harnessCaps.available_models
    : harnessCaps?.supported_models ?? [];
  const harnessEffortValues = (
    harnessModelOptions.find((option) => option.id === model)?.effort_values
    ?? harnessCaps?.effort_values
    ?? []
  );

  useEffect(() => {
    setModel("");
    setProviderId(null);
    setHarnessEffort("");
  }, [effectiveBotId]);

  useEffect(() => {
    if (!harnessEffort || !harnessEffortValues.length) return;
    if (!harnessEffortValues.includes(harnessEffort)) {
      setHarnessEffort("");
    }
  }, [harnessEffort, harnessEffortValues]);

  const submit = () => {
    const cleanTitle = title.trim();
    const cleanDirective = directive.trim();
    if (!cleanTitle || !cleanDirective || !effectiveBotId) return;
    create.mutate({
      title: cleanTitle,
      directive: cleanDirective,
      scope,
      channel_id: scope === "channel" ? channelId || null : null,
      bot_id: effectiveBotId,
      interval_kind: recurrence ? (["+1h", "+4h", "+1d"].includes(recurrence) ? "preset" : "custom") : "manual",
      recurrence: recurrence || null,
      model_override: model || null,
      model_provider_id_override: harnessRuntime ? null : providerId ?? null,
      harness_effort: harnessRuntime ? harnessEffort || null : null,
      history_mode: "recent",
      history_recent_count: 8,
    }, {
      onSuccess: () => {
        setTitle("");
        setDirective("");
        setOpen(false);
      },
    });
  };

  if (!open) {
    return (
      <section className="mb-5">
        <button
          type="button"
          className="flex w-full items-center justify-between rounded-md bg-surface-raised/45 px-3 py-3 text-left hover:bg-surface-overlay/45"
          onClick={() => setOpen(true)}
        >
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-text">Create a mission</span>
            <span className="mt-0.5 block text-xs text-text-dim">Give a bot a broad objective with configurable follow-up ticks.</span>
          </span>
          <Sparkles size={16} className="shrink-0 text-accent" />
        </button>
      </section>
    );
  }

  return (
    <section className="mb-5 rounded-md bg-surface-raised/45 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-text">New mission</div>
        <button type="button" className="rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text" onClick={() => setOpen(false)}>
          Close
        </button>
      </div>
      <input
        className="mb-2 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent"
        placeholder="Mission title"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
      />
      <textarea
        className="min-h-24 w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent"
        placeholder="Broad direction. Example: triage the issue queue and propose the first useful PR."
        value={directive}
        onChange={(event) => setDirective(event.target.value)}
      />
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Bot</div>
          <BotPicker value={effectiveBotId} onChange={setBotId} bots={botList} />
        </div>
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Scope</div>
          <div className="grid grid-cols-2 gap-1 rounded-md bg-surface-overlay/45 p-1">
            {(["workspace", "channel"] as MissionScope[]).map((value) => (
              <button
                key={value}
                type="button"
                className={`rounded px-2 py-1.5 text-xs ${scope === value ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay hover:text-text"}`}
                onClick={() => setScope(value)}
              >
                {value}
              </button>
            ))}
          </div>
        </div>
      </div>
      {scope === "channel" && (
        <div className="mt-2">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">Channel</div>
          <ChannelPicker value={channelId} onChange={setChannelId} channels={channelList} bots={botList} />
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {[
          ["", "Manual"],
          ["+1h", "Hourly"],
          ["+4h", "Every few hours"],
          ["+1d", "Daily"],
        ].map(([value, label]) => (
          <button
            key={label}
            type="button"
            className={`rounded-md px-2 py-1.5 text-xs ${recurrence === value ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay hover:text-text"}`}
            onClick={() => setRecurrence(value)}
          >
            {label}
          </button>
        ))}
        <input
          className="h-8 w-20 rounded-md border border-input-border bg-input px-2 text-xs text-text outline-none placeholder:text-text-dim focus:border-accent"
          placeholder="+6h"
          value={recurrence}
          onChange={(event) => setRecurrence(event.target.value)}
        />
      </div>
      <button
        type="button"
        className="mt-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text"
        onClick={() => setAdvanced((value) => !value)}
      >
        <Settings2 size={13} />
        Advanced model
      </button>
      {advanced && (
        <div className="mt-2 space-y-2">
          {harnessRuntime ? (
            <HarnessMissionControls
              runtimeLabel={harnessCaps?.display_name ?? harnessRuntime}
              model={model}
              onModelChange={setModel}
              modelOptions={harnessModelOptions}
              models={harnessModels}
              modelIsFreeform={harnessCaps?.model_is_freeform ?? false}
              effort={harnessEffort}
              onEffortChange={setHarnessEffort}
              effortValues={harnessEffortValues}
            />
          ) : (
            <LlmModelDropdown
              value={model}
              selectedProviderId={providerId}
              allowClear
              placeholder="Bot default model"
              onChange={(nextModel, nextProvider) => {
                setModel(nextModel);
                setProviderId(nextProvider ?? null);
              }}
            />
          )}
        </div>
      )}
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          disabled={!title.trim() || !directive.trim() || !effectiveBotId || create.isPending || (scope === "channel" && !channelId)}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.08] disabled:cursor-not-allowed disabled:text-text-dim"
          onClick={submit}
        >
          <Zap size={14} />
          Start mission
        </button>
      </div>
    </section>
  );
}

function HarnessMissionControls({
  runtimeLabel,
  model,
  onModelChange,
  modelOptions,
  models,
  modelIsFreeform,
  effort,
  onEffortChange,
  effortValues,
}: {
  runtimeLabel: string;
  model: string;
  onModelChange: (value: string) => void;
  modelOptions: Array<{ id: string; label?: string | null; effort_values: string[]; default_effort?: string | null }>;
  models: string[];
  modelIsFreeform: boolean;
  effort: string;
  onEffortChange: (value: string) => void;
  effortValues: string[];
}) {
  const modelLabel = (id: string) => modelOptions.find((option) => option.id === id)?.label ?? id;
  const optionIds = Array.from(new Set([...(model ? [model] : []), ...models]));
  return (
    <div className="rounded-md border border-surface-border bg-surface-overlay/30 p-2">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">
        {runtimeLabel} harness
      </div>
      {modelIsFreeform ? (
        <input
          className="h-9 w-full rounded-md border border-input-border bg-input px-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent"
          placeholder="Harness default model"
          value={model}
          onChange={(event) => onModelChange(event.target.value)}
        />
      ) : (
        <select
          className="h-9 w-full rounded-md border border-input-border bg-input px-2 text-sm text-text outline-none focus:border-accent"
          value={model}
          onChange={(event) => onModelChange(event.target.value)}
        >
          <option value="">Harness default model</option>
          {optionIds.map((id) => (
            <option key={id} value={id}>{modelLabel(id)}</option>
          ))}
        </select>
      )}
      <select
        className="mt-2 h-9 w-full rounded-md border border-input-border bg-input px-2 text-sm text-text outline-none focus:border-accent disabled:opacity-60"
        value={effort}
        disabled={!effortValues.length}
        onChange={(event) => onEffortChange(event.target.value)}
      >
        <option value="">Harness default effort</option>
        {effortValues.map((value) => (
          <option key={value} value={value}>{value}</option>
        ))}
      </select>
    </div>
  );
}

function BotLanes({ missions, onSelect }: { missions: WorkspaceMission[]; onSelect: (id: string) => void }) {
  const lanes = useMemo(() => {
    const map = new Map<string, { botName: string; runtime?: string | null; missions: WorkspaceMission[] }>();
    for (const mission of missions) {
      for (const assignment of mission.assignments) {
        const lane = map.get(assignment.bot_id) ?? { botName: assignment.bot_name, runtime: assignment.harness_runtime, missions: [] };
        if (!lane.missions.some((item) => item.id === mission.id)) lane.missions.push(mission);
        map.set(assignment.bot_id, lane);
      }
    }
    return Array.from(map.entries()).sort((a, b) => a[1].botName.localeCompare(b[1].botName));
  }, [missions]);
  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Bot Lanes</div>
        <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{lanes.length}</span>
      </div>
      <div className="grid gap-2">
        {lanes.map(([botId, lane]) => (
          <div key={botId} className="rounded-md bg-surface-raised/45 px-3 py-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/[0.1] text-accent"><Bot size={15} /></span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-text">{lane.botName}</span>
                  <span className="block truncate text-xs text-text-dim">{lane.runtime ? `${lane.runtime} harness` : "Bot"}</span>
                </span>
              </div>
              <span className="shrink-0 rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{lane.missions.length} missions</span>
            </div>
            <div className="space-y-1">
              {lane.missions.map((mission) => (
                <MissionListRow key={mission.id} mission={mission} onSelect={() => onSelect(mission.id)} />
              ))}
            </div>
          </div>
        ))}
        {!lanes.length && (
          <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-3 py-6 text-center text-sm text-text-dim">
            No active missions yet.
          </div>
        )}
      </div>
    </section>
  );
}

function MissionListRow({ mission, onSelect }: { mission: WorkspaceMission; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 rounded-md px-3 py-2 text-left hover:bg-surface-overlay/55">
      <Route size={15} className="mt-0.5 shrink-0 text-accent" />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-text">{mission.title}</span>
          <StatusBadge label={mission.status} variant={missionStatusVariant(mission.status)} />
        </span>
        <span className="mt-1 block truncate text-xs text-text-dim">
          {mission.channel_name ? `#${mission.channel_name}` : "workspace"} · {recurrenceLabel(mission.recurrence)} · next {formatRelative(mission.next_run_at)}
        </span>
      </span>
    </button>
  );
}

function MissionUpdateRow({ mission, update, onSelect }: { mission: WorkspaceMission; update: WorkspaceMissionUpdate; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 rounded-md bg-surface-raised/35 px-3 py-2 text-left hover:bg-surface-overlay/45">
      <span className="mt-0.5">{updateIcon(update.kind)}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text">{mission.title}</span>
        <span className="mt-1 line-clamp-2 text-xs text-text-muted">{update.summary}</span>
        <span className="mt-1 block truncate text-[11px] text-text-dim">
          {update.bot_name ?? "system"} · {formatRelative(update.created_at)}
        </span>
      </span>
    </button>
  );
}

function MissionDetail({ mission, onBack }: { mission: WorkspaceMission; onBack: () => void }) {
  const runNow = useRunWorkspaceMissionNow();
  const setStatus = useSetWorkspaceMissionStatus();
  const latest = mission.updates[0];
  return (
    <div>
      <button type="button" className="mb-3 rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text" onClick={onBack}>
        Back
      </button>
      <section className="rounded-md bg-surface-raised/45 p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-semibold text-text">{mission.title}</h2>
              <StatusBadge label={mission.status} variant={missionStatusVariant(mission.status)} />
            </div>
            <div className="mt-1 text-xs text-text-dim">
              {mission.channel_name ? `#${mission.channel_name}` : "workspace"} · {recurrenceLabel(mission.recurrence)} · next {formatRelative(mission.next_run_at)}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text"
              title="Run now"
              onClick={() => runNow.mutate(mission.id)}
            >
              <Play size={15} />
            </button>
            <button
              type="button"
              className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text"
              title={mission.status === "paused" ? "Resume" : "Pause"}
              onClick={() => setStatus.mutate({ missionId: mission.id, status: mission.status === "paused" ? "active" : "paused" })}
            >
              {mission.status === "paused" ? <Activity size={15} /> : <Pause size={15} />}
            </button>
          </div>
        </div>
        <p className="mt-3 whitespace-pre-wrap text-sm text-text-muted">{mission.directive}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {mission.assignments.map((assignment) => (
            <span key={assignment.id} className="inline-flex items-center gap-1.5 rounded-full bg-surface-overlay px-2 py-1 text-xs text-text-muted">
              <Bot size={12} />
              {assignment.bot_name}
            </span>
          ))}
          {mission.last_task_id && (
            <a href={`/admin/tasks/${mission.last_task_id}`} className="inline-flex items-center gap-1.5 rounded-full bg-surface-overlay px-2 py-1 text-xs text-text-muted hover:text-text">
              <ListChecks size={12} />
              task
            </a>
          )}
          {mission.last_correlation_id && (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-full bg-surface-overlay px-2 py-1 text-xs text-text-muted hover:text-text"
              onClick={() => openTraceInspector({ correlationId: mission.last_correlation_id!, title: mission.title })}
            >
              <ExternalLink size={12} />
              trace
            </button>
          )}
        </div>
      </section>

      {latest?.next_actions?.length ? (
        <section className="mt-4">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Next Actions</div>
          <div className="space-y-1">
            {latest.next_actions.map((action, index) => (
              <div key={`${action}-${index}`} className="flex items-center gap-2 rounded-md bg-surface-raised/35 px-3 py-2 text-sm text-text-muted">
                <CheckCircle2 size={14} className="shrink-0 text-success" />
                <span className="min-w-0 flex-1">{action}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="mt-4">
        <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <Clock size={13} />
          Mission Log
        </div>
        <div className="space-y-1">
          {mission.updates.map((update) => (
            <div key={update.id} className="rounded-md bg-surface-raised/35 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2 text-xs text-text-dim">
                  {updateIcon(update.kind)}
                  <span className="truncate">{update.kind}</span>
                  {update.bot_name && <span className="truncate">· {update.bot_name}</span>}
                </div>
                <span className="shrink-0 text-xs tabular-nums text-text-dim">{formatRelative(update.created_at)}</span>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-text-muted">{update.summary}</p>
              {update.correlation_id && (
                <button
                  type="button"
                  className="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text"
                  onClick={() => openTraceInspector({ correlationId: update.correlation_id!, title: mission.title })}
                >
                  <ExternalLink size={12} />
                  Trace
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
