import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bot, Check, ExternalLink, Loader2, MessageSquare, Plus, Radar, Sparkles, X } from "lucide-react";
import {
  getOperatorTriage,
  isOperatorTriageProcessed,
  isOperatorTriageReadyForReview,
  useAcknowledgeAttentionItem,
  useAssignAttentionItem,
  useAttentionTriageRuns,
  useBulkAcknowledgeAttentionItems,
  useCreateAttentionItem,
  useResolveAttentionItem,
  useStartAttentionTriageRun,
  useSubmitAttentionTriageFeedback,
  useWorkspaceAttention,
  isActiveAttentionItem,
  type AttentionTriageRunResponse,
  type AttentionAssignmentMode,
  type AttentionSeverity,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";
import {
  OPERATOR_BOT_ID,
  activeAttentionItems,
  attentionBucketSummary,
  attentionItemTriageLabel,
  attentionMapCueLabel,
  bucketAttentionItems,
  getAttentionWorkflowState,
  severityRank,
  sweepCandidateItems,
  type AttentionBuckets,
} from "./SpatialAttentionModel";
import { useBots } from "../../api/hooks/useBots";
import { useChannels } from "../../api/hooks/useChannels";
import { BotPicker } from "../shared/BotPicker";
import { LlmModelDropdown } from "../shared/LlmModelDropdown";
import { useUIStore } from "../../stores/ui";
import { openTraceInspector } from "../../stores/traceInspector";
import { SessionChatView } from "../chat/SessionChatView";

function signalClass(item: WorkspaceAttentionItem): string {
  if (getAttentionWorkflowState(item) === "operator_review") return "text-accent";
  if (item.source_type === "system") return "text-danger";
  if (item.severity === "critical" || item.severity === "error") return "text-danger";
  if (item.severity === "warning") return "text-warning";
  return "text-accent";
}

function severityTextClass(item: WorkspaceAttentionItem): string {
  if (item.severity === "critical" || item.severity === "error") return "text-danger";
  if (item.severity === "warning") return "text-warning";
  return "text-accent";
}

function statusLabel(item: WorkspaceAttentionItem): string {
  const triageLabel = attentionItemTriageLabel(item);
  if (triageLabel !== "untriaged") return triageLabel;
  if (item.assignment_status === "running") return "running";
  if (item.assignment_status === "assigned") return "assigned";
  if (item.assignment_status === "reported") return "reported";
  if (item.status === "responded") return "responded";
  if (item.status === "acknowledged") return "acknowledged";
  if (item.requires_response) return "needs reply";
  return item.status;
}

export function shouldSurfaceAttentionOnMap(item: WorkspaceAttentionItem): boolean {
  if (!isActiveAttentionItem(item) && getAttentionWorkflowState(item) !== "operator_review") return false;
  if (getAttentionWorkflowState(item) === "operator_review") return true;
  if (item.source_type === "system") {
    const classification = typeof item.evidence?.classification === "string" ? item.evidence.classification : "";
    return item.severity === "critical"
      || classification === "severe"
      || classification === "repeated"
      || (item.occurrence_count || 0) >= 3;
  }
  if (item.requires_response) return true;
  return item.severity === "warning" || item.severity === "error" || item.severity === "critical";
}

function plural(count: number, singular: string, pluralLabel = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralLabel}`;
}

function targetKey(item: WorkspaceAttentionItem): string {
  return `${item.target_kind}:${item.target_id ?? "none"}:${item.channel_id ?? "none"}`;
}

function targetLabel(item: WorkspaceAttentionItem): string {
  return item.channel_name ?? item.target_id ?? item.target_kind;
}

function isOperatorRunActive(run: AttentionTriageRunResponse | null | undefined): boolean {
  if (!run) return false;
  return run.status === "queued" || run.status === "running" || (run.counts?.running ?? 0) > 0;
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

interface SignalProps {
  items: WorkspaceAttentionItem[];
  scale: number;
  onSelect: (item: WorkspaceAttentionItem) => void;
}

export function SpatialAttentionSignal({ items, scale, onSelect }: SignalProps) {
  const active = activeAttentionItems(items).filter(shouldSurfaceAttentionOnMap).sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
  if (!active.length) return null;
  const primary = active[0];
  const count = active.length;
  const inv = 1 / Math.max(scale, 0.05);
  const occurrenceCount = active.reduce((total, item) => total + Math.max(1, item.occurrence_count || 1), 0);
  const urgent = active.some((item) => getAttentionWorkflowState(item) !== "operator_review" && (item.source_type === "system" || item.severity === "critical"));
  const label = count === 1
    ? `${targetLabel(primary)}: ${attentionMapCueLabel(primary)} - ${statusLabel(primary)}${occurrenceCount > 1 ? ` (${occurrenceCount} occurrences)` : ""}`
    : `${targetLabel(primary)}: ${plural(count, "action item")} (${occurrenceCount} occurrences)`;
  return (
    <div
      className="pointer-events-none absolute left-1/2 top-1/2 z-[50]"
      style={{
        transform: `translate(18px, -34px) scale(${inv})`,
        transformOrigin: "center center",
      }}
    >
      <div
        className={`relative flex h-10 w-10 items-center justify-center rounded-full ${signalClass(primary)}`}
        aria-hidden
      >
        <span
          className={`absolute h-7 w-7 rounded-full border-t-2 border-r-2 border-current opacity-75 ${urgent ? "attention-signal-pulse" : ""}`}
        />
        <span className="absolute h-1.5 w-1.5 translate-x-2 -translate-y-2 rounded-full bg-current" />
      </div>
      <button
        type="button"
        data-testid="spatial-attention-badge"
        className={`pointer-events-auto absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full border border-surface-raised bg-surface-raised ${signalClass(primary)} shadow-[0_6px_16px_rgb(0_0_0/0.28)] hover:bg-surface-overlay focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70`}
        title={label}
        aria-label={label}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          onSelect(primary);
        }}
      >
        <AlertTriangle size={12} aria-hidden />
      </button>
    </div>
  );
}

interface LayerProps {
  items: WorkspaceAttentionItem[];
  selectedId: string | null;
  hubOpen: boolean;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  onCloseHub: () => void;
  onReply: (item: WorkspaceAttentionItem) => void;
}

export function SpatialAttentionLayer({ items, selectedId, hubOpen, onSelect, onCloseHub, onReply }: LayerProps) {
  return (
    <AttentionHubDrawer
      open={hubOpen || Boolean(selectedId)}
      items={items}
      selectedId={selectedId}
      onSelect={onSelect}
      onClose={() => {
        onSelect(null);
        onCloseHub();
      }}
      onReply={onReply}
    />
  );
}

export function AttentionHubDrawerRoot() {
  const open = useUIStore((s) => s.attentionHubOpen);
  const close = useUIStore((s) => s.closeAttentionHub);
  const { data: items } = useWorkspaceAttention(null, { enabled: open, includeResolved: true });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return (
    <AttentionHubDrawer
      open={open}
      items={items ?? []}
      selectedId={selectedId}
      onSelect={(item) => setSelectedId(item?.id ?? null)}
      onClose={() => {
        setSelectedId(null);
        close();
      }}
    />
  );
}

function AttentionHubDrawer({
  open,
  items,
  selectedId,
  onSelect,
  onClose,
  onReply,
}: {
  open: boolean;
  items: WorkspaceAttentionItem[];
  selectedId: string | null;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  onClose: () => void;
  onReply?: (item: WorkspaceAttentionItem) => void;
}) {
  if (!open) return null;
  return (
    <aside
      className="fixed bottom-4 right-4 top-16 z-[70] flex w-[460px] max-w-[calc(100vw-2rem)] flex-col rounded-md bg-surface-raised/95 text-sm text-text backdrop-blur"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <AttentionHubContent
        items={items}
        selectedId={selectedId}
        onSelect={onSelect}
        onClose={onClose}
        onReply={onReply}
      />
    </aside>
  );
}

export function AttentionHubContent({
  items,
  selectedId,
  onSelect,
  onClose,
  onReply,
}: {
  items: WorkspaceAttentionItem[];
  selectedId: string | null;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  onClose?: () => void;
  onReply?: (item: WorkspaceAttentionItem) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [triageRun, setTriageRun] = useState<AttentionTriageRunResponse | null>(null);
  const [operatorRunOpen, setOperatorRunOpen] = useState(false);
  const [triageOptionsOpen, setTriageOptionsOpen] = useState(false);
  const [triageModel, setTriageModel] = useState("");
  const [triageProviderId, setTriageProviderId] = useState<string | null>(null);
  const bulkAcknowledge = useBulkAcknowledgeAttentionItems();
  const startTriage = useStartAttentionTriageRun();
  const { data: triageRuns = [] } = useAttentionTriageRuns({
    limit: 12,
    refetchInterval: operatorRunOpen || startTriage.isPending ? 5_000 : 15_000,
  });
  const { data: bots = [] } = useBots();
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const operatorBot = bots.find((bot) => bot.id === OPERATOR_BOT_ID);
  const operatorDefaultModel = operatorBot?.model ?? "operator default";
  const active = activeAttentionItems(items);
  const sweepable = sweepCandidateItems(items);
  const activeOccurrenceCount = active.reduce((total, item) => total + Math.max(1, item.occurrence_count || 1), 0);
  const selectedTargetItems = useMemo(() => {
    if (!selected) return [];
    const key = targetKey(selected);
    return active
      .filter((item) => targetKey(item) === key)
      .sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
  }, [active, selected]);
  const grouped = useMemo(() => bucketAttentionItems(items), [items]);
  const recoveredTriageRun = useMemo<AttentionTriageRunResponse | null>(() => {
    for (const item of items) {
      const triage = getOperatorTriage(item);
      if (!triage?.session_id || !triage.parent_channel_id) continue;
      const sessionItemCount = items.filter((candidate) => getOperatorTriage(candidate)?.session_id === triage.session_id).length;
      return {
        task_id: triage.task_id ?? "",
        session_id: triage.session_id,
        parent_channel_id: triage.parent_channel_id,
        bot_id: triage.operator_bot_id || OPERATOR_BOT_ID,
        item_count: sessionItemCount || 1,
        model_override: null,
        model_provider_id_override: null,
        effective_model: null,
      };
    }
    return null;
  }, [items]);
  const latestHistoryRun = triageRuns[0] ?? null;
  const activeHistoryRun = triageRuns.find(isOperatorRunActive) ?? null;
  const visibleTriageRun = triageRun ?? activeHistoryRun ?? latestHistoryRun ?? recoveredTriageRun;
  const acknowledgeAllActive = () => {
    if (!active.length) return;
    const ok = window.confirm(`Acknowledge all ${active.length} actionable Attention Items you can see?`);
    if (!ok) return;
    bulkAcknowledge.mutate({ scope: "workspace_visible" }, { onSuccess: () => onSelect(null) });
  };
  const startOperatorSweep = () => {
    if (!sweepable.length || startTriage.isPending) return;
    setCreating(false);
    onSelect(null);
    setOperatorRunOpen(true);
    setTriageOptionsOpen(false);
    startTriage.mutate(
      {
        model_override: triageModel || null,
        model_provider_id_override: triageModel ? triageProviderId ?? null : null,
      },
      {
        onSuccess: (run) => {
          setTriageRun(run);
        },
      },
    );
  };
  return (
    <>
      <div className="flex items-center justify-between px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Radar size={14} />
            Attention Hub
          </div>
          <div className="mt-1 text-xs text-text-muted">
            {attentionBucketSummary(grouped)}
            {activeOccurrenceCount > active.length ? ` · ${plural(activeOccurrenceCount, "occurrence")}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={!active.length || bulkAcknowledge.isPending}
            className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-40"
            onClick={acknowledgeAllActive}
            title="Acknowledge all actionable Attention Items you can see"
          >
            Ack all
          </button>
          <button
            type="button"
            disabled={!sweepable.length && !visibleTriageRun && !startTriage.isPending}
            className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08] disabled:opacity-40 ${
              operatorRunOpen ? "bg-accent/[0.08]" : ""
            }`}
            onClick={() => {
              if (visibleTriageRun || startTriage.isPending || operatorRunOpen) {
                setOperatorRunOpen(true);
                setTriageOptionsOpen(false);
                setCreating(false);
                onSelect(null);
                return;
              }
              setTriageOptionsOpen((value) => !value);
            }}
            title="Configure an operator sweep for untriaged Attention Items"
          >
            {startTriage.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Operator sweep
          </button>
          <button type="button" className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text" onClick={() => setCreating((v) => !v)} title="Create Attention Item">
            <Plus size={16} />
          </button>
          {onClose && (
            <button type="button" className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text" onClick={onClose} title="Close">
              <X size={16} />
            </button>
          )}
        </div>
      </div>
      {triageOptionsOpen && (
        <div className="px-3 pb-2">
          <OperatorTriageSetup
            activeCount={sweepable.length}
            occurrenceCount={sweepable.reduce((total, item) => total + Math.max(1, item.occurrence_count || 1), 0)}
            defaultModel={operatorDefaultModel}
            model={triageModel}
            providerId={triageProviderId}
            pending={startTriage.isPending}
            onModelChange={(model, providerId) => {
              setTriageModel(model);
              setTriageProviderId(model ? providerId ?? null : null);
            }}
            onCancel={() => setTriageOptionsOpen(false)}
            onStart={startOperatorSweep}
          />
        </div>
      )}
      {operatorRunOpen ? (
        <OperatorRunWorkspace
          run={visibleTriageRun}
          runs={triageRuns}
          pending={startTriage.isPending}
          error={startTriage.error}
          grouped={grouped}
          onBack={() => setOperatorRunOpen(false)}
          onSelect={(item) => {
            setOperatorRunOpen(false);
            onSelect(item);
          }}
        />
      ) : creating ? (
        <CreateAttentionForm onCreated={(item) => { setCreating(false); onSelect(item); }} />
      ) : selected ? (
        <AttentionDetail
          item={selected}
          targetItems={selectedTargetItems}
          onSelect={onSelect}
          onBack={() => onSelect(null)}
          onReply={onReply}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <OperatorReviewOverview
            run={visibleTriageRun}
            grouped={grouped}
            onOpenRun={() => {
              setOperatorRunOpen(true);
              setCreating(false);
              onSelect(null);
            }}
            onSelect={onSelect}
            runs={triageRuns}
          />
        </div>
      )}
    </>
  );
}

function OperatorRunWorkspace({
  run,
  runs,
  pending,
  error,
  grouped,
  onBack,
  onSelect,
}: {
  run: AttentionTriageRunResponse | null;
  runs: AttentionTriageRunResponse[];
  pending: boolean;
  error: unknown;
  grouped: {
    review: WorkspaceAttentionItem[];
    triage: WorkspaceAttentionItem[];
    untriaged: WorkspaceAttentionItem[];
    assigned: WorkspaceAttentionItem[];
    processed: WorkspaceAttentionItem[];
    closed: WorkspaceAttentionItem[];
  };
  onBack: () => void;
  onSelect: (item: WorkspaceAttentionItem) => void;
}) {
  const message = error instanceof Error ? error.message : error ? String(error) : null;
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    if (!pending || run) {
      setElapsedMs(0);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedMs(Date.now() - startedAt);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [pending, run]);

  const slowStart = pending && !run && elapsedMs >= 12_000;
  const waitingCopy = slowStart
    ? "The server has not returned the run yet. Existing triage cards remain visible below; this usually means the backend is busy or out of DB connections."
    : "Creating the run and transcript. This panel will attach the live feed as soon as the server returns the session.";

  return (
    <div className="min-h-0 flex-1 overflow-auto px-3 pb-3">
      <div className="sticky top-0 z-10 -mx-3 mb-3 flex items-center justify-between gap-2 bg-surface/95 px-3 pb-2 pt-1 backdrop-blur-sm">
        <button type="button" className="rounded-md px-2 py-1 text-xs text-text-dim hover:bg-surface-overlay/60 hover:text-text" onClick={onBack}>
          Back to Attention
        </button>
        <div className="flex items-center gap-1.5">
          {run && (
            <a href="#operator-review-findings" className="rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-overlay/60 hover:text-text">
              Findings
            </a>
          )}
          {pending && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] text-accent">
              <Loader2 size={11} className="animate-spin" />
              starting
            </span>
          )}
        </div>
      </div>
      {run ? (
        <OperatorTriageRunPanel run={run} />
      ) : (
        <section className="mb-4 space-y-2 rounded-md bg-surface-overlay/35 p-3">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            {pending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            Operator run
          </div>
          <div className="text-sm text-text">
            {message ? "Operator sweep could not start." : slowStart ? "Still waiting for the server..." : "Starting operator sweep..."}
          </div>
          <div className="text-xs leading-5 text-text-muted">
            {message ?? waitingCopy}
          </div>
          {message && (
            <button
              type="button"
              className="rounded-md px-2 py-1.5 text-xs text-accent hover:bg-accent/[0.08]"
              onClick={onBack}
            >
              Back to sweep setup
            </button>
          )}
        </section>
      )}
      <div id="operator-review-findings" className="scroll-mt-14">
        <AttentionLane title="Ready for review" items={grouped.review} onSelect={onSelect} />
      </div>
      <AttentionLane title="In operator triage" items={grouped.triage} onSelect={onSelect} />
      <AttentionLane title="Processed by operator" items={grouped.processed.slice(0, 16)} onSelect={onSelect} />
      <AttentionLane title="Still untriaged" items={[...grouped.untriaged, ...grouped.assigned].slice(0, 16)} onSelect={onSelect} />
      <OperatorRunHistory runs={runs} onSelect={onSelect} />
    </div>
  );
}

function OperatorReviewOverview({
  run,
  grouped,
  onOpenRun,
  onSelect,
  runs,
}: {
  run: AttentionTriageRunResponse | null;
  grouped: AttentionBuckets;
  onOpenRun: () => void;
  onSelect: (item: WorkspaceAttentionItem) => void;
  runs: AttentionTriageRunResponse[];
}) {
  const hasReview = grouped.review.length > 0;
  const hasTriage = grouped.triage.length > 0;
  const hasRun = Boolean(run);
  return (
    <>
      {hasRun && (
        <section className="mb-4 rounded-md bg-surface-overlay/30 px-3 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
                <Sparkles size={13} />
                Operator sweep
              </div>
              <div className="mt-1 truncate text-xs text-text-muted">
                {runStatusLabel(run!)} · {run?.counts?.ready_for_review ?? grouped.review.length} review · {run?.counts?.processed ?? grouped.processed.length} cleared
              </div>
            </div>
            <button
              type="button"
              className="shrink-0 rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08]"
              onClick={onOpenRun}
            >
              Open run
            </button>
          </div>
        </section>
      )}
      {(hasReview || hasTriage) && (
        <section className="mb-4">
          <div className="mb-2 flex items-end justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Operator Review</div>
              <div className="mt-0.5 text-xs text-text-muted">
                Review these findings; cleared items are already out of the main path.
              </div>
            </div>
            <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">{grouped.review.length}</span>
          </div>
          <AttentionLane title="Ready for review" items={grouped.review} onSelect={onSelect} emptyText="No findings need review." />
          {hasTriage && <AttentionLane title="In operator sweep" items={grouped.triage} onSelect={onSelect} />}
        </section>
      )}
      <AttentionLane title="Untriaged" items={grouped.untriaged} onSelect={onSelect} emptyText="No raw issues are waiting for triage." />
      <AttentionLane title="Assigned to bots" items={grouped.assigned} onSelect={onSelect} emptyText="No issues are assigned to normal bots." />
      {grouped.processed.length > 0 && (
        <section className="mb-4 rounded-md bg-surface-raised/30 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
            <span>{grouped.processed.length} cleared by Operator</span>
            <span className="text-text-dim">hidden from review</span>
          </div>
        </section>
      )}
      <OperatorRunHistory runs={runs} onSelect={onSelect} />
    </>
  );
}

function OperatorTriageSetup({
  activeCount,
  occurrenceCount,
  defaultModel,
  model,
  providerId,
  pending,
  onModelChange,
  onCancel,
  onStart,
}: {
  activeCount: number;
  occurrenceCount: number;
  defaultModel: string;
  model: string;
  providerId: string | null;
  pending: boolean;
  onModelChange: (model: string, providerId?: string | null) => void;
  onCancel: () => void;
  onStart: () => void;
}) {
  return (
    <section className="space-y-3 rounded-md bg-surface-overlay/35 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Sparkles size={13} />
            Operator sweep
          </div>
          <div className="mt-1 text-xs text-text-muted">
            Runs across untriaged issues, not just the selected target · {plural(activeCount, "item")} · {plural(occurrenceCount, "occurrence")}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text"
            onClick={onCancel}
          >
            Close
          </button>
          <button
            type="button"
            disabled={!activeCount || pending}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent/10 px-2.5 py-1.5 text-xs font-medium text-accent hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-40"
            onClick={onStart}
          >
            {pending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Start sweep
          </button>
        </div>
      </div>
      <div className="space-y-1.5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Model override</div>
        <LlmModelDropdown
          value={model}
          selectedProviderId={providerId}
          onChange={onModelChange}
          placeholder={`Inherit ${defaultModel}`}
          allowClear
        />
      </div>
    </section>
  );
}

function OperatorTriageRunPanel({ run }: { run: AttentionTriageRunResponse }) {
  const status = runStatusLabel(run);
  const canShowTranscript = Boolean(run.session_id && run.parent_channel_id);
  const counts = run.counts;
  return (
    <section className="mb-5 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Sparkles size={13} />
            Operator sweep
          </div>
          <div className="mt-1 truncate text-xs text-text-muted">
            {plural(run.item_count, "item")} · {run.effective_model || run.model_override || "default model"} · {formatRunTime(run.created_at)}
          </div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] ${
          status === "failed"
            ? "bg-danger/10 text-danger"
            : status === "complete"
              ? "bg-surface-raised text-text-muted"
              : "bg-accent/10 text-accent"
        }`}>{status}</span>
      </div>
      {counts && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-md bg-surface-overlay/45 px-2 py-1.5 text-text-muted"><span className="text-text">{counts.ready_for_review}</span> review</div>
          <div className="rounded-md bg-surface-overlay/45 px-2 py-1.5 text-text-muted"><span className="text-text">{counts.processed}</span> processed</div>
          <div className="rounded-md bg-surface-overlay/45 px-2 py-1.5 text-text-muted"><span className="text-text">{counts.running}</span> running</div>
        </div>
      )}
      {run.error && <div className="rounded-md bg-danger/10 px-3 py-2 text-xs text-danger">{run.error}</div>}
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Transcript evidence</div>
      <div className="relative min-h-[min(76vh,760px)] overflow-hidden" style={{ contain: "paint" }}>
        <div className="absolute inset-0 overflow-hidden">
          {canShowTranscript ? (
            <SessionChatView
              sessionId={run.session_id!}
              parentChannelId={run.parent_channel_id!}
              botId={run.bot_id}
              chatMode="default"
              surface="operator-panel"
              emptyStateComponent={<div className="px-3 py-4 text-xs text-text-dim">Waiting for operator transcript...</div>}
            />
          ) : (
            <div className="px-3 py-4 text-xs text-text-dim">Transcript is not available for this run.</div>
          )}
        </div>
      </div>
    </section>
  );
}

