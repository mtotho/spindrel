import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, AlertTriangle, Bot, CheckCircle2, ClipboardCheck, Clock, ExternalLink, ListChecks, Loader2, MessageSquare, Pause, Pencil, Play, Plus, Radar, Route, Send, Settings2, ShieldCheck, Sparkles, X, Zap } from "lucide-react";

import { useBots } from "../../api/hooks/useBots";
import { useChannels } from "../../api/hooks/useChannels";
import {
  useCreateWorkspaceMission,
  useRunWorkspaceMissionNow,
  useSetWorkspaceMissionStatus,
  type MissionCreateInput,
  type MissionScope,
  type WorkspaceMission,
  type WorkspaceMissionUpdate,
} from "../../api/hooks/useWorkspaceMissions";
import {
  useAcceptMissionControlDraft,
  useAskMissionControlAi,
  useDismissMissionControlDraft,
  useMissionControl,
  useRefreshMissionControlAi,
  useUpdateMissionControlDraft,
  type MissionControlAssistantBrief,
  type MissionControlDraft,
  type MissionControlLane,
  type MissionControlMissionRow,
  type MissionControlResponse,
  type MissionControlSpatialAdvisory,
} from "../../api/hooks/useMissionControl";
import { BotPicker } from "../shared/BotPicker";
import { ChannelPicker } from "../shared/ChannelPicker";
import { LlmModelDropdown } from "../shared/LlmModelDropdown";
import { StatusBadge } from "../shared/SettingsControls";
import { openTraceInspector } from "../../stores/traceInspector";
import { useRuntimeCapabilities } from "../../api/hooks/useRuntimes";
import { attentionDeckHref } from "../../lib/hubRoutes";

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

function mutationErrorMessage(error: unknown): string | null {
  if (!error) return null;
  const detail = typeof error === "object" && error !== null && "detail" in error
    ? (error as { detail?: unknown }).detail
    : null;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (error instanceof Error) return error.message;
  return "The request failed.";
}

function missionStatusVariant(status: WorkspaceMission["status"]): "success" | "warning" | "info" {
  if (status === "active") return "success";
  if (status === "paused") return "warning";
  return "info";
}

