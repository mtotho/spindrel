import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Archive,
  Bot,
  Check,
  Clock,
  ExternalLink,
  Inbox,
  Loader2,
  MessageSquare,
  Play,
  Radar,
  Sparkles,
  XCircle,
} from "lucide-react";

import {
  getOperatorTriage,
  useAcknowledgeAttentionItem,
  useAssignAttentionItem,
  useAttentionTriageRuns,
  useResolveAttentionItem,
  useStartAttentionTriageRun,
  useSubmitAttentionTriageFeedback,
  type AttentionAssignmentMode,
  type AttentionTriageRunResponse,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";
import { useBots } from "../../api/hooks/useBots";
import { BotPicker } from "../shared/BotPicker";
import { SessionChatView } from "../chat/SessionChatView";
import { openTraceInspector } from "../../stores/traceInspector";
import {
  OPERATOR_BOT_ID,
  attentionItemTriageLabel,
  bucketAttentionItems,
  getAttentionWorkflowState,
  severityRank,
  sweepCandidateItems,
  type AttentionBuckets,
} from "../spatial-canvas/SpatialAttentionModel";
import type { AttentionDeckMode } from "../../lib/hubRoutes";

type DeckMode = AttentionDeckMode;

interface AttentionCommandDeckProps {
  items: WorkspaceAttentionItem[];
  selectedId: string | null;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  initialMode?: DeckMode | null;
  selectedRunId?: string | null;
  channelId?: string | null;
  onModeChange?: (mode: DeckMode) => void;
  onRunSelect?: (runId: string | null) => void;
  onReply?: (item: WorkspaceAttentionItem) => void;
}

function targetLabel(item: WorkspaceAttentionItem): string {
  return item.channel_name ?? item.target_id ?? item.target_kind;
}

function sortAttention(items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  return [...items].sort((a, b) => {
    const severity = severityRank[b.severity] - severityRank[a.severity];
    if (severity !== 0) return severity;
    return new Date(b.last_seen_at ?? b.first_seen_at ?? 0).getTime() - new Date(a.last_seen_at ?? a.first_seen_at ?? 0).getTime();
  });
}

function runStatusLabel(run: AttentionTriageRunResponse): string {
  if (run.error || run.status === "failed") return "failed";
  if (run.status === "queued") return "queued";
  if (run.status === "running" || (run.counts?.running ?? 0) > 0) return "running";
  return "complete";
}

function formatRunTime(value?: string | null): string {
  if (!value) return "recent";
  return new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatItemTime(item: WorkspaceAttentionItem): string {
  const value = item.last_seen_at ?? item.first_seen_at;
  if (!value) return "unknown";
  return new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function routeLabel(route?: string | null): string {
  if (!route) return "Needs review";
  if (route === "developer_channel") return "Code fix";
  if (route === "owner_channel") return "Owner follow-up";
  if (route === "automation") return "Automation fix";
  if (route === "acknowledge") return "Can acknowledge";
  if (route === "user_decision") return "User decision";
  if (route === "benign") return "Benign";
  return route.replaceAll("_", " ");
}

function humanizeSuggestedAction(action?: string | null): string {
  const text = (action ?? "").trim();
  if (!text) return "";
  return text
    .replace(/\b[Rr]oute to (the )?developer channel\b/g, "Open a code fix")
    .replace(/\b[Rr]oute to development\b/g, "Open a code fix")
    .replace(/\b[Rr]oute to dev\b/g, "Open a code fix")
    .replace(/\bdeveloper channel\b/gi, "code fix")
    .replace(/\bdevelopment\b/gi, "code")
    .trim();
}

function severityClass(item: WorkspaceAttentionItem): string {
  if (item.severity === "critical" || item.severity === "error") return "text-danger";
  if (item.severity === "warning") return "text-warning";
  return "text-accent";
}

function modeItems(mode: DeckMode, buckets: AttentionBuckets): WorkspaceAttentionItem[] {
  if (mode === "review") return buckets.review;
  if (mode === "inbox") return [...buckets.untriaged, ...buckets.assigned];
  if (mode === "cleared") return [...buckets.processed, ...buckets.closed];
  return [...buckets.triage, ...buckets.review];
}

export function AttentionCommandDeck({
  items,
  selectedId,
  onSelect,
  initialMode,
  selectedRunId,
  channelId,
  onModeChange,
  onRunSelect,
  onReply,
}: AttentionCommandDeckProps) {
  const [mode, setModeState] = useState<DeckMode>(() => initialMode ?? "review");
  const [notice, setNotice] = useState<string | null>(null);
  const [runModePinned, setRunModePinned] = useState(false);
  const [sweepStarting, setSweepStarting] = useState(false);
  const detailRef = useRef<HTMLElement | null>(null);
  const buckets = useMemo(() => bucketAttentionItems(items), [items]);
  const sweepable = useMemo(() => sweepCandidateItems(items), [items]);
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const { data: runs = [] } = useAttentionTriageRuns({ limit: 16, refetchInterval: mode === "runs" ? 5_000 : 15_000 });
  const startTriage = useStartAttentionTriageRun();
  const hasActiveRun = runs.some((run) => {
    const status = runStatusLabel(run);
    return status === "queued" || status === "running";
  });
  const sweepBusy = startTriage.isPending || sweepStarting || hasActiveRun;
  const counts = {
    review: buckets.review.length,
    inbox: buckets.untriaged.length + buckets.assigned.length,
    running: buckets.triage.length,
    cleared: buckets.processed.length,
    closed: buckets.closed.length,
  };
  const activeList = useMemo(() => sortAttention(modeItems(mode, buckets)), [buckets, mode]);
  const firstReview = useMemo(() => sortAttention(buckets.review)[0] ?? null, [buckets.review]);
  const displayItem = selected ?? activeList[0] ?? null;

  const setDeckMode = (next: DeckMode) => {
    setRunModePinned(next === "runs");
    setModeState(next);
    onModeChange?.(next);
  };

  useEffect(() => {
    if (initialMode) {
      setModeState(initialMode);
      setRunModePinned(initialMode === "runs");
    }
  }, [initialMode]);

  useEffect(() => {
    if (initialMode || selected || runModePinned) return;
    if (counts.review > 0) setModeState("review");
    else if (counts.inbox > 0) setModeState("inbox");
    else if (runs.length > 0) setModeState("runs");
    else setModeState("cleared");
  }, [initialMode, selected?.id, counts.review, counts.inbox, runs.length, runModePinned]);

  useEffect(() => {
    if (hasActiveRun || runs.length > 0) setSweepStarting(false);
  }, [hasActiveRun, runs.length]);

  useEffect(() => {
    if (!selected) return;
    const state = getAttentionWorkflowState(selected);
    if (state === "operator_review") setDeckMode("review");
    else if (state === "processed" || state === "closed") setDeckMode("cleared");
    else if (state === "in_sweep") setDeckMode("runs");
    else setDeckMode("inbox");
  }, [selected?.id]);

  const startSweep = () => {
    setNotice(null);
    if (sweepBusy) {
      onSelect(null);
      setDeckMode("runs");
      setNotice("Operator sweep is already running. Stay here for the run log.");
      return;
    }
    if (!sweepable.length) {
      setDeckMode(buckets.review.length ? "review" : "inbox");
      setNotice(buckets.review.length ? "No new items to sweep. Review the existing Operator findings." : "No raw signals are ready for Operator.");
      return;
    }
    onSelect(null);
    setDeckMode("runs");
    setSweepStarting(true);
    startTriage.mutate({}, {
      onSuccess: (run) => {
        onRunSelect?.(run.task_id);
        setNotice("Operator sweep started. Stay on the run log while findings arrive.");
      },
      onError: (error) => {
        setSweepStarting(false);
        setNotice(error instanceof Error ? error.message : "Operator sweep could not start.");
      },
    });
  };

  const focusDetail = () => {
    window.requestAnimationFrame(() => detailRef.current?.focus({ preventScroll: false }));
  };

  const focusReviewFinding = (item: WorkspaceAttentionItem | null = firstReview) => {
    if (!item) return;
    setDeckMode("review");
    onSelect(item);
    focusDetail();
  };

  const whatNow = (() => {
    if (sweepBusy) {
      return {
        eyebrow: "Operator running",
        title: "Watch the active sweep",
        detail: "Raw signals are being classified into findings or cleared receipts.",
        action: "View run log",
        icon: <Loader2 size={15} className="animate-spin" />,
        onClick: () => setDeckMode("runs"),
      };
    }
    if (counts.review > 0) {
      return {
        eyebrow: "Best next click",
        title: "Review the first Operator finding",
        detail: `${counts.review} finding${counts.review === 1 ? "" : "s"} already classified and waiting for a decision.`,
        action: "Review first finding",
        icon: <Sparkles size={15} />,
        onClick: () => focusReviewFinding(),
      };
    }
    if (counts.inbox > 0) {
      return {
        eyebrow: "Raw signals waiting",
        title: "Run Operator sweep",
        detail: `${counts.inbox} raw signal${counts.inbox === 1 ? "" : "s"} can be classified before you review them manually.`,
        action: "Start sweep",
        icon: <Sparkles size={15} />,
        onClick: startSweep,
      };
    }
    return {
      eyebrow: "No active review",
      title: "Check cleared receipts",
      detail: `${counts.cleared + counts.closed} cleared item${counts.cleared + counts.closed === 1 ? "" : "s"} are available for audit.`,
      action: "View cleared",
      icon: <Archive size={15} />,
      onClick: () => setDeckMode("cleared"),
    };
  })();

  return (
    <div className="flex h-full min-h-0 flex-col text-text">
      <div className="shrink-0 border-b border-surface-border/70 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
              <Radar size={13} />
              Mission Control Review
            </div>
            <div className="mt-1 text-sm text-text-muted">
              {channelId ? "Channel-filtered" : "Workspace"} review · {counts.review} findings · {counts.inbox} raw · {counts.cleared} cleared
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-text-muted hover:bg-surface-overlay/60 hover:text-text"
              onClick={() => setDeckMode("runs")}
            >
              <Clock size={14} />
              Runs
            </button>
            <button
              type="button"
              disabled={sweepBusy || !sweepable.length}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md bg-accent/[0.08] px-3 text-xs font-medium text-accent hover:bg-accent/[0.12] disabled:opacity-50"
              onClick={startSweep}
            >
              {sweepBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {sweepBusy ? "Sweep running" : sweepable.length ? "Run Operator sweep" : "No raw signals"}
            </button>
          </div>
        </div>
        {notice && (
          <div className="mt-3 rounded-md bg-surface-overlay/45 px-3 py-2 text-xs text-text-muted">
            {notice}
          </div>
        )}
        <div className="mt-3 rounded-md bg-surface-overlay/35 px-3 py-3" data-testid="attention-command-deck-what-now">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">{whatNow.eyebrow}</div>
              <div className="mt-1 text-sm font-medium text-text">{whatNow.title}</div>
              <div className="mt-1 text-xs leading-5 text-text-muted">{whatNow.detail}</div>
            </div>
            <button
              type="button"
              className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-md bg-accent/[0.08] px-3 text-sm font-medium text-accent hover:bg-accent/[0.12]"
              onClick={whatNow.onClick}
            >
              {whatNow.icon}
              {whatNow.action}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
            <QueueChip active={mode === "review"} label="Findings" count={counts.review} onClick={() => setDeckMode("review")} />
            <QueueChip active={mode === "inbox"} label="Raw" count={counts.inbox} onClick={() => setDeckMode("inbox")} />
            <QueueChip active={mode === "runs"} label="Runs" count={runs.length || counts.running} onClick={() => setDeckMode("runs")} />
            <QueueChip active={mode === "cleared"} label="Cleared" count={counts.cleared + counts.closed} onClick={() => setDeckMode("cleared")} />
          </div>
        </div>
      </div>

      <div className={`grid min-h-0 flex-1 grid-cols-1 ${mode === "runs" ? "lg:grid-cols-[280px_minmax(0,1fr)]" : "lg:grid-cols-[280px_minmax(0,1fr)_320px]"}`}>
        <DeckQueue
          mode={mode}
          counts={counts}
          runCount={runs.length}
          items={activeList}
          selectedId={displayItem?.id ?? null}
          onModeChange={(next) => {
            setDeckMode(next);
            onSelect(null);
          }}
          onSelect={onSelect}
        />
        <main ref={detailRef} tabIndex={-1} className="min-h-0 overflow-y-auto border-t border-surface-border/60 px-4 py-4 outline-none lg:border-l lg:border-t-0">
          {mode === "runs" ? (
            <RunLogWorkspace pending={sweepBusy} runs={runs} selectedRunId={selectedRunId} onRunSelect={onRunSelect} />
          ) : displayItem ? (
            <DeckItemDetail item={displayItem} onReply={onReply} />
          ) : (
            <EmptyDeckState mode={mode} />
          )}
        </main>
        {mode !== "runs" && (
          <DeckSideRail
            mode={mode}
            selectedId={displayItem?.id ?? null}
            runs={runs}
            buckets={buckets}
            onModeChange={setDeckMode}
            onRunSelect={onRunSelect}
            onSelect={(item) => {
              onSelect(item);
              focusDetail();
            }}
          />
        )}
      </div>
    </div>
  );
}

function QueueChip({ active, label, count, onClick }: { active: boolean; label: string; count: number; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`inline-flex min-h-7 items-center gap-1.5 rounded-full px-2.5 transition-colors ${
        active ? "bg-accent/[0.08] text-accent" : "bg-surface-raised/50 text-text-muted hover:bg-surface-overlay/60 hover:text-text"
      }`}
      onClick={onClick}
    >
      <span>{label}</span>
      <span className="text-[11px] text-text-dim">{count}</span>
    </button>
  );
}

function DeckQueue({
  mode,
  counts,
  runCount,
  items,
  selectedId,
  onModeChange,
  onSelect,
}: {
  mode: DeckMode;
  counts: { review: number; inbox: number; running: number; cleared: number; closed: number };
  runCount: number;
  items: WorkspaceAttentionItem[];
  selectedId: string | null;
  onModeChange: (mode: DeckMode) => void;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
}) {
  const title = mode === "inbox" ? "Raw signals" : mode === "review" ? "Operator findings" : mode === "cleared" ? "Cleared items" : "Run log";
  return (
    <aside className="min-h-0 overflow-y-auto px-3 py-3">
      <div className="grid grid-cols-2 gap-1.5">
        <ModeButton active={mode === "review"} icon={<Sparkles size={14} />} label="Review" count={counts.review} onClick={() => onModeChange("review")} />
        <ModeButton active={mode === "inbox"} icon={<Inbox size={14} />} label="Inbox" count={counts.inbox} onClick={() => onModeChange("inbox")} />
        <ModeButton active={mode === "runs"} icon={<Clock size={14} />} label="Runs" count={runCount || counts.running} onClick={() => onModeChange("runs")} />
        <ModeButton active={mode === "cleared"} icon={<Archive size={14} />} label="Cleared" count={counts.cleared + counts.closed} onClick={() => onModeChange("cleared")} />
      </div>

      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <span>{title}</span>
          <span>{mode === "runs" ? runCount : items.length}</span>
        </div>
        <div className="space-y-1">
          {mode === "runs" ? (
            <div className="rounded-md bg-surface-raised/35 px-3 py-3 text-xs leading-5 text-text-muted">
              Pick a run in the center panel. Runs are receipts: they explain which signals became findings, which were cleared, and where the transcript evidence lives.
            </div>
          ) : items.length ? items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`block w-full rounded-md px-3 py-2 text-left transition-colors ${
                selectedId === item.id ? "bg-accent/[0.08] text-text" : "text-text-muted hover:bg-surface-overlay/55 hover:text-text"
              }`}
              onClick={() => onSelect(item)}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0 truncate text-sm font-medium">{item.title}</span>
                <span className={`shrink-0 text-[10px] ${severityClass(item)}`}>{item.severity}</span>
              </div>
              <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-text-dim">
                <span className="truncate">{attentionItemTriageLabel(item)} · {targetLabel(item)}</span>
              </div>
            </button>
          )) : (
            <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/35 px-3 py-6 text-center text-xs text-text-dim">
              Nothing in this lane.
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function ModeButton({ active, icon, label, count, onClick }: { active: boolean; icon: ReactNode; label: string; count: number; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`flex min-h-10 items-center justify-between gap-2 rounded-md px-2.5 text-left text-xs transition-colors ${
        active ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/55 hover:text-text"
      }`}
      onClick={onClick}
    >
      <span className="inline-flex min-w-0 items-center gap-1.5">
        {icon}
        <span className="truncate">{label}</span>
      </span>
      <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-muted">{count}</span>
    </button>
  );
}

function DeckItemDetail({ item, onReply }: { item: WorkspaceAttentionItem; onReply?: (item: WorkspaceAttentionItem) => void }) {
  const acknowledge = useAcknowledgeAttentionItem();
  const resolve = useResolveAttentionItem();
  const triageFeedback = useSubmitAttentionTriageFeedback();
  const triage = getOperatorTriage(item);
  const workflowState = getAttentionWorkflowState(item);
  const reviewed = workflowState === "operator_review";
  const readonly = workflowState === "processed" || workflowState === "closed";
  const suggestedAction = humanizeSuggestedAction(triage?.suggested_action);

  return (
    <article className="mx-auto max-w-3xl">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            {reviewed ? "Operator finding" : "Raw signal"}
          </div>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-text">{item.title}</h2>
          <div className="mt-1 text-sm text-text-muted">
            {item.severity} · {attentionItemTriageLabel(item)} · {targetLabel(item)} · {formatItemTime(item)}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {readonly ? (
            <span className="rounded-full bg-surface-overlay px-2.5 py-1 text-xs font-medium text-text-muted">
              {workflowState === "closed" ? "Closed" : "Cleared by Operator"}
            </span>
          ) : onReply && (
            <button type="button" className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-accent hover:bg-accent/[0.08]" onClick={() => onReply(item)}>
              <MessageSquare size={15} />
              Reply
            </button>
          )}
          {!readonly && (
            <>
              <button type="button" className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-text-muted hover:bg-surface-overlay/60 hover:text-text" onClick={() => acknowledge.mutate(item.id)}>
                <Check size={15} />
                Acknowledge
              </button>
              <button type="button" className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-text-muted hover:bg-surface-overlay/60 hover:text-text" onClick={() => resolve.mutate(item.id)}>
                <XCircle size={15} />
                Resolve
              </button>
            </>
          )}
        </div>
      </div>

      {triage && (
        <section className="mb-4 rounded-md bg-surface-overlay/35 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">
              <Sparkles size={13} />
              Operator review
            </span>
            {triage.classification && <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">{triage.classification.replaceAll("_", " ")}</span>}
            <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-accent">{routeLabel(triage.route)}</span>
          </div>
          {triage.summary && <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-text-muted">{triage.summary}</p>}
          {suggestedAction && (
            <p className="mt-3 text-sm leading-6 text-text">
              <span className="text-text-dim">Next: </span>
              {suggestedAction}
            </p>
          )}
          {!readonly && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button type="button" className="rounded-md px-2.5 py-1.5 text-sm text-accent hover:bg-accent/[0.08]" onClick={() => triageFeedback.mutate({ itemId: item.id, verdict: "confirmed" })}>
                Accept finding
              </button>
              <button
                type="button"
                className="rounded-md px-2.5 py-1.5 text-sm text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                onClick={() => {
                  const note = window.prompt("What should Operator remember next time?", triage.summary ?? "");
                  if (note !== null) triageFeedback.mutate({ itemId: item.id, verdict: "wrong", note });
                }}
              >
                Mark wrong
              </button>
              <button
                type="button"
                className="rounded-md px-2.5 py-1.5 text-sm text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                onClick={() => {
                  const note = window.prompt("Routing correction for future Operator sweeps", triage.route ? `Suggested route should not be ${routeLabel(triage.route)}.` : "");
                  if (note !== null) triageFeedback.mutate({ itemId: item.id, verdict: "rerouted", note, route: triage.route ?? null });
                }}
              >
                Change routing
              </button>
            </div>
          )}
        </section>
      )}

      <section className="mb-4 space-y-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Evidence</div>
        <p className="whitespace-pre-wrap text-base leading-7 text-text-muted">{item.message}</p>
        {item.assignment_report && (
          <div className="rounded-md bg-accent/[0.08] px-4 py-3">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Bot findings</div>
            <p className="whitespace-pre-wrap text-sm leading-6 text-text-muted">{item.assignment_report}</p>
          </div>
        )}
        <div className="grid gap-2 text-xs text-text-dim sm:grid-cols-2">
          <span>Target: {item.target_kind}</span>
          <span>Count: {item.occurrence_count}</span>
          <span>Channel: {item.channel_name ?? item.channel_id ?? "none"}</span>
          <span>Last: {item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : "unknown"}</span>
        </div>
        {item.latest_correlation_id && (
          <button type="button" className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-accent hover:bg-accent/10" onClick={() => openTraceInspector({ correlationId: item.latest_correlation_id!, title: item.title })}>
            <ExternalLink size={14} />
            Open trace evidence
          </button>
        )}
      </section>

      {!readonly && <SendToBotDisclosure item={item} />}
    </article>
  );
}