function OperatorRunHistory({ runs, onSelect }: { runs: AttentionTriageRunResponse[]; onSelect: (item: WorkspaceAttentionItem) => void }) {
  if (!runs.length) return null;
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
        <span>Operator history</span>
        <span>{runs.length}</span>
      </div>
      <div className="space-y-2">
        {runs.slice(0, 6).map((run) => {
          const counts = run.counts;
          const reviewItems = (run.items ?? []).filter(isOperatorTriageReadyForReview);
          const processedItems = (run.items ?? []).filter(isOperatorTriageProcessed);
          return (
            <div key={run.task_id} className="rounded-md bg-surface-raised/35 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 text-xs text-text-muted">
                  <span className="font-medium text-text">{formatRunTime(run.created_at)}</span>
                  <span> · {runStatusLabel(run)} · {plural(run.item_count, "item")}</span>
                </div>
                {counts && (
                  <div className="shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                    {counts.ready_for_review} review · {counts.processed} done
                  </div>
                )}
              </div>
              {reviewItems.length > 0 && (
                <div className="mt-2 space-y-1">
                  {reviewItems.slice(0, 3).map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="block w-full truncate rounded px-2 py-1 text-left text-xs text-accent hover:bg-accent/[0.08]"
                      onClick={() => onSelect(item)}
                    >
                      Review: {item.title}
                    </button>
                  ))}
                </div>
              )}
              {reviewItems.length === 0 && processedItems.length > 0 && (
                <div className="mt-1 truncate text-xs text-text-dim">
                  Processed: {processedItems.slice(0, 3).map((item) => item.title).join(", ")}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AttentionLane({
  title,
  items,
  onSelect,
  emptyText = "No items",
}: {
  title: string;
  items: WorkspaceAttentionItem[];
  onSelect: (item: WorkspaceAttentionItem) => void;
  emptyText?: string;
}) {
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
        <span>{title}</span>
        <span>{items.length}</span>
      </div>
      <div className="space-y-1">
        {items.length === 0 ? (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-3 text-xs text-text-dim">{emptyText}</div>
        ) : items.map((item) => {
          const triage = getOperatorTriage(item);
          return (
            <button
              key={item.id}
              type="button"
              className="block w-full rounded-md bg-surface-raised/45 px-3 py-2 text-left hover:bg-surface-overlay/50"
              onClick={() => onSelect(item)}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0 truncate font-medium">{item.title}</span>
                <span className={`shrink-0 text-[10px] ${item.severity === "critical" || item.severity === "error" ? "text-danger" : item.severity === "warning" ? "text-warning" : "text-accent"}`}>
                  {item.severity}
                </span>
              </div>
              <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-text-dim">
                <span className="truncate">{statusLabel(item)} · {item.channel_name ?? item.target_kind}</span>
                {triage?.classification && (
                  <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
                    {triage.classification.replaceAll("_", " ")}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function AttentionEvidence({ item, collapsed }: { item: WorkspaceAttentionItem; collapsed: boolean }) {
  const content = (
    <div className="space-y-3">
      <p className="whitespace-pre-wrap text-sm leading-5 text-text-muted">{item.message}</p>
      {item.assignment_report && (
        <div className="rounded-md bg-accent/[0.08] p-3">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Bot Findings</div>
          <p className="whitespace-pre-wrap text-sm text-text-muted">{item.assignment_report}</p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 text-xs text-text-dim">
        <span>Target: {item.target_kind}</span>
        <span>Count: {item.occurrence_count}</span>
        <span>Channel: {item.channel_name ?? item.channel_id ?? "none"}</span>
        <span>Last: {item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : "unknown"}</span>
      </div>
      {item.latest_correlation_id && (
        <button type="button" className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs font-medium text-accent hover:bg-accent/10" onClick={() => openTraceInspector({ correlationId: item.latest_correlation_id!, title: item.title })}>
          <ExternalLink size={14} />
          Open trace evidence
        </button>
      )}
    </div>
  );
  if (!collapsed) return content;
  return (
    <details className="rounded-md bg-surface-raised/30 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-text-muted">Evidence</summary>
      <div className="mt-3">{content}</div>
    </details>
  );
}

function CreateAttentionForm({ onCreated }: { onCreated: (item: WorkspaceAttentionItem) => void }) {
  const create = useCreateAttentionItem();
  const assign = useAssignAttentionItem();
  const { data: channels = [] } = useChannels();
  const { data: bots = [] } = useBots();
  const assignableBots = useMemo(() => bots.filter((bot) => bot.id !== OPERATOR_BOT_ID), [bots]);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [severity, setSeverity] = useState<AttentionSeverity>("warning");
  const [channelId, setChannelId] = useState("");
  const [botId, setBotId] = useState("");
  const [mode, setMode] = useState<AttentionAssignmentMode>("next_heartbeat");
  const [instructions, setInstructions] = useState("");
  const canSubmit = title.trim().length > 0 && channelId;
  return (
    <form
      className="min-h-0 flex-1 space-y-3 overflow-auto p-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const item = await create.mutateAsync({
          channel_id: channelId,
          target_kind: "channel",
          target_id: channelId,
          title,
          message,
          severity,
          requires_response: true,
        });
        if (botId) {
          const assigned = await assign.mutateAsync({ itemId: item.id, bot_id: botId, mode, instructions });
          onCreated(assigned);
        } else {
          onCreated(item);
        }
      }}
    >
      <input className="w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea className="min-h-28 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Message" value={message} onChange={(e) => setMessage(e.target.value)} />
      <div className="grid grid-cols-2 gap-2">
        <select className="rounded-md border border-input-border bg-input px-2 py-2 text-sm text-text" value={severity} onChange={(e) => setSeverity(e.target.value as AttentionSeverity)}>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
        <select className="rounded-md border border-input-border bg-input px-2 py-2 text-sm text-text" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
          <option value="">Target channel...</option>
          {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
        </select>
      </div>
      <div className="space-y-2 rounded-md bg-surface-raised/45 p-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Assign Bot</div>
        <BotPicker value={botId} onChange={setBotId} bots={assignableBots} allowNone />
        <div className="grid grid-cols-2 gap-2">
          <button type="button" className={`rounded-md px-2 py-1.5 text-xs ${mode === "next_heartbeat" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"}`} onClick={() => setMode("next_heartbeat")}>Next heartbeat</button>
          <button type="button" className={`rounded-md px-2 py-1.5 text-xs ${mode === "run_now" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"}`} onClick={() => setMode("run_now")}>Run now</button>
        </div>
        <textarea className="min-h-20 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Assignment instructions" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
      </div>
      <button type="submit" disabled={!canSubmit || create.isPending || assign.isPending} className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-foreground disabled:opacity-50">
        Create Attention Item
      </button>
    </form>
  );
}

function AttentionDetail({
  item,
  targetItems,
  onSelect,
  onBack,
  onReply,
}: {
  item: WorkspaceAttentionItem;
  targetItems: WorkspaceAttentionItem[];
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  onBack: () => void;
  onReply?: (item: WorkspaceAttentionItem) => void;
}) {
  const acknowledge = useAcknowledgeAttentionItem();
  const bulkAcknowledge = useBulkAcknowledgeAttentionItems();
  const resolve = useResolveAttentionItem();
  const assign = useAssignAttentionItem();
  const triageFeedback = useSubmitAttentionTriageFeedback();
  const { data: bots = [] } = useBots();
  const assignableBots = useMemo(() => bots.filter((bot) => bot.id !== OPERATOR_BOT_ID), [bots]);
  const [botId, setBotId] = useState(item.assigned_bot_id === OPERATOR_BOT_ID ? "" : item.assigned_bot_id ?? "");
  const [mode, setMode] = useState<AttentionAssignmentMode>(item.assignment_mode ?? "next_heartbeat");
  const [instructions, setInstructions] = useState(item.assignment_instructions ?? "");
  const workflowState = getAttentionWorkflowState(item);
  const operatorReviewed = workflowState === "operator_review" || workflowState === "processed";
  useEffect(() => {
    setBotId(item.assigned_bot_id === OPERATOR_BOT_ID ? "" : item.assigned_bot_id ?? "");
    setMode(item.assignment_mode ?? "next_heartbeat");
    setInstructions(item.assignment_instructions ?? "");
  }, [item.id, item.assigned_bot_id, item.assignment_mode, item.assignment_instructions]);

  const currentIndex = Math.max(0, targetItems.findIndex((candidate) => candidate.id === item.id));
  const targetCount = Math.max(targetItems.length, 1);
  const nextActiveItem = targetItems.find((candidate) => candidate.id !== item.id) ?? null;
  const previousItem = targetItems[currentIndex - 1] ?? null;
  const nextItem = targetItems[currentIndex + 1] ?? null;
  const finishCurrent = () => {
    if (nextActiveItem) onSelect(nextActiveItem);
    else onBack();
  };
  const acknowledgeTarget = () => {
    bulkAcknowledge.mutate({
      scope: "target",
      target_kind: item.target_kind,
      target_id: item.target_id,
      channel_id: item.channel_id,
    }, {
      onSuccess: () => onBack(),
    });
  };

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-auto px-3 pb-3 pt-1">
      <button type="button" className="rounded-md px-2 py-1 text-xs text-text-dim hover:bg-surface-overlay/60 hover:text-text" onClick={onBack}>
        Back to {operatorReviewed ? "Operator Review" : "all issues"}
      </button>

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
              {operatorReviewed ? "Review target" : "Target"}
            </div>
            <div className="mt-1 flex min-w-0 items-center gap-2">
              <span className="truncate text-base font-semibold text-text">{targetLabel(item)}</span>
              <span className="shrink-0 rounded-full bg-surface-overlay px-2 py-0.5 text-xs font-medium text-text-muted">
                {currentIndex + 1} of {targetCount} issue{targetCount === 1 ? "" : "s"}
              </span>
            </div>
          </div>
          {targetCount > 1 && (
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="rounded-md px-2 py-1.5 text-xs font-medium text-text-muted hover:bg-surface-overlay/60 hover:text-text disabled:opacity-40"
                disabled={bulkAcknowledge.isPending}
                onClick={acknowledgeTarget}
              >
                Ack target
              </button>
              <button
                type="button"
                disabled={!previousItem}
                className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay/60 hover:text-text disabled:opacity-40"
                onClick={() => previousItem && onSelect(previousItem)}
              >
                Prev
              </button>
              <button
                type="button"
                disabled={!nextItem}
                className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay/60 hover:text-text disabled:opacity-40"
                onClick={() => nextItem && onSelect(nextItem)}
              >
                Next
              </button>
            </div>
          )}
        </div>
        {targetCount > 1 && (
          <div className="space-y-1">
            {targetItems.map((candidate, index) => (
              <button
                key={candidate.id}
                type="button"
                className={`relative flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-xs ${
                  candidate.id === item.id
                    ? "bg-accent/[0.08] text-text before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent"
                    : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                }`}
                onClick={() => onSelect(candidate)}
              >
                <span className="min-w-0 truncate">
                  {index + 1}. {candidate.title}
                </span>
                <span className={`shrink-0 text-[10px] ${severityTextClass(candidate)}`}>
                  {candidate.severity}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div>
          {operatorReviewed && (
            <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">
              <Sparkles size={13} />
              Operator Review
            </div>
          )}
          <h2 className="text-lg font-medium text-text">{item.title}</h2>
          <div className="mt-1 text-xs text-text-muted">{item.severity} · {statusLabel(item)} · {item.source_type}</div>
        </div>
        <OperatorTriageCard
          item={item}
          isPending={triageFeedback.isPending || acknowledge.isPending || resolve.isPending}
          onFeedback={(verdict, note, route) => triageFeedback.mutate({ itemId: item.id, verdict, note, route })}
          onAcknowledge={() => acknowledge.mutate(item.id, { onSuccess: finishCurrent })}
          onResolve={() => resolve.mutate(item.id, { onSuccess: finishCurrent })}
        />
        <AttentionEvidence item={item} collapsed={operatorReviewed} />
      </section>

      <div className="flex flex-wrap gap-2">
        {onReply && (
          <button type="button" className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-accent hover:bg-accent/10" onClick={() => onReply(item)}>
            <MessageSquare size={15} />
            Reply
          </button>
        )}
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay hover:text-text"
          disabled={acknowledge.isPending}
          onClick={() => acknowledge.mutate(item.id, { onSuccess: finishCurrent })}
        >
          <Check size={15} />
          Acknowledge
        </button>
        <button type="button" className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay hover:text-text" disabled={resolve.isPending} onClick={() => resolve.mutate(item.id, { onSuccess: finishCurrent })}>
          Resolve
        </button>
      </div>

      <section className="space-y-2 rounded-md bg-surface-raised/20 p-2">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80"><Bot size={13} /> Send this issue to a bot</div>
          <div className="mt-1 text-xs text-text-dim">Optional follow-up for issue {currentIndex + 1}. Operator sweep handles the whole queue.</div>
        </div>
        <BotPicker value={botId} onChange={setBotId} bots={assignableBots} allowNone />
        <div className="grid grid-cols-2 gap-2 rounded-md bg-surface-overlay/35 p-0.5">
          <button type="button" className={`rounded px-2 py-1.5 text-xs font-medium ${mode === "next_heartbeat" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"}`} onClick={() => setMode("next_heartbeat")}>Next heartbeat</button>
          <button type="button" className={`rounded px-2 py-1.5 text-xs font-medium ${mode === "run_now" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"}`} onClick={() => setMode("run_now")}>Run now</button>
        </div>
        <textarea className="min-h-16 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Instructions for the selected bot" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        <button type="button" disabled={!botId || assign.isPending} className="rounded-md bg-accent/[0.08] px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.12] disabled:opacity-50" onClick={() => assign.mutate({ itemId: item.id, bot_id: botId, mode, instructions })}>
          Send to bot
        </button>
      </section>
    </div>
  );
}

function OperatorTriageCard({
  item,
  isPending,
  onFeedback,
  onAcknowledge,
  onResolve,
}: {
  item: WorkspaceAttentionItem;
  isPending: boolean;
  onFeedback: (verdict: "confirmed" | "wrong" | "rerouted", note?: string | null, route?: string | null) => void;
  onAcknowledge: () => void;
  onResolve: () => void;
}) {
  const triage = getOperatorTriage(item);
  if (!triage) return null;
  const route = triage.route ? operatorRouteLabel(triage.route) : null;
  const suggestedAction = humanizeOperatorAction(triage.suggested_action);
  const confirm = () => onFeedback("confirmed");
  const markWrong = () => {
    const note = window.prompt("What should the operator remember next time?", triage.summary ?? "");
    if (note === null) return;
    onFeedback("wrong", note);
  };
  const changeRoute = () => {
    const note = window.prompt("Routing correction for future operator sweeps", triage.route ? `Suggested route should not be ${operatorRouteLabel(triage.route)}.` : "");
    if (note === null) return;
    onFeedback("rerouted", note, triage.route ?? null);
  };
  return (
    <div className="space-y-3 rounded-md bg-surface-overlay/35 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <Sparkles size={13} />
          Operator triage
        </div>
        {triage.classification && (
          <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
            {triage.classification.replaceAll("_", " ")}
          </span>
        )}
        {route && <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-accent">{route}</span>}
      </div>
      {triage.summary && <p className="whitespace-pre-wrap text-sm leading-5 text-text-muted">{triage.summary}</p>}
      {suggestedAction && (
        <p className="text-sm leading-5 text-text">
          <span className="text-text-dim">Next: </span>
          {suggestedAction}
        </p>
      )}
      <p className="text-xs leading-5 text-text-dim">Accepting trains future sweeps. Acknowledge or resolve removes this review item.</p>
      {triage.review?.verdict ? (
        <div className="text-xs text-text-dim">Review saved: {triage.review.verdict}</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-accent hover:bg-accent/[0.08] disabled:opacity-50" onClick={confirm}>
            Accept finding
          </button>
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-50" onClick={onAcknowledge}>
            Acknowledge
          </button>
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-50" onClick={onResolve}>
            Resolve
          </button>
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-50" onClick={markWrong}>
            Mark wrong
          </button>
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-50" onClick={changeRoute}>
            Change routing
          </button>
        </div>
      )}
    </div>
  );
}

function operatorRouteLabel(route: string): string {
  if (route === "developer_channel") return "Code fix";
  if (route === "owner_channel") return "Owner follow-up";
  if (route === "automation") return "Automation fix";
  if (route === "acknowledge") return "Can acknowledge";
  if (route === "user_decision") return "User decision";
  if (route === "benign") return "Benign/noise";
  return route.replaceAll("_", " ");
}

function humanizeOperatorAction(action?: string | null): string {
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