function readinessVariant(status: MissionControlSpatialAdvisory["status"]): "success" | "warning" | "danger" | "info" {
  if (status === "ready") return "success";
  if (status === "far") return "warning";
  if (status === "blocked") return "danger";
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
  initialItemId = null,
}: {
  embedded?: boolean;
  initialItemId?: string | null;
}) {
  const { data, isLoading, isError } = useMissionControl();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState<MissionControlDraft | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  useEffect(() => {
    if (initialItemId) setSelectedId(initialItemId);
  }, [initialItemId]);
  const selectedRow = useMemo(() => {
    if (!data || !selectedId) return null;
    return data.lanes.flatMap((lane) => lane.missions).find((row) => row.mission.id === selectedId) ?? null;
  }, [data, selectedId]);
  const selected = selectedRow?.mission ?? data?.missions.find((mission) => mission.id === selectedId) ?? null;
  const activeCount = data?.summary.active_missions ?? 0;
  const pausedCount = data?.summary.paused_missions ?? 0;
  const updateCount = data?.summary.recent_updates ?? 0;

  if (isLoading) {
    return <div className="p-4 text-sm text-text-dim">Loading Mission Control...</div>;
  }
  if (isError || !data) {
    return <div className="p-4 text-sm text-text-muted">Mission Control is unavailable.</div>;
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${embedded ? "" : "h-full"}`}>
      {!embedded && (
        <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-dim/80">
              <Radar size={14} />
              Mission Control
            </div>
            <div className="mt-1 text-xs text-text-muted">
              {activeCount} active · {pausedCount} paused · {data.summary.active_bots} bots · {data.summary.spatial_warnings} spatial warnings · {updateCount} recent updates
            </div>
          </div>
        </div>
      )}

      <div className={`min-h-0 flex-1 overflow-auto pb-4 ${embedded ? "px-1" : "px-3"}`}>
        {selected ? (
          <MissionDetail mission={selected} row={selectedRow} onBack={() => setSelectedId(null)} />
        ) : (
          <>
            <OperatorBrief brief={data.assistant_brief ?? null} summary={data.summary} embedded={embedded} />
            <AskMissionControl />
            <OperatorOpportunityStack data={data} onManualMission={() => setManualOpen(true)} />
            <DraftStack
              drafts={data.drafts}
              onEdit={(draft) => {
                setManualOpen(false);
                setEditingDraft(draft);
              }}
            />
            <div className="mb-5">
              {editingDraft ? (
                <MissionEditor draft={editingDraft} onClose={() => setEditingDraft(null)} />
              ) : manualOpen ? (
                <MissionEditor onClose={() => setManualOpen(false)} />
              ) : (
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text"
                  onClick={() => setManualOpen(true)}
                >
                  <Plus size={13} />
                  Manual mission
                </button>
              )}
            </div>
            <BotLanes lanes={data.lanes} onSelect={setSelectedId} />
            <section className="mt-5">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Mission Updates</div>
                <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{updateCount}</span>
              </div>
              <div className="space-y-1">
                {data.recent_updates.slice(0, 10).map(({ mission_id, mission_title, update }) => (
                  <MissionUpdateRow key={update.id} missionTitle={mission_title} update={update} onSelect={() => setSelectedId(mission_id)} />
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

function OperatorBrief({
  brief,
  summary,
  embedded = false,
}: {
  brief: MissionControlAssistantBrief | null;
  embedded?: boolean;
  summary: {
    active_missions: number;
    paused_missions: number;
    active_bots: number;
    attention_signals: number;
    assigned_attention: number;
    spatial_warnings: number;
    recent_updates: number;
  };
}) {
  const refresh = useRefreshMissionControlAi();
  const refreshError = mutationErrorMessage(refresh.error);
  const lastRun = brief?.created_at ? formatRelative(brief.created_at) : null;
  return (
    <section className={`mb-3 ${embedded ? "pb-2" : "border-b border-surface-border/70 pb-4"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Sparkles size={13} />
            Operator Brief
          </div>
          {brief ? (
            <>
              <p className={`mt-1.5 font-semibold text-text ${embedded ? "text-sm leading-5" : "text-[15px] leading-6"}`}>{brief.summary}</p>
              {brief.next_focus && <p className={`mt-1.5 text-text-muted ${embedded ? "text-xs leading-5" : "text-sm leading-6"}`}>{brief.next_focus}</p>}
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-text-dim">
                <StatusBadge label={`${brief.confidence} confidence`} variant={brief.confidence === "high" ? "success" : brief.confidence === "low" ? "warning" : "info"} />
                {brief.ai_model && <span className="rounded-full bg-surface-overlay px-2 py-0.5">{brief.ai_model}</span>}
                {lastRun && <span>{lastRun}</span>}
              </div>
            </>
          ) : (
            <>
              <p className={`mt-1.5 font-semibold text-text ${embedded ? "text-sm leading-5" : "text-[15px] leading-6"}`}>Generate a brief from live workspace signals.</p>
              <p className={`mt-1.5 text-text-muted ${embedded ? "text-xs leading-5" : "text-sm leading-6"}`}>
                Mission Control will inspect missions, tasks, channels, bots, and map readiness before drafting next moves.
              </p>
            </>
          )}
        </div>
        <button
          type="button"
          disabled={refresh.isPending}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08] disabled:cursor-wait disabled:text-text-dim"
          onClick={() => refresh.mutate(undefined)}
        >
          {refresh.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          Refresh
        </button>
      </div>
      {embedded ? (
        <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-text-muted">
          <span className="rounded-full bg-surface-overlay/45 px-2 py-0.5">{summary.active_missions}/{summary.paused_missions} missions</span>
          <span className="rounded-full bg-surface-overlay/45 px-2 py-0.5">{summary.active_bots} bots</span>
          <span className="rounded-full bg-surface-overlay/45 px-2 py-0.5">{summary.spatial_warnings} spatial</span>
          <span className="rounded-full bg-surface-overlay/45 px-2 py-0.5">{summary.recent_updates} updates</span>
        </div>
      ) : (
        <div className="mt-4 grid grid-cols-4 gap-2 text-xs">
          <BriefMetric label="Missions" value={`${summary.active_missions}/${summary.paused_missions}`} />
          <BriefMetric label="Bots" value={summary.active_bots} />
          <BriefMetric label="Spatial" value={summary.spatial_warnings} />
          <BriefMetric label="Updates" value={summary.recent_updates} />
        </div>
      )}
      {refreshError && (
        <div className="mt-3 rounded-md bg-danger/10 px-3 py-2 text-xs leading-5 text-danger">
          {refreshError}
        </div>
      )}
    </section>
  );
}

function BriefMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-surface-border/70 bg-surface-raised/30 px-2 py-2">
      <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim">{label}</div>
      <div className="mt-1 text-sm font-semibold tabular-nums text-text">{value}</div>
    </div>
  );
}

