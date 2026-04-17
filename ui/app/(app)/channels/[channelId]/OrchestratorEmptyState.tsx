import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Radar,
  Compass,
  Activity,
  ArrowRight,
  Loader2,
  ChevronDown,
  ChevronUp,
  X,
  Cog,
  Clock,
  CheckCircle2,
  AlertCircle,
  PauseCircle,
  Circle,
} from "lucide-react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { apiFetch } from "@/src/api/client";
import { useRunTaskNow, useTaskChildren } from "@/src/api/hooks/useTasks";
import type { StepState } from "@/src/api/hooks/useTasks";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannelPipelines, type ChannelPipelineSubscription } from "@/src/api/hooks/useChannelPipelines";
import { useFindings } from "./FindingsPanel";
import { BotPicker } from "@/src/components/shared/BotPicker";
import type { TasksResponse, TaskItem } from "@/src/components/shared/TaskConstants";
import { cn } from "@/src/lib/cn";

// ---------------------------------------------------------------------------
// Icon selection — pipeline-id prefix match. Falls back to Radar.
// ---------------------------------------------------------------------------

const PIPELINE_ICON: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  "orchestrator.full_scan": Radar,
  "orchestrator.deep_dive_bot": Compass,
  "orchestrator.analyze_discovery": Activity,
};

function iconFor(id: string) {
  return PIPELINE_ICON[id] ?? Radar;
}

/** Synthesize the TaskItem-ish shape used downstream (TaskRunModal, param
 *  schema lookup, getDescription) from a subscription's joined pipeline. */
function subscriptionToTaskItem(sub: ChannelPipelineSubscription): TaskItem {
  const p = sub.pipeline!;
  return {
    id: p.id,
    title: p.title ?? p.id,
    bot_id: p.bot_id,
    source: p.source,
    task_type: p.task_type,
    status: "active",
    prompt: "",
    dispatch_type: "none",
    run_count: 0,
    retry_count: 0,
    created_at: sub.created_at,
    execution_config: {
      description: p.description ?? undefined,
      featured: sub.featured,
      params_schema: p.params_schema ?? undefined,
      requires_channel: p.requires_channel ?? undefined,
      requires_bot: p.requires_bot ?? undefined,
    },
  } as unknown as TaskItem;
}

// ---------------------------------------------------------------------------
// Param schema + config helpers — read execution_config directly off the task.
// ---------------------------------------------------------------------------

interface ParamDef {
  name: string;
  required?: boolean;
  description?: string;
}

function getParamsSchema(task: TaskItem): ParamDef[] | null {
  const schema = (task as any).execution_config?.params_schema;
  if (Array.isArray(schema) && schema.length > 0) return schema as ParamDef[];
  return null;
}

function getFeatured(task: TaskItem): boolean {
  return !!(task as any).execution_config?.featured;
}

function getDescription(task: TaskItem): string | null {
  const d = (task as any).execution_config?.description;
  return typeof d === "string" && d.trim() ? d.trim() : null;
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!then) return "";
  const diffMs = Date.now() - then;
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

// ---------------------------------------------------------------------------
// Param-picker modal (pipelines declaring params_schema)
// ---------------------------------------------------------------------------