function SendToBotDisclosure({ item }: { item: WorkspaceAttentionItem }) {
  const assign = useAssignAttentionItem();
  const { data: bots = [] } = useBots();
  const assignableBots = useMemo(() => bots.filter((bot) => bot.id !== OPERATOR_BOT_ID), [bots]);
  const [botId, setBotId] = useState(item.assigned_bot_id === OPERATOR_BOT_ID ? "" : item.assigned_bot_id ?? "");
  const [mode, setMode] = useState<AttentionAssignmentMode>(item.assignment_mode ?? "next_heartbeat");
  const [instructions, setInstructions] = useState(item.assignment_instructions ?? "");

  useEffect(() => {
    setBotId(item.assigned_bot_id === OPERATOR_BOT_ID ? "" : item.assigned_bot_id ?? "");
    setMode(item.assignment_mode ?? "next_heartbeat");
    setInstructions(item.assignment_instructions ?? "");
  }, [item.id, item.assigned_bot_id, item.assignment_mode, item.assignment_instructions]);

  return (
    <details className="rounded-md bg-surface-raised/35 px-3 py-2">
      <summary className="cursor-pointer text-sm font-medium text-text-muted hover:text-text">Send this issue to a bot</summary>
      <div className="mt-3 space-y-3">
        <BotPicker value={botId} onChange={setBotId} bots={assignableBots} allowNone />
        <div className="inline-flex rounded-md bg-surface-overlay/45 p-0.5">
          <button type="button" className={`rounded px-3 py-1.5 text-xs font-medium ${mode === "next_heartbeat" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:text-text"}`} onClick={() => setMode("next_heartbeat")}>Next heartbeat</button>
          <button type="button" className={`rounded px-3 py-1.5 text-xs font-medium ${mode === "run_now" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:text-text"}`} onClick={() => setMode("run_now")}>Run now</button>
        </div>
        <textarea
          className="min-h-20 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent"
          placeholder="Instructions for the selected bot"
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
        />
        <button
          type="button"
          disabled={!botId || assign.isPending}
          className="rounded-md bg-accent/[0.08] px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.12] disabled:opacity-50"
          onClick={() => assign.mutate({ itemId: item.id, bot_id: botId, mode, instructions })}
        >
          Send to bot
        </button>
      </div>
    </details>
  );
}