function AskMissionControl() {
  const ask = useAskMissionControlAi();
  const [instruction, setInstruction] = useState("");
  const submit = () => {
    const clean = instruction.trim();
    if (!clean || ask.isPending) return;
    ask.mutate(clean, { onSuccess: () => setInstruction("") });
  };
  return (
    <section className="mb-4">
      <div className="flex items-center gap-2 rounded-md border border-input-border bg-input px-2 py-2 focus-within:border-accent">
        <MessageSquare size={15} className="shrink-0 text-text-dim" />
        <input
          className="min-w-0 flex-1 bg-transparent text-sm text-text outline-none placeholder:text-text-dim"
          placeholder="Ask Mission Control to inspect or stage next work..."
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit();
          }}
        />
        <button
          type="button"
          disabled={!instruction.trim() || ask.isPending}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-accent hover:bg-accent/[0.08] disabled:cursor-not-allowed disabled:text-text-dim"
          title="Ask Mission Control"
          onClick={submit}
        >
          {ask.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
        </button>
      </div>
    </section>
  );
}

function OperatorOpportunityStack({
  data,
  onManualMission,
}: {
  data: MissionControlResponse;
  onManualMission: () => void;
}) {
  const navigate = useNavigate();
  const ask = useAskMissionControlAi();
  const refresh = useRefreshMissionControlAi();
  const refreshError = mutationErrorMessage(refresh.error);
  const cards: Array<{
    id: string;
    title: string;
    detected: string;
    missing: string;
    staged: string;
    action: string;
    icon: typeof Radar;
    onSelect: () => void;
    busy?: boolean;
  }> = [];

  if (!data.assistant_brief && data.drafts.length === 0) {
    cards.push({
      id: "operator-inspection",
      title: "Run an operator inspection",
      detected: "No current brief or staged next moves.",
      missing: "A grounded read of missions, bots, channels, recent runs, and map readiness.",
      staged: "Brief plus reviewable mission drafts. Nothing durable is created until you approve a draft.",
      action: "Inspect workspace",
      icon: Sparkles,
      onSelect: () => refresh.mutate("Inspect the workspace and stage only concrete, approval-ready next moves."),
      busy: refresh.isPending,
    });
  }

  if (data.unassigned_attention.length > 0) {
    cards.push({
      id: "triage-attention",
      title: "Review attention signals",
      detected: `${data.unassigned_attention.length} raw signal${data.unassigned_attention.length === 1 ? "" : "s"} ready for Operator sweep.`,
      missing: "Operator classification and review status.",
      staged: "Mission Control Review shows raw signals, Operator findings, and run receipts.",
      action: "Open review queue",
      icon: AlertTriangle,
      onSelect: () => navigate(attentionDeckHref({ mode: "inbox" })),
    });
  }

  if (data.summary.spatial_warnings > 0) {
    cards.push({
      id: "spatial-readiness",
      title: "Resolve map readiness",
      detected: `${data.summary.spatial_warnings} mission lane${data.summary.spatial_warnings === 1 ? "" : "s"} with spatial readiness warnings.`,
      missing: "A clear target, nearby bot posture, or explicit decision to ignore proximity.",
      staged: "Drafted move/inspection plan or a mission edit that makes the warning visible before the next run.",
      action: "Inspect warnings",
      icon: Radar,
      onSelect: () => ask.mutate("Inspect spatial readiness warnings. Stage concrete fixes or mission edits, and keep position advisory rather than blocking work."),
      busy: ask.isPending,
    });
  }

  if (data.summary.active_missions === 0 && data.summary.active_bots > 0) {
    cards.push({
      id: "first-operating-rhythm",
      title: "Start an operating rhythm",
      detected: `${data.summary.active_bots} bot${data.summary.active_bots === 1 ? "" : "s"} available and no active missions.`,
      missing: "One bounded responsibility that should recur or run on demand.",
      staged: "A task-backed mission draft tied to a bot and room, ready for approval.",
      action: "Stage first mission",
      icon: ClipboardCheck,
      onSelect: onManualMission,
    });
  }

  if (!cards.length) return null;

  return (
    <section className="mb-4">
      {refreshError && (
        <div className="mb-3 rounded-md bg-danger/10 px-3 py-2 text-xs leading-5 text-danger">
          {refreshError}
        </div>
      )}
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <ShieldCheck size={13} />
          Operator Opportunities
        </div>
        <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{cards.length}</span>
      </div>
      <div className="grid gap-2">
        {cards.slice(0, 3).map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.id} className="rounded-md bg-surface-raised/35 px-2.5 py-2.5">
              <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2.5">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
                  <Icon size={15} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold leading-5 text-text">{card.title}</div>
                  <div className="mt-0.5 text-xs leading-5 text-text-muted">
                    <span className="text-text-dim">Detected:</span> {card.detected}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] leading-4 text-text-muted">
                    <span className="rounded-full bg-surface-overlay/45 px-2 py-0.5">
                      Missing: {card.missing}
                    </span>
                    <span className="rounded-full bg-surface-overlay/45 px-2 py-0.5">
                      Will stage: {card.staged}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  disabled={card.busy}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08] disabled:cursor-wait disabled:text-text-dim"
                  onClick={card.onSelect}
                >
                  {card.busy ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
                  {card.action}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function DraftStack({ drafts, onEdit }: { drafts: MissionControlDraft[]; onEdit: (draft: MissionControlDraft) => void }) {
  const accept = useAcceptMissionControlDraft();
  const dismiss = useDismissMissionControlDraft();
  const refresh = useRefreshMissionControlAi();
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Suggested Next Moves</div>
        <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{drafts.length}</span>
      </div>
      <div className="overflow-hidden rounded-md border border-surface-border/70">
        {drafts.map((draft) => (
          <div key={draft.id} className="border-t border-surface-border/60 px-3 py-3 first:border-t-0">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-semibold text-text">{draft.title}</span>
                  <StatusBadge label={recurrenceLabel(draft.recurrence)} variant="info" />
                </div>
                {draft.rationale && <p className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{draft.rationale}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-text-dim">
                  <span>{draft.bot_name ?? "best available bot"}</span>
                  <span>·</span>
                  <span>{draft.target_channel_name ? `#${draft.target_channel_name}` : draft.scope}</span>
                  {draft.ai_model && (
                    <>
                      <span>·</span>
                      <span>{draft.ai_model}</span>
                    </>
                  )}
                </div>
                <div className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-surface-overlay/45 px-2 py-1 text-[11px] text-text-muted">
                  <ShieldCheck size={12} />
                  Approval creates a task-backed mission; dismissing does not start work.
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text"
                  title="Edit draft"
                  onClick={() => onEdit(draft)}
                >
                  <Pencil size={14} />
                </button>
                <button
                  type="button"
                  disabled={accept.isPending}
                  className="rounded-md p-2 text-accent hover:bg-accent/[0.08] disabled:cursor-wait disabled:text-text-dim"
                  title="Start mission"
                  onClick={() => accept.mutate(draft.id)}
                >
                  <Zap size={14} />
                </button>
                <button
                  type="button"
                  disabled={dismiss.isPending}
                  className="rounded-md p-2 text-text-dim hover:bg-surface-overlay hover:text-text"
                  title="Dismiss"
                  onClick={() => dismiss.mutate(draft.id)}
                >
                  <X size={14} />
                </button>
              </div>
            </div>
          </div>
        ))}
        {!drafts.length && (
          <div className="px-3 py-5 text-sm text-text-muted">
            <div className="font-medium text-text">No AI drafts yet.</div>
            <div className="mt-1 text-xs leading-5 text-text-dim">Refresh the brief or ask Mission Control for a specific sweep.</div>
            <button
              type="button"
              disabled={refresh.isPending}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08] disabled:cursor-wait disabled:text-text-dim"
              onClick={() => refresh.mutate(undefined)}
            >
              {refresh.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              Draft suggestions
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function MissionEditor({ draft, onClose }: { draft?: MissionControlDraft | null; onClose: () => void }) {
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const create = useCreateWorkspaceMission();
  const updateDraft = useUpdateMissionControlDraft();
  const acceptDraft = useAcceptMissionControlDraft();
  const [title, setTitle] = useState("");
  const [directive, setDirective] = useState("");
  const [rationale, setRationale] = useState("");
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
    if (!draft) {
      setTitle("");
      setDirective("");
      setRationale("");
      setScope("workspace");
      setBotId("");
      setChannelId("");
      setRecurrence("+4h");
      setModel("");
      setProviderId(null);
      setHarnessEffort("");
      return;
    }
    setTitle(draft.title);
    setDirective(draft.directive);
    setRationale(draft.rationale ?? "");
    setScope(draft.scope);
    setBotId(draft.bot_id ?? "");
    setChannelId(draft.target_channel_id ?? "");
    setRecurrence(draft.recurrence ?? "");
    setModel(draft.model_override ?? "");
    setProviderId(draft.model_provider_id_override ?? null);
    setHarnessEffort(draft.harness_effort ?? "");
  }, [draft?.id]);

  useEffect(() => {
    if (draft) return;
    setModel("");
    setProviderId(null);
    setHarnessEffort("");
  }, [draft, effectiveBotId]);

  useEffect(() => {
    if (!harnessEffort || !harnessEffortValues.length) return;
    if (!harnessEffortValues.includes(harnessEffort)) {
      setHarnessEffort("");
    }
  }, [harnessEffort, harnessEffortValues]);

  const submit = async () => {
    const cleanTitle = title.trim();
    const cleanDirective = directive.trim();
    if (!cleanTitle || !cleanDirective || !effectiveBotId) return;
    const body: MissionCreateInput = {
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
    };
    if (draft) {
      await updateDraft.mutateAsync({
        draftId: draft.id,
        patch: {
          title: cleanTitle,
          directive: cleanDirective,
          rationale: rationale.trim() || null,
          scope,
          bot_id: effectiveBotId,
          target_channel_id: scope === "channel" ? channelId || null : null,
          interval_kind: body.interval_kind,
          recurrence: body.recurrence,
          model_override: body.model_override,
          model_provider_id_override: body.model_provider_id_override,
          harness_effort: body.harness_effort,
        },
      });
      await acceptDraft.mutateAsync(draft.id);
      onClose();
      return;
    }
    create.mutate(body, {
      onSuccess: onClose,
    });
  };
  const busy = create.isPending || updateDraft.isPending || acceptDraft.isPending;

  return (
    <section className="rounded-md border border-surface-border/80 bg-surface-raised/35 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-text">{draft ? "Review draft" : "Manual mission"}</div>
          {draft?.rationale && <div className="mt-0.5 line-clamp-1 text-xs text-text-dim">{draft.rationale}</div>}
        </div>
        <button type="button" className="rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text" onClick={onClose}>
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
      {draft && (
        <textarea
          className="mt-2 min-h-16 w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent"
          placeholder="Why this is worth doing"
          value={rationale}
          onChange={(event) => setRationale(event.target.value)}
        />
      )}
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
          disabled={!title.trim() || !directive.trim() || !effectiveBotId || busy || (scope === "channel" && !channelId)}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.08] disabled:cursor-not-allowed disabled:text-text-dim"
          onClick={submit}
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
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

function BotLanes({ lanes, onSelect }: { lanes: MissionControlLane[]; onSelect: (id: string) => void }) {
  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Bot Lanes</div>
        <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{lanes.length}</span>
      </div>
      <div className="grid gap-2">
        {lanes.map((lane) => (
          <div key={lane.bot_id} className="rounded-md bg-surface-raised/45 px-3 py-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/[0.1] text-accent"><Bot size={15} /></span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-text">{lane.bot_name}</span>
                  <span className="block truncate text-xs text-text-dim">
                    {lane.harness_runtime ? `${lane.harness_runtime} harness` : "Bot"}
                    {lane.bot_node ? ` · map ${Math.round(lane.bot_node.world_x)}, ${Math.round(lane.bot_node.world_y)}` : " · no map node"}
                    {lane.nearest_objects[0] ? ` · near ${lane.nearest_objects[0].label}` : ""}
                  </span>
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {lane.warning_count > 0 && <StatusBadge label={`${lane.warning_count} warnings`} variant="warning" />}
                <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-xs text-text-muted">{lane.missions.length} missions</span>
              </div>
            </div>
            <div className="space-y-1">
              {lane.missions.map((row) => (
                <MissionListRow key={`${row.mission.id}-${row.assignment.id}`} row={row} onSelect={() => onSelect(row.mission.id)} />
              ))}
              {lane.attention_signals.map((signal) => (
                <button key={signal.id} type="button" className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-surface-overlay/55">
                  <Radar size={15} className="shrink-0 text-warning" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-text">{signal.title}</span>
                    <span className="mt-1 block truncate text-xs text-text-dim">
                      attention · {signal.channel_name ? `#${signal.channel_name}` : "workspace"} · {signal.assignment_status ?? signal.status}
                    </span>
                  </span>
                  <StatusBadge label={signal.severity} variant={signal.severity === "critical" || signal.severity === "error" ? "danger" : "warning"} />
                </button>
              ))}
            </div>
          </div>
        ))}
        {!lanes.length && (
          <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-3 py-6 text-center text-sm text-text-dim">
            No active mission lanes yet. Ask Mission Control to inspect the workspace or stage one bounded mission.
          </div>
        )}
      </div>
    </section>
  );
}

function MissionListRow({ row, onSelect }: { row: MissionControlMissionRow; onSelect: () => void }) {
  const mission = row.mission;
  const readiness = row.spatial_advisory;
  return (
    <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 rounded-md px-3 py-2 text-left hover:bg-surface-overlay/55">
      <Route size={15} className="mt-0.5 shrink-0 text-accent" />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-text">{mission.title}</span>
          <StatusBadge label={mission.status} variant={missionStatusVariant(mission.status)} />
          <StatusBadge label={readiness.status} variant={readinessVariant(readiness.status)} />
        </span>
        <span className="mt-1 block truncate text-xs text-text-dim">
          {mission.channel_name ? `#${mission.channel_name}` : "workspace"} · target {readiness.target_channel_name ? `#${readiness.target_channel_name}` : "unknown"} · next {formatRelative(mission.next_run_at)}
        </span>
      </span>
    </button>
  );
}

function MissionUpdateRow({ missionTitle, update, onSelect }: { missionTitle: string; update: WorkspaceMissionUpdate; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 rounded-md bg-surface-raised/35 px-3 py-2 text-left hover:bg-surface-overlay/45">
      <span className="mt-0.5">{updateIcon(update.kind)}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text">{missionTitle}</span>
        <span className="mt-1 line-clamp-2 text-xs text-text-muted">{update.summary}</span>
        <span className="mt-1 block truncate text-[11px] text-text-dim">
          {update.bot_name ?? "system"} · {formatRelative(update.created_at)}
        </span>
      </span>
    </button>
  );
}

function MissionDetail({ mission, row, onBack }: { mission: WorkspaceMission; row?: MissionControlMissionRow | null; onBack: () => void }) {
  const runNow = useRunWorkspaceMissionNow();
  const setStatus = useSetWorkspaceMissionStatus();
  const latest = mission.updates[0];
  const spatial = row?.spatial_advisory;
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

      {spatial && (
        <section className="mt-4 rounded-md bg-surface-raised/35 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
              <Radar size={13} />
              Spatial Readiness
            </div>
            <StatusBadge label={spatial.status} variant={readinessVariant(spatial.status)} />
          </div>
          <p className="text-sm text-text-muted">{spatial.reason}</p>
          <div className="mt-3 grid gap-2 text-xs text-text-dim sm:grid-cols-2">
            <div className="rounded-md bg-surface-overlay/35 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Target</div>
              <div className="mt-1 truncate text-text">{spatial.target_channel_name ? `#${spatial.target_channel_name}` : "Unknown target"}</div>
            </div>
            <div className="rounded-md bg-surface-overlay/35 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Distance</div>
              <div className="mt-1 text-text">
                {spatial.center_distance != null ? `${spatial.center_distance} center · ${spatial.edge_distance ?? 0} edge` : "No mapped distance"}
              </div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {spatial.bot_node_id && (
              <Link to={`/canvas?node=${encodeURIComponent(spatial.bot_node_id)}`} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text">
                <ExternalLink size={12} />
                Fly to bot
              </Link>
            )}
            {spatial.target_node_id && (
              <Link to={`/canvas?node=${encodeURIComponent(spatial.target_node_id)}`} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text">
                <ExternalLink size={12} />
                Fly to target
              </Link>
            )}
            {spatial.target_channel_id && (
              <Link to={`/channels/${encodeURIComponent(spatial.target_channel_id)}`} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay hover:text-text">
                <ExternalLink size={12} />
                Open channel
              </Link>
            )}
          </div>
        </section>
      )}

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