function TaskRunModal({
  pipeline,
  onClose,
  onLaunch,
  running,
}: {
  pipeline: TaskItem;
  onClose: () => void;
  onLaunch: (params: Record<string, any>) => void;
  running: boolean;
}) {
  const schema = getParamsSchema(pipeline) ?? [];
  const [values, setValues] = useState<Record<string, any>>({});
  const { data: bots = [] } = useBots();

  const canLaunch = useMemo(() => {
    return schema.every((p) => {
      if (!p.required) return true;
      const v = values[p.name];
      return v !== undefined && v !== null && v !== "";
    });
  }, [schema, values]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        onClick={running ? undefined : onClose}
        className="fixed inset-0 bg-black/45 z-[10020]"
      />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                   w-[440px] max-w-[92vw] z-[10021]
                   bg-surface-raised border border-surface-border rounded-xl
                   shadow-[0_16px_48px_rgba(0,0,0,0.3)] p-5"
      >
        <div className="flex flex-row items-center justify-between mb-3">
          <div className="flex flex-row items-center gap-2 min-w-0">
            <Cog size={14} className="text-accent shrink-0" />
            <span className="text-sm font-semibold truncate">{pipeline.title}</span>
          </div>
          {!running && (
            <button onClick={onClose} className="p-1 text-text-dim hover:text-text">
              <X size={16} />
            </button>
          )}
        </div>

        {getDescription(pipeline) && (
          <p className="text-xs text-text-dim leading-relaxed mb-4">
            {getDescription(pipeline)}
          </p>
        )}

        <div className="flex flex-col gap-3 mb-5">
          {schema.map((param) => (
            <div key={param.name} className="flex flex-col gap-1">
              <label className="text-[11px] font-medium text-text-dim uppercase tracking-wider">
                {param.name}
                {param.required && <span className="text-accent ml-1">*</span>}
              </label>
              {param.name === "bot_id" ? (
                <BotPicker
                  value={values[param.name] ?? ""}
                  onChange={(v) => setValues({ ...values, [param.name]: v })}
                  bots={bots}
                  placeholder="Select a bot..."
                  disabled={running}
                />
              ) : (
                <input
                  type="text"
                  value={values[param.name] ?? ""}
                  onChange={(e) => setValues({ ...values, [param.name]: e.target.value })}
                  disabled={running}
                  placeholder={param.description}
                  className="px-2.5 py-1.5 text-sm bg-surface border border-surface-border
                             rounded-md focus:outline-none focus:border-accent/50
                             text-text placeholder:text-text-dim"
                />
              )}
              {param.description && (
                <span className="text-[10px] text-text-dim">{param.description}</span>
              )}
            </div>
          ))}
        </div>

        <div className="flex flex-row justify-end gap-2">
          <button
            onClick={onClose}
            disabled={running}
            className="px-3 py-1.5 text-xs rounded-md border border-surface-border
                       text-text-dim hover:text-text disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => onLaunch(values)}
            disabled={!canLaunch || running}
            className="px-3 py-1.5 text-xs rounded-md bg-accent text-white font-semibold
                       hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed
                       flex flex-row items-center gap-1.5"
          >
            {running ? <Loader2 size={12} className="animate-spin" /> : null}
            {running ? "Launching..." : "Launch"}
          </button>
        </div>
      </div>
    </>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Tile — compact enough to fit 2-3 across inside a strip.
// ---------------------------------------------------------------------------

function PipelineTile({
  pipeline,
  onLaunch,
  launchingId,
  onOpenFindings,
}: {
  pipeline: TaskItem;
  onLaunch: (pipeline: TaskItem) => void;
  launchingId: string | null;
  onOpenFindings: () => void;
}) {
  const { data: children } = useTaskChildren(pipeline.id, 5_000);
  const sortedChildren = (children ?? []).slice().sort(
    (a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  );
  // A child is "awaiting review" if any of its step_states is awaiting_user_input,
  // regardless of the outer status (the outer is "running" while paused).
  const awaitingChildren = sortedChildren.filter((c) =>
    ((c.step_states as StepState[] | null) ?? []).some(
      (s) => s?.status === "awaiting_user_input",
    ),
  );
  const awaitingCount = awaitingChildren.length;
  const activeChild = sortedChildren.find(
    (c) => c.status === "running" || c.status === "pending",
  );
  const lastRun = sortedChildren.map((c) => c.created_at).filter(Boolean)[0];

  const Icon = iconFor(pipeline.id);
  const description = getDescription(pipeline) ?? pipeline.prompt;
  const isLaunching = launchingId === pipeline.id;

  return (
    <div
      className={cn(
        "group relative flex flex-row items-center gap-3 px-3.5 py-3 rounded-lg",
        "bg-surface-raised/60 border border-surface-border",
        "hover:border-accent/40 hover:bg-surface-raised",
        "transition-colors",
      )}
      title={description || undefined}
    >
      <Icon size={16} className="text-accent shrink-0" />

      <div className="flex flex-col min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-text leading-tight truncate">
          {pipeline.title || pipeline.id}
        </h3>
        {/* Status sub-row — priority: awaiting > running > last-run chip (hover-only) */}
        {awaitingCount > 0 ? (
          <button
            onClick={onOpenFindings}
            className="inline-flex items-center gap-1 text-[11px] font-semibold
                       text-accent hover:underline self-start mt-0.5"
          >
            <PauseCircle size={11} className="animate-pulse" />
            {awaitingCount} awaiting review
          </button>
        ) : activeChild ? (
          <Link
            to={`/admin/tasks/${activeChild.id}`}
            className="inline-flex items-center gap-1 text-[11px] text-accent/80 hover:text-accent
                       font-medium self-start mt-0.5"
            onClick={(e) => e.stopPropagation()}
          >
            <Loader2 size={10} className="animate-spin" />
            Running · view
          </Link>
        ) : lastRun ? (
          <span
            className="text-[10px] text-text-dim inline-flex items-center gap-1 self-start mt-0.5
                       opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <Clock size={9} />
            Last run {relTime(lastRun)}
          </span>
        ) : null}
      </div>

      <button
        onClick={() => onLaunch(pipeline)}
        disabled={isLaunching}
        className={cn(
          "shrink-0 inline-flex items-center gap-1 text-[11px] font-medium",
          "px-2.5 py-1 rounded-md bg-accent/10 text-accent border border-accent/30",
          "hover:bg-accent/20 transition-colors",
          "disabled:opacity-60 disabled:cursor-not-allowed",
        )}
      >
        {isLaunching ? (
          <>
            <Loader2 size={11} className="animate-spin" />
            Launching
          </>
        ) : (
          <>
            {activeChild ? "Run again" : "Run"}
            <ArrowRight size={11} />
          </>
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main — always-visible collapsible strip that sits above the chat on system
// channels. Modelled on the HudStripBar vertical-stack pattern.
// ---------------------------------------------------------------------------

const COLLAPSED_STORAGE_KEY = "orchestrator-launchpad-collapsed";

// Stored preference is tri-state:
//   "1" → user explicitly collapsed (sticks even when activity returns)
//   "0" → user explicitly expanded (sticks across idle periods)
//   null → follow activity heuristic
function loadCollapsedPref(channelId: string): boolean | null {
  try {
    const raw = localStorage.getItem(`${COLLAPSED_STORAGE_KEY}:${channelId}`);
    if (raw === "1") return true;
    if (raw === "0") return false;
    return null;
  } catch {
    return null;
  }
}

function saveCollapsed(channelId: string, value: boolean) {
  try {
    localStorage.setItem(
      `${COLLAPSED_STORAGE_KEY}:${channelId}`,
      value ? "1" : "0",
    );
  } catch {
    // ignore
  }
}

export function OrchestratorLaunchpad({
  channelId,
  onOpenFindings,
}: {
  channelId: string;
  onOpenFindings: () => void;
}) {
  const runNowMut = useRunTaskNow();
  const { count: findingsCount } = useFindings(channelId);
  const [paramModalPipeline, setParamModalPipeline] = useState<TaskItem | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  // When the user has no explicit preference, follow activity: collapsed by
  // default, auto-expanded when findings are pending. We seed from findingsCount
  // only; running-state comes from per-tile polls and would cause thrash if we
  // included it in the default.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    const pref = loadCollapsedPref(channelId);
    if (pref !== null) return pref;
    return findingsCount === 0;
  });
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launchingId, setLaunchingId] = useState<string | null>(null);

  useEffect(() => {
    const pref = loadCollapsedPref(channelId);
    if (pref !== null) {
      setCollapsed(pref);
    } else {
      setCollapsed(findingsCount === 0);
    }
    // Intentionally not watching findingsCount here — the initial seed follows
    // activity, but live changes shouldn't force-collapse/expand the strip while
    // the user is interacting with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId]);

  // Phase 5: launchpad is driven by the channel's pipeline subscriptions
  // (not a global view of every source=system task). Each subscription carries
  // its own featured override; we synthesize TaskItem shape for downstream code.
  const { data: subsData, isLoading } = useChannelPipelines(channelId, {
    enabledOnly: true,
  });

  const systemTasks = useMemo<TaskItem[]>(() => {
    const subs = subsData?.subscriptions ?? [];
    return subs
      .filter((s) => s.pipeline !== null)
      .map((s) => subscriptionToTaskItem(s));
  }, [subsData]);

  // Resolve featured using the subscription override (pipeline default fallback
  // already applied server-side on subscription.featured).
  const featuredTaskIds = useMemo(() => {
    const ids = new Set<string>();
    for (const s of subsData?.subscriptions ?? []) {
      if (s.featured) ids.add(s.task_id);
    }
    return ids;
  }, [subsData]);

  const featured = useMemo(
    () => systemTasks.filter((t) => featuredTaskIds.has(t.id)),
    [systemTasks, featuredTaskIds],
  );
  const libraryItems = useMemo(
    () => systemTasks.filter((t) => !featuredTaskIds.has(t.id)),
    [systemTasks, featuredTaskIds],
  );

  // Recent runs on this channel — child tasks of pipelines, ordered by recency.
  // Refreshes every 10s while the strip is expanded so in-flight runs update.
  // include_children=true is required: pipeline runs are child tasks of the
  // system pipeline definitions, and the list endpoint hides children by default.
  const { data: runsData } = useQuery({
    queryKey: ["orchestrator-runs", channelId],
    queryFn: () =>
      apiFetch<TasksResponse>(
        `/api/v1/admin/tasks?channel_id=${encodeURIComponent(channelId)}&limit=20&include_children=true`,
      ),
    refetchInterval: collapsed ? false : 10_000,
    staleTime: 5_000,
  });

  const recentRuns = useMemo(() => {
    const rows = runsData?.tasks ?? [];
    const systemIds = new Set(systemTasks.map((t) => t.id));
    return rows
      .filter((r) => r.parent_task_id && systemIds.has(r.parent_task_id))
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))
      .slice(0, 6);
  }, [runsData, systemTasks]);

  const toggleCollapsed = () => {
    setCollapsed((v) => {
      const next = !v;
      saveCollapsed(channelId, next);
      return next;
    });
  };

  const handleLaunch = (pipeline: TaskItem) => {
    const schema = getParamsSchema(pipeline);
    if (schema && schema.length > 0) {
      setParamModalPipeline(pipeline);
      return;
    }
    setLaunchError(null);
    setLaunchingId(pipeline.id);
    runNowMut.mutate(
      { taskId: pipeline.id, channel_id: channelId },
      {
        onSuccess: () => setLaunchingId(null),
        onError: (err) => {
          setLaunchingId(null);
          setLaunchError(
            err instanceof Error
              ? `${pipeline.title || pipeline.id}: ${err.message}`
              : `Failed to launch ${pipeline.title || pipeline.id}`,
          );
        },
      },
    );
  };

  const handleModalLaunch = (params: Record<string, any>) => {
    if (!paramModalPipeline) return;
    setLaunchError(null);
    setLaunchingId(paramModalPipeline.id);
    runNowMut.mutate(
      { taskId: paramModalPipeline.id, params, channel_id: channelId },
      {
        onSuccess: () => {
          setLaunchingId(null);
          setParamModalPipeline(null);
        },
        onError: (err) => {
          setLaunchingId(null);
          setLaunchError(
            err instanceof Error
              ? `${paramModalPipeline.title || paramModalPipeline.id}: ${err.message}`
              : `Failed to launch ${paramModalPipeline.title || paramModalPipeline.id}`,
          );
        },
      },
    );
  };

  // Hide entirely if there aren't any system pipelines to show (fresh install
  // with no seeded pipelines shouldn't render a dead strip).
  if (!isLoading && systemTasks.length === 0) return null;

  return (
    <div className={cn(!collapsed && "bg-surface-raised/40")}>
      {/* Header — always visible, clickable to collapse/expand */}
      <button
        onClick={toggleCollapsed}
        className="w-full flex flex-row items-center justify-between
                   px-4 py-2 hover:bg-surface-raised/70 transition-colors"
        aria-expanded={!collapsed}
      >
        <div className="flex flex-row items-center gap-2">
          <Cog size={12} className="text-accent" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">
            Pipelines
          </span>
        </div>
        {collapsed ? (
          <ChevronDown size={14} className="text-text-dim" />
        ) : (
          <ChevronUp size={14} className="text-text-dim" />
        )}
      </button>

      {/* Awaiting reviews banner — the primary call-to-action when pipelines
          are paused at a user_prompt step. Highest visual weight in the strip. */}
      {findingsCount > 0 && !collapsed && (
        <button
          onClick={onOpenFindings}
          className="mx-4 mt-2 px-3 py-2 rounded-md
                     bg-accent/10 border border-accent/40
                     flex flex-row items-center justify-between gap-2
                     hover:bg-accent/15 transition-colors w-[calc(100%-2rem)]"
        >
          <div className="flex flex-row items-center gap-2 min-w-0">
            <PauseCircle size={14} className="text-accent animate-pulse shrink-0" />
            <span className="text-[12px] font-semibold text-accent truncate">
              {findingsCount} pipeline run{findingsCount === 1 ? "" : "s"} awaiting your review
            </span>
          </div>
          <span className="text-[11px] text-accent/80 shrink-0 flex items-center gap-1">
            Open Findings
            <ArrowRight size={11} />
          </span>
        </button>
      )}

      {/* Launch error banner */}
      {launchError && !collapsed && (
        <div className="mx-4 mt-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30
                        flex flex-row items-center justify-between gap-2 text-[12px] text-red-400">
          <span className="flex-1 min-w-0 truncate">{launchError}</span>
          <button
            onClick={() => setLaunchError(null)}
            className="shrink-0 text-red-400/70 hover:text-red-400"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* Body — tiles + library */}
      {!collapsed && (
        <div className="px-4 pb-4 pt-1 flex flex-col gap-3">
          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {[0, 1].map((i) => (
                <div
                  key={i}
                  className="h-[52px] p-3.5 rounded-lg bg-surface-raised border border-surface-border
                             animate-pulse opacity-60"
                />
              ))}
            </div>
          ) : featured.length === 0 ? (
            <div className="text-xs text-text-dim py-4 text-center">
              No featured system pipelines.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {featured.map((pipeline) => (
                <PipelineTile
                  key={pipeline.id}
                  pipeline={pipeline}
                  onLaunch={handleLaunch}
                  launchingId={launchingId}
                  onOpenFindings={onOpenFindings}
                />
              ))}
            </div>
          )}

          {/* Recent runs are hidden while reviews are pending — the launchpad's
              purpose in that moment is the review CTA, not browsing history. */}
          {recentRuns.length > 0 && findingsCount === 0 && (
            <div className="flex flex-col gap-1.5">
              <div className="flex flex-row items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">
                  Recent runs
                </span>
              </div>
              <div className="flex flex-col gap-1 border border-surface-border rounded-md
                              bg-surface overflow-hidden">
                {recentRuns.map((run) => {
                  const parent = systemTasks.find((t) => t.id === run.parent_task_id);
                  const pipelineTitle = parent?.title ?? run.parent_task_id ?? "pipeline";
                  const hasAwaiting = ((run as any).step_states ?? []).some(
                    (s: any) => s?.status === "awaiting_user_input",
                  );
                  const status = hasAwaiting ? "awaiting_user_input" : run.status;
                  const StatusIcon =
                    status === "running" || status === "pending" ? Loader2 :
                    status === "complete" ? CheckCircle2 :
                    status === "failed" ? AlertCircle :
                    status === "awaiting_user_input" ? PauseCircle :
                    Circle;
                  const statusColor =
                    status === "running" || status === "pending" ? "text-accent" :
                    status === "complete" ? "text-emerald-500" :
                    status === "failed" ? "text-red-500" :
                    status === "awaiting_user_input" ? "text-accent animate-pulse" :
                    "text-text-dim";
                  const statusLabel =
                    status === "awaiting_user_input" ? "awaiting review" :
                    status === "running" ? "running" :
                    status === "pending" ? "queued" :
                    status === "complete" ? "complete" :
                    status === "failed" ? "failed" :
                    status;
                  const isSpinning = status === "running" || status === "pending";
                  return (
                    <Link
                      to={`/admin/tasks/${run.id}`}
                      key={run.id}
                      className="flex flex-row items-center justify-between gap-3 px-3 py-2
                                 text-xs hover:bg-surface-raised transition-colors"
                    >
                      <div className="flex flex-row items-center gap-2.5 min-w-0 flex-1">
                        <StatusIcon
                          size={13}
                          className={cn(statusColor, "shrink-0", isSpinning && "animate-spin")}
                        />
                        <span className="font-medium text-text truncate">{pipelineTitle}</span>
                        <span className="text-text-dim truncate shrink-0">
                          · {statusLabel}
                        </span>
                      </div>
                      <span className="text-[10px] text-text-dim shrink-0 flex items-center gap-1">
                        <Clock size={9} />
                        {relTime(run.created_at)}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          )}

          {libraryItems.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <button
                onClick={() => setLibraryOpen((v) => !v)}
                className="flex flex-row items-center gap-1.5 text-[11px] text-text-dim
                           hover:text-text self-start"
              >
                {libraryOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                More pipelines ({libraryItems.length})
              </button>
              {libraryOpen && (
                <div className="flex flex-col gap-1 border border-surface-border rounded-md
                                bg-surface overflow-hidden">
                  {libraryItems.map((pipeline) => {
                    const Icon = iconFor(pipeline.id);
                    const pipelineRunning = launchingId === pipeline.id;
                    return (
                      <button
                        key={pipeline.id}
                        onClick={() => !pipelineRunning && handleLaunch(pipeline)}
                        disabled={pipelineRunning}
                        className="flex flex-row items-center justify-between gap-3 px-3 py-2
                                   hover:bg-surface-raised text-left disabled:opacity-60"
                      >
                        <div className="flex flex-row items-center gap-2.5 min-w-0">
                          <Icon size={13} className="text-text-dim shrink-0" />
                          <span className="text-xs font-medium text-text truncate">
                            {pipeline.title || pipeline.id}
                          </span>
                          {getDescription(pipeline) && (
                            <span className="text-[10px] text-text-dim truncate opacity-70">
                              · {getDescription(pipeline)}
                            </span>
                          )}
                        </div>
                        {pipelineRunning ? (
                          <Loader2 size={12} className="text-accent animate-spin shrink-0" />
                        ) : (
                          <ArrowRight size={11} className="text-text-dim shrink-0 opacity-60" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {paramModalPipeline && (
        <TaskRunModal
          pipeline={paramModalPipeline}
          onClose={() => setParamModalPipeline(null)}
          onLaunch={handleModalLaunch}
          running={runNowMut.isPending}
        />
      )}
    </div>
  );
}

// Backwards-compatible alias — earlier code passed this via emptyStateComponent.
// Kept exported so the generalized ChatMessageArea prop still works if some other
// channel wires it up; on system channels we now mount OrchestratorLaunchpad
// above the chat instead.
export const OrchestratorEmptyState = OrchestratorLaunchpad;