function RunLogWorkspace({
  pending,
  runs,
  selectedRunId,
  onRunSelect,
}: {
  pending: boolean;
  runs: AttentionTriageRunResponse[];
  selectedRunId?: string | null;
  onRunSelect?: (runId: string | null) => void;
}) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const activeRunId = selectedRunId ?? selectedTaskId;
  const selectedRun = runs.find((run) => run.task_id === activeRunId) ?? runs[0] ?? null;
  const selectRun = (taskId: string) => {
    setSelectedTaskId(taskId);
    onRunSelect?.(taskId);
  };

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-4">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Operator runs</div>
        <h2 className="mt-1 text-2xl font-semibold text-text">Run log</h2>
        <p className="mt-1 text-sm text-text-muted">
          Runs explain how raw signals became reviewed findings or cleared noise.
        </p>
      </div>

      {pending && (
        <section className="mb-4 rounded-md bg-accent/[0.08] px-4 py-3 text-sm text-accent">
          <span className="inline-flex items-center gap-2">
            <Loader2 size={15} className="animate-spin" />
            Starting Operator sweep
          </span>
        </section>
      )}

      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-1">
          {runs.length ? runs.map((run) => (
            <button
              key={run.task_id}
              type="button"
              className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
                selectedRun?.task_id === run.task_id ? "bg-accent/[0.08] text-text" : "text-text-muted hover:bg-surface-overlay/55 hover:text-text"
              }`}
              onClick={() => selectRun(run.task_id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{formatRunTime(run.created_at)}</span>
                <span className="text-[10px] uppercase tracking-[0.08em] text-text-dim">{runStatusLabel(run)}</span>
              </div>
              <div className="mt-1 text-xs text-text-dim">
                {run.item_count} items · {run.counts?.ready_for_review ?? 0} review · {run.counts?.processed ?? 0} cleared
              </div>
            </button>
          )) : (
            <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/35 px-3 py-6 text-center text-xs text-text-dim">
              No Operator runs yet.
            </div>
          )}
        </aside>

        <section className="min-w-0">
          {selectedRun ? (
            <RunReceipt run={selectedRun} />
          ) : (
            <div className="rounded-md bg-surface-raised/35 px-4 py-8 text-center text-sm text-text-dim">
              Start a sweep to create a run log.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function runBucketItems(run: AttentionTriageRunResponse) {
  const runItems = run.items ?? [];
  return {
    review: sortAttention(runItems.filter((item) => getAttentionWorkflowState(item) === "operator_review")),
    cleared: sortAttention(runItems.filter((item) => {
      const state = getAttentionWorkflowState(item);
      return state === "processed" || state === "closed";
    })),
    running: sortAttention(runItems.filter((item) => getAttentionWorkflowState(item) === "in_sweep")),
  };
}

function RunReceipt({ run }: { run: AttentionTriageRunResponse }) {
  const status = runStatusLabel(run);
  const hasTranscript = Boolean(run.session_id && run.parent_channel_id);
  const runItems = runBucketItems(run);
  const reviewCount = run.counts?.ready_for_review ?? runItems.review.length;
  const clearedCount = run.counts?.processed ?? runItems.cleared.length;
  const runningCount = run.counts?.running ?? runItems.running.length;
  return (
    <div className="space-y-4" data-testid="attention-run-receipt">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-surface-overlay/35 px-4 py-3">
        <div>
          <div className="text-sm font-medium text-text">Operator sweep</div>
          <div className="mt-1 text-xs text-text-muted">
            {run.item_count} items · {run.effective_model || run.model_override || "default model"} · {formatRunTime(run.created_at)}
          </div>
        </div>
        <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">{status}</span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-sm">
        <div className="rounded-md bg-surface-overlay/35 px-3 py-2"><span className="font-medium text-text">{reviewCount}</span> review</div>
        <div className="rounded-md bg-surface-overlay/35 px-3 py-2"><span className="font-medium text-text">{clearedCount}</span> cleared</div>
        <div className="rounded-md bg-surface-overlay/35 px-3 py-2"><span className="font-medium text-text">{runningCount}</span> running</div>
      </div>

      {run.error && (
        <div className="rounded-md bg-danger/10 px-4 py-3 text-sm text-danger-muted">
          {run.error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <RunItemList title="Ready for review" items={runItems.review} empty="No review items from this run." />
        <RunItemList title="Cleared by Operator" items={runItems.cleared} empty="No cleared items from this run." />
      </div>

      <details className="rounded-md bg-surface-overlay/30 px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium text-text-muted hover:text-text">Transcript evidence</summary>
        <div className="mt-3 min-h-[min(72vh,720px)] overflow-hidden rounded-md bg-surface-raised/35" style={{ contain: "paint" }}>
          {hasTranscript ? (
            <div className="relative h-[min(72vh,720px)]">
              <SessionChatView
                sessionId={run.session_id!}
                parentChannelId={run.parent_channel_id!}
                botId={run.bot_id}
                chatMode="default"
                surface="operator-panel"
                emptyStateComponent={<div className="px-3 py-4 text-xs text-text-dim">Waiting for Operator transcript...</div>}
              />
            </div>
          ) : (
            <div className="px-4 py-8 text-center text-sm text-text-dim">Transcript is not available for this run.</div>
          )}
        </div>
      </details>
    </div>
  );
}

function RunItemList({ title, items, empty }: { title: string; items: WorkspaceAttentionItem[]; empty: string }) {
  return (
    <section className="rounded-md bg-surface-overlay/25 px-3 py-3">
      <div className="mb-2 flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
        <span>{title}</span>
        <span>{items.length}</span>
      </div>
      <div className="space-y-1">
        {items.length ? items.slice(0, 8).map((item) => (
          <div key={item.id} className="rounded-md px-2 py-1.5 text-sm">
            <div className="truncate font-medium text-text">{item.title}</div>
            <div className="mt-0.5 truncate text-xs text-text-dim">{targetLabel(item)} · {routeLabel(getOperatorTriage(item)?.route)}</div>
          </div>
        )) : (
          <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/25 px-3 py-5 text-center text-xs text-text-dim">{empty}</div>
        )}
      </div>
    </section>
  );
}

function DeckSideRail({
  mode,
  selectedId,
  runs,
  buckets,
  onModeChange,
  onRunSelect,
  onSelect,
}: {
  mode: DeckMode;
  selectedId: string | null;
  runs: AttentionTriageRunResponse[];
  buckets: AttentionBuckets;
  onModeChange: (mode: DeckMode) => void;
  onRunSelect?: (runId: string | null) => void;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
}) {
  const latest = runs[0] ?? null;
  const nextReview = buckets.review[0] ?? null;
  const reviewingNext = Boolean(nextReview && mode === "review" && selectedId === nextReview.id);
  return (
    <aside className="hidden min-h-0 overflow-y-auto border-l border-surface-border/60 px-3 py-3 lg:block">
      <section className="mb-4 rounded-md bg-surface-overlay/35 px-3 py-3">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <Sparkles size={13} />
          Next best click
        </div>
        {nextReview ? (
          <>
            <div className="mt-2 text-sm font-medium text-text">{nextReview.title}</div>
            <div className="mt-1 text-xs text-text-muted">{reviewingNext ? "You are reviewing this finding now." : "Operator has marked this for review."}</div>
            {!reviewingNext && (
              <button
                type="button"
                className="mt-3 rounded-md bg-accent/[0.08] px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.12]"
                onClick={() => {
                  onModeChange("review");
                  onSelect(nextReview);
                }}
              >
                Review first finding
              </button>
            )}
          </>
        ) : (
          <div className="mt-2 text-sm text-text-muted">No reviewed findings are waiting.</div>
        )}
      </section>

      <section className="rounded-md bg-surface-overlay/35 px-3 py-3">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <Clock size={13} />
          Latest run
        </div>
        {latest ? (
          <>
            <div className="mt-2 text-sm font-medium text-text">{runStatusLabel(latest)} · {formatRunTime(latest.created_at)}</div>
            <div className="mt-1 text-xs text-text-muted">
              {latest.item_count} items · {latest.counts?.ready_for_review ?? 0} review · {latest.counts?.processed ?? 0} cleared
            </div>
            <button
              type="button"
              className="mt-3 rounded-md px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.08]"
              onClick={() => {
                onModeChange("runs");
                onRunSelect?.(latest.task_id);
              }}
            >
              Open run log
            </button>
          </>
        ) : (
          <div className="mt-2 text-sm text-text-muted">No sweep has reported yet.</div>
        )}
      </section>
    </aside>
  );
}

function EmptyDeckState({ mode }: { mode: DeckMode }) {
  const icon = mode === "review" ? <Sparkles size={20} /> : mode === "inbox" ? <Inbox size={20} /> : mode === "cleared" ? <Archive size={20} /> : <Clock size={20} />;
  return (
    <div className="flex min-h-[320px] items-center justify-center">
      <div className="max-w-sm text-center">
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-md bg-surface-overlay/45 text-text-dim">{icon}</div>
        <div className="mt-3 text-sm font-medium text-text">Nothing selected</div>
        <div className="mt-1 text-sm text-text-muted">Choose a lane item, start a sweep, or open a run log.</div>
      </div>
    </div>
  );
}
