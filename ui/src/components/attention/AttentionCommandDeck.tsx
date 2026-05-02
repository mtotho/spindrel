import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
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
  Pencil,
  Radar,
  RotateCcw,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";

import {
  getOperatorTriage,
  getToolErrorReviewSignal,
  useAcknowledgeAttentionItem,
  useAssignAttentionItem,
  useAttentionTriageRuns,
  useBulkAcknowledgeAttentionItems,
  useResolveAttentionItem,
  useStartAttentionTriageRun,
  useSubmitAttentionTriageFeedback,
  useWorkspaceAttentionBrief,
  WORKSPACE_ATTENTION_BRIEF_KEY,
  WORKSPACE_ATTENTION_KEY,
  type AgentReadinessAutofixItem,
  type AttentionBriefResponse,
  type AttentionFixPack,
  type AttentionAssignmentMode,
  type AttentionTriageRunResponse,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";
import { applyAgentReadinessRepair, fetchAgentCapabilities } from "../../api/hooks/useAgentCapabilities";
import { useBots } from "../../api/hooks/useBots";
import { useProjectChannels, useProjects } from "../../api/hooks/useProjects";
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
  loading?: boolean;
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

function getBotReport(item: WorkspaceAttentionItem): any | null {
  const report = item.evidence?.report_issue;
  return report && typeof report === "object" ? report : null;
}

function getIssueIntake(item: WorkspaceAttentionItem): any | null {
  const intake = item.evidence?.issue_intake;
  return intake && typeof intake === "object" ? intake : null;
}

function getIssueTriage(item: WorkspaceAttentionItem): any | null {
  const triage = item.evidence?.issue_triage;
  return triage && typeof triage === "object" ? triage : null;
}

function toolSignalClass(tone: "muted" | "warning" | "danger"): string {
  if (tone === "danger") return "bg-danger/10 text-danger-muted";
  if (tone === "warning") return "bg-warning/10 text-warning";
  return "bg-surface-raised text-text-muted";
}

function decisionLabel(item: WorkspaceAttentionItem): string {
  if (getBotReport(item)) return "Bot-reported issue";
  const toolSignal = getToolErrorReviewSignal(item);
  if (toolSignal) return toolSignal.label;
  if (getAttentionWorkflowState(item) === "operator_review") return "Operator finding";
  return "Needs review";
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

function sortDeckItems(mode: DeckMode, items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  const sorted = sortAttention(items);
  if (mode !== "review") return sorted;
  return sorted.sort((a, b) => Number(Boolean(getBotReport(a))) - Number(Boolean(getBotReport(b))));
}

function SkeletonBlock({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-skeleton/10 ${className}`} />;
}

function AttentionCommandDeckSkeleton() {
  return (
    <div className="flex h-full min-h-0 flex-col text-text" data-testid="attention-command-deck-loading">
      <div className="shrink-0 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <SkeletonBlock className="h-3 w-40" />
            <SkeletonBlock className="h-4 w-72 max-w-full" />
          </div>
          <SkeletonBlock className="h-8 w-36" />
        </div>
        <div className="mt-3 rounded-md bg-surface-overlay/30 px-3 py-3">
          <SkeletonBlock className="h-3 w-24" />
          <SkeletonBlock className="mt-3 h-4 w-56 max-w-full" />
          <SkeletonBlock className="mt-2 h-3 w-full max-w-xl" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="rounded-md bg-surface-overlay/25 px-3 py-2">
              <SkeletonBlock className="h-3 w-16" />
              <SkeletonBlock className="mt-2 h-5 w-8" />
            </div>
          ))}
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 px-3 pb-3 md:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="min-h-0 rounded-md bg-surface-overlay/20 px-3 py-3">
          <div className="grid grid-cols-2 gap-1.5">
            {[0, 1, 2, 3].map((index) => <SkeletonBlock key={index} className="h-10" />)}
          </div>
          <div className="mt-5 space-y-2">
            {[0, 1, 2, 3, 4, 5].map((index) => <SkeletonBlock key={index} className="h-14" />)}
          </div>
        </aside>
        <main className="min-h-0 rounded-md bg-surface-overlay/20 px-4 py-4">
          <SkeletonBlock className="h-3 w-36" />
          <SkeletonBlock className="mt-3 h-8 w-80 max-w-full" />
          <SkeletonBlock className="mt-3 h-4 w-96 max-w-full" />
          <SkeletonBlock className="mt-6 h-32 w-full max-w-3xl" />
          <SkeletonBlock className="mt-5 h-24 w-full max-w-3xl" />
        </main>
      </div>
    </div>
  );
}

export function AttentionCommandDeck({
  loading = false,
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
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mode, setModeState] = useState<DeckMode>(() => initialMode ?? "review");
  const [notice, setNotice] = useState<string | null>(null);
  const [autofixError, setAutofixError] = useState<string | null>(null);
  const [applyingAutofixId, setApplyingAutofixId] = useState<string | null>(null);
  const [staleAutofixIds, setStaleAutofixIds] = useState<string[]>([]);
  const [runModePinned, setRunModePinned] = useState(false);
  const [sweepStarting, setSweepStarting] = useState(false);
  const [localSelectedRunId, setLocalSelectedRunId] = useState<string | null>(null);
  const detailRef = useRef<HTMLElement | null>(null);
  const buckets = useMemo(() => bucketAttentionItems(items), [items]);
  const sweepable = useMemo(() => sweepCandidateItems(items), [items]);
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const { data: runs = [] } = useAttentionTriageRuns({ limit: 16, refetchInterval: mode === "runs" ? 5_000 : 15_000 });
  const { data: brief } = useWorkspaceAttentionBrief({ channelId, refetchInterval: 15_000 });
  const startTriage = useStartAttentionTriageRun();
  const hasActiveRun = runs.some((run) => {
    const status = runStatusLabel(run);
    return status === "queued" || status === "running";
  });
  const selectedRunLoaded = Boolean(selectedRunId && runs.some((run) => run.task_id === selectedRunId));
  const sweepBusy = startTriage.isPending || sweepStarting || hasActiveRun;
  const counts = {
    review: buckets.review.length,
    botReports: buckets.review.filter((item) => getBotReport(item)).length,
    inbox: buckets.untriaged.length + buckets.assigned.length,
    running: buckets.triage.length,
    cleared: buckets.processed.length,
    closed: buckets.closed.length,
  };
  const activeList = useMemo(() => sortDeckItems(mode, modeItems(mode, buckets)), [buckets, mode]);
  const firstReview = useMemo(() => sortAttention(buckets.review)[0] ?? null, [buckets.review]);
  const displayItem = selected ?? activeList[0] ?? null;
  const activeRunId = selectedRunId ?? localSelectedRunId ?? runs[0]?.task_id ?? null;
  const selectedRun = activeRunId ? runs.find((run) => run.task_id === activeRunId) ?? null : null;

  const setDeckMode = (next: DeckMode, notify = true) => {
    setRunModePinned(next === "runs");
    setModeState(next);
    if (notify) onModeChange?.(next);
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
    if (hasActiveRun || selectedRunLoaded) setSweepStarting(false);
  }, [hasActiveRun, selectedRunLoaded]);

  useEffect(() => {
    if (!selected) return;
    const state = getAttentionWorkflowState(selected);
    if (state === "operator_review" || state === "bot_report") setDeckMode("review", false);
    else if (state === "processed" || state === "closed") setDeckMode("cleared", false);
    else if (state === "in_sweep") setDeckMode("runs", false);
    else setDeckMode("inbox", false);
  }, [selected?.id]);

  const startSweep = () => {
    setNotice(null);
    if (sweepBusy) {
      onSelect(null);
      setDeckMode("runs");
      setNotice("Operator sweep is already running. Stay here for the sweep history.");
      return;
    }
    if (!sweepable.length) {
      setDeckMode(buckets.review.length ? "review" : "inbox");
      setNotice(buckets.review.length ? "No new signals to sweep. Review the existing findings." : "No raw signals are ready for Operator.");
      return;
    }
    onSelect(null);
    setDeckMode("runs");
    setSweepStarting(true);
    startTriage.mutate({}, {
      onSuccess: (run) => {
        setLocalSelectedRunId(run.task_id);
        onRunSelect?.(run.task_id);
        setNotice("Operator sweep started. Stay on the sweep history while findings arrive.");
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

  const selectBriefItem = (itemId?: string | null) => {
    if (!itemId) return;
    const item = items.find((candidate) => candidate.id === itemId);
    if (!item) return;
    setDeckMode(getAttentionWorkflowState(item) === "operator_review" ? "review" : "inbox");
    onSelect(item);
    focusDetail();
  };

  const copyFixPrompt = async (pack: AttentionFixPack) => {
    try {
      await navigator.clipboard.writeText(pack.prompt);
      setNotice(`Copied fix prompt for ${pack.title}.`);
    } catch {
      setNotice("Could not copy the fix prompt from this browser.");
    }
  };

  const openBotReadiness = (request: AgentReadinessAutofixItem) => {
    if (!request.bot_id) return;
    navigate(`/admin/bots/${request.bot_id}`);
  };

  const applyAutofixRequest = async (request: AgentReadinessAutofixItem) => {
    setAutofixError(null);
    setNotice(null);
    const marker = request.receipt_id || `${request.bot_id}:${request.action_id}`;
    if (!request.bot_id || !request.action_id) {
      setAutofixError("This repair request is missing a bot or action id.");
      return;
    }
    setApplyingAutofixId(marker);
    try {
      const manifest = await fetchAgentCapabilities({
        botId: request.bot_id,
        channelId: request.channel_id,
        sessionId: request.session_id,
        includeEndpoints: false,
        includeSchemas: false,
        maxTools: 40,
      });
      const action = (manifest.doctor.proposed_actions || []).find((candidate) => candidate.id === request.action_id);
      if (!action || action.apply.type !== "bot_patch") {
        setStaleAutofixIds((current) => current.includes(marker) ? current : [...current, marker]);
        setNotice("That repair request is stale. Open the bot readiness panel for the current finding.");
        return;
      }
      const result = await applyAgentReadinessRepair({
        action,
        botId: request.bot_id,
        channelId: request.channel_id,
        sessionId: request.session_id,
        actor: { kind: "human_ui", surface: "mission_control_review" },
        approvalRef: "mission_control_review",
        beforeDoctorStatus: manifest.doctor.status,
      });
      if (result.status === "blocked" || result.status === "stale") {
        if (result.status === "stale") {
          setStaleAutofixIds((current) => current.includes(marker) ? current : [...current, marker]);
        }
        setAutofixError(result.preflight.reason || "This repair could not be applied.");
        return;
      }
      setStaleAutofixIds((current) => current.filter((id) => id !== marker));
      setNotice(result.findingResolved === false ? "Repair applied, but readiness still needs review." : "Repair applied and verified.");
      void qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
      void qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      void qc.invalidateQueries({ queryKey: ["agent-capabilities"] });
      void qc.invalidateQueries({ queryKey: ["bots", request.bot_id] });
      void qc.invalidateQueries({ queryKey: ["bot-editor", request.bot_id] });
      void qc.invalidateQueries({ queryKey: ["bots"] });
      void qc.invalidateQueries({ queryKey: ["admin-bots"] });
    } catch (error) {
      setAutofixError(error instanceof Error ? error.message : "Could not apply this readiness repair.");
    } finally {
      setApplyingAutofixId(null);
    }
  };

  const clearableCount = counts.review + counts.inbox;
  const bulkAcknowledge = useBulkAcknowledgeAttentionItems();
  const clearActiveAttention = () => {
    if (!clearableCount || bulkAcknowledge.isPending) return;
    const scope = channelId ? "this channel" : "the workspace";
    if (!window.confirm(`Clear ${clearableCount} active attention item${clearableCount === 1 ? "" : "s"} from ${scope}? New occurrences will still show up later.`)) {
      return;
    }
    bulkAcknowledge.mutate(
      { scope: "workspace_visible", channel_id: channelId ?? null },
      {
        onSuccess: (res) => {
          onSelect(null);
          setNotice(`Cleared ${res.count} active attention item${res.count === 1 ? "" : "s"}.`);
        },
        onError: () => setNotice("Could not clear attention items. Try again from the Attention deck."),
      },
    );
  };

  const whatNow = (() => {
    const viewingFirstReview = Boolean(firstReview && mode === "review" && displayItem?.id === firstReview.id);
    if (sweepBusy) {
      return {
        eyebrow: "Operator sweep",
        title: "Watch the active sweep",
        detail: "Raw signals are being classified into findings or cleared receipts.",
        action: "View run log",
        icon: <Loader2 size={15} className="animate-spin" />,
        onClick: () => setDeckMode("runs"),
      };
    }
    if (brief && brief.next_action.kind !== "empty") {
      const itemId = brief.next_action.item_id;
      const alreadyViewing = Boolean(itemId && displayItem?.id === itemId);
      return {
        eyebrow: "Mission brief",
        title: brief.next_action.title,
        detail: brief.next_action.description,
        action: alreadyViewing ? null : brief.next_action.action_label || "Open",
        icon: <Sparkles size={15} />,
        onClick: () => {
          if (brief.next_action.kind === "sweep") startSweep();
          else if (brief.next_action.kind === "autofix") setNotice("Review the Autofix queue below the brief metrics.");
          else selectBriefItem(itemId);
        },
      };
    }
    if (counts.review > 0) {
      return {
        eyebrow: viewingFirstReview ? "Current finding" : "Next decision",
        title: viewingFirstReview ? "Decide on this finding" : "Open the first finding",
        detail: viewingFirstReview
          ? `${counts.review} finding${counts.review === 1 ? "" : "s"}${counts.botReports ? `, including ${counts.botReports} bot-reported issue${counts.botReports === 1 ? "" : "s"}` : ""}. Accept it, clear it, or mark it wrong.`
          : `${counts.review} finding${counts.review === 1 ? "" : "s"}${counts.botReports ? `, including ${counts.botReports} bot-reported issue${counts.botReports === 1 ? "" : "s"}` : ""}, waiting for a decision.`,
        action: viewingFirstReview ? null : "Review first finding",
        icon: <Sparkles size={15} />,
        onClick: () => focusReviewFinding(),
      };
    }
    if (counts.inbox > 0) {
      return {
        eyebrow: "Signals",
      title: "Sweep raw signals",
      detail: `${counts.inbox} signal${counts.inbox === 1 ? "" : "s"} can be classified before you review them manually.`,
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
  const detailOwnsFocus = mode === "runs" || mode === "cleared" || Boolean(displayItem);
  const showWhatNow = !detailOwnsFocus;
  const visibleBrief = !detailOwnsFocus ? brief : null;
  const selectRunFromQueue = (runId: string | null) => {
    setLocalSelectedRunId(runId);
    onRunSelect?.(runId);
  };

  if (loading && !items.length) {
    return <AttentionCommandDeckSkeleton />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col text-text">
      <div className="shrink-0 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
              <Radar size={13} />
              Mission Control Review
            </div>
            <div className="mt-1 text-sm leading-5 text-text-muted">
              {channelId ? "Channel-filtered" : "Workspace"} review · {counts.review} findings
              {counts.botReports ? ` (${counts.botReports} bot report${counts.botReports === 1 ? "" : "s"})` : ""} · {counts.inbox} signals · {counts.cleared} cleared
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              disabled={!clearableCount || bulkAcknowledge.isPending}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-text-muted hover:bg-surface-overlay/60 hover:text-text disabled:opacity-40"
              onClick={clearActiveAttention}
            >
              {bulkAcknowledge.isPending ? <Loader2 size={14} className="animate-spin" /> : <Archive size={14} />}
              Clear all
            </button>
            <button
              type="button"
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-text-muted hover:bg-surface-overlay/60 hover:text-text"
              onClick={() => setDeckMode("runs")}
            >
              <Clock size={14} />
              Sweeps
            </button>
            <button
              type="button"
              disabled={sweepBusy || !sweepable.length}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-md bg-accent/[0.08] px-3 text-xs font-medium text-accent hover:bg-accent/[0.12] disabled:opacity-50"
              onClick={startSweep}
            >
              {sweepBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {sweepBusy ? "Sweep running" : sweepable.length ? "Sweep signals" : "Nothing to sweep"}
            </button>
          </div>
        </div>
        {notice && (
          <div className="mt-3 rounded-md bg-surface-overlay/45 px-3 py-2 text-xs text-text-muted">
            {notice}
          </div>
        )}
        {showWhatNow && (
          <div className="mt-3 rounded-md bg-surface-overlay/35 px-3 py-3" data-testid="attention-command-deck-what-now">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">{whatNow.eyebrow}</div>
                <div className="mt-1 text-sm font-medium text-text">{whatNow.title}</div>
                <div className="mt-1 text-xs leading-5 text-text-muted">{whatNow.detail}</div>
              </div>
              {whatNow.action ? (
                <button
                  type="button"
                  className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-md bg-accent/[0.08] px-3 text-sm font-medium text-accent hover:bg-accent/[0.12]"
                  onClick={whatNow.onClick}
                >
                  {whatNow.icon}
                  {whatNow.action}
                </button>
              ) : null}
            </div>
          </div>
        )}
        {visibleBrief && (
          <BriefSummary
            brief={visibleBrief}
            onOpenItem={selectBriefItem}
            onCopyFixPrompt={copyFixPrompt}
            onApplyAutofix={applyAutofixRequest}
            onOpenAutofix={openBotReadiness}
            applyingAutofixId={applyingAutofixId}
            staleAutofixIds={staleAutofixIds}
            autofixError={autofixError}
          />
        )}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 px-3 pb-3 md:grid-cols-[300px_minmax(0,1fr)]">
        <DeckQueue
          mode={mode}
          counts={counts}
          runCount={runs.length}
          runs={runs}
          selectedRunId={activeRunId}
          items={activeList}
          selectedId={displayItem?.id ?? null}
          onModeChange={(next) => {
            setDeckMode(next);
            onSelect(null);
          }}
          onSelect={onSelect}
          onRunSelect={selectRunFromQueue}
        />
        <main ref={detailRef} tabIndex={-1} className="min-h-0 overflow-y-auto rounded-md bg-surface-overlay/20 px-4 py-4 outline-none">
          {mode === "runs" ? (
            <RunLogWorkspace pending={sweepBusy} selectedRun={selectedRun} activeRunId={activeRunId} />
          ) : displayItem ? (
            <DeckItemDetail item={displayItem} onReply={onReply} />
          ) : (
            <EmptyDeckState mode={mode} />
          )}
        </main>
      </div>
    </div>
  );
}

function DeckQueue({
  mode,
  counts,
  runCount,
  runs,
  selectedRunId,
  items,
  selectedId,
  onModeChange,
  onSelect,
  onRunSelect,
}: {
  mode: DeckMode;
  counts: { review: number; botReports: number; inbox: number; running: number; cleared: number; closed: number };
  runCount: number;
  runs: AttentionTriageRunResponse[];
  selectedRunId: string | null;
  items: WorkspaceAttentionItem[];
  selectedId: string | null;
  onModeChange: (mode: DeckMode) => void;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  onRunSelect: (runId: string | null) => void;
}) {
  const title = mode === "inbox" ? "Signals" : mode === "review" ? "Findings" : mode === "cleared" ? "Cleared" : "Sweep history";
  return (
    <aside className="min-h-0 overflow-y-auto rounded-md bg-surface-overlay/20 px-3 py-3">
      <div>
        <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Needs action</div>
        <div className="space-y-1">
          <ModeButton active={mode === "review"} icon={<Sparkles size={14} />} label="Findings" count={counts.review} onClick={() => onModeChange("review")} />
          <ModeButton active={mode === "inbox"} icon={<Inbox size={14} />} label="Signals" count={counts.inbox} onClick={() => onModeChange("inbox")} />
        </div>
        <div className="mb-1 mt-4 px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Review history</div>
        <div className="space-y-1">
          <ModeButton active={mode === "runs"} icon={<Clock size={14} />} label="Sweeps" count={runCount || counts.running} onClick={() => onModeChange("runs")} />
          <ModeButton active={mode === "cleared"} icon={<Archive size={14} />} label="Cleared" count={counts.cleared + counts.closed} onClick={() => onModeChange("cleared")} />
        </div>
      </div>

      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
          <span>{title}</span>
          <span>{mode === "runs" ? runCount : items.length}</span>
        </div>
        <div className="space-y-1">
          {mode === "runs" ? runs.length ? runs.map((run) => (
            <button
              key={run.task_id}
              type="button"
              className={`block w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                selectedRunId === run.task_id ? "bg-accent/[0.08] text-text" : "text-text-muted hover:bg-surface-overlay/55 hover:text-text"
              }`}
              onClick={() => onRunSelect(run.task_id)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{formatRunTime(run.created_at)}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-dim">{runStatusLabel(run)}</span>
              </div>
              <div className="mt-1 truncate text-xs text-text-dim">
                {run.item_count} items · {run.counts?.ready_for_review ?? 0} review · {run.counts?.processed ?? 0} cleared
              </div>
            </button>
          )) : (
            <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/35 px-3 py-6 text-center text-xs text-text-dim">
              No Operator sweeps yet.
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
                <span className="truncate">{decisionLabel(item)} · {targetLabel(item)}</span>
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
      className={`flex min-h-9 w-full items-center justify-between gap-2 rounded-md px-2.5 text-left text-xs transition-colors ${
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


function BriefSummary({
  brief,
  onOpenItem,
  onCopyFixPrompt,
  onApplyAutofix,
  onOpenAutofix,
  applyingAutofixId,
  staleAutofixIds,
  autofixError,
}: {
  brief: AttentionBriefResponse;
  onOpenItem: (itemId?: string | null) => void;
  onCopyFixPrompt: (pack: AttentionFixPack) => void;
  onApplyAutofix: (request: AgentReadinessAutofixItem) => void;
  onOpenAutofix: (request: AgentReadinessAutofixItem) => void;
  applyingAutofixId: string | null;
  staleAutofixIds: string[];
  autofixError: string | null;
}) {
  const primaryFixPack = brief.fix_packs[0] ?? null;
  const primaryDecision = brief.decisions[0] ?? null;
  const primaryBlocker = brief.blockers[0] ?? null;
  const hasBriefWork = Boolean(brief.autofix_queue.length || primaryFixPack || primaryDecision || primaryBlocker || brief.quiet_digest.count);

  if (!hasBriefWork) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2" data-testid="attention-brief-summary">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <BriefMetric label="Autofix" value={brief.summary.autofix} tone={brief.summary.autofix ? "accent" : "muted"} />
        <BriefMetric label="Fix packs" value={brief.summary.fix_packs} tone={brief.summary.fix_packs ? "accent" : "muted"} />
        <BriefMetric label="Decisions" value={brief.summary.decisions} tone={brief.summary.decisions ? "warning" : "muted"} />
        <BriefMetric label="Blockers" value={brief.summary.blockers} tone={brief.summary.blockers ? "danger" : "muted"} />
        <BriefMetric label="Quiet" value={brief.summary.quiet} tone="muted" />
      </div>
      {brief.autofix_queue.length > 0 && (
        <AutofixQueue
          requests={brief.autofix_queue}
          onApply={onApplyAutofix}
          onOpen={onOpenAutofix}
          applyingId={applyingAutofixId}
          staleIds={staleAutofixIds}
          error={autofixError}
        />
      )}
      <div className="grid gap-2 lg:grid-cols-3">
        {primaryFixPack && (
          <BriefTile
            eyebrow={`${primaryFixPack.count} item${primaryFixPack.count === 1 ? "" : "s"} grouped`}
            title={primaryFixPack.title}
            body={primaryFixPack.summary}
            actionLabel="Open evidence"
            secondaryLabel="Copy fix prompt"
            onAction={() => onOpenItem(primaryFixPack.item_ids[0])}
            onSecondary={() => onCopyFixPrompt(primaryFixPack)}
          />
        )}
        {primaryDecision && (
          <BriefTile
            eyebrow="Decision"
            title={primaryDecision.title}
            body={primaryDecision.summary}
            actionLabel={primaryDecision.action_label || "Make decision"}
            onAction={() => onOpenItem(primaryDecision.item_ids[0] ?? primaryDecision.id)}
          />
        )}
        {primaryBlocker && (
          <BriefTile
            eyebrow="Blocker"
            title={primaryBlocker.title}
            body={primaryBlocker.summary}
            actionLabel={primaryBlocker.action_label || "Inspect blocker"}
            onAction={() => onOpenItem(primaryBlocker.item_ids[0] ?? primaryBlocker.id)}
          />
        )}
      </div>
    </div>
  );
}

function AutofixQueue({
  requests,
  onApply,
  onOpen,
  applyingId,
  staleIds,
  error,
}: {
  requests: AgentReadinessAutofixItem[];
  onApply: (request: AgentReadinessAutofixItem) => void;
  onOpen: (request: AgentReadinessAutofixItem) => void;
  applyingId: string | null;
  staleIds: string[];
  error: string | null;
}) {
  return (
    <section className="rounded-md bg-surface-overlay/30 px-3 py-3" data-testid="agent-readiness-autofix-queue">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">Agent readiness autofix</div>
          <div className="mt-1 text-sm font-medium text-text">
            {requests.length} queued repair{requests.length === 1 ? "" : "s"}
          </div>
        </div>
        {error && <div className="text-xs text-warning">{error}</div>}
      </div>
      <div className="mt-2 space-y-1.5">
        {requests.slice(0, 3).map((request) => {
          const marker = request.receipt_id || `${request.bot_id}:${request.action_id}`;
          const isStale = staleIds.includes(marker);
          const isApplying = applyingId === marker;
          return (
            <div key={marker} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-raised/35 px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-text">{request.summary || "Requested readiness repair"}</div>
                <div className="mt-0.5 text-xs text-text-dim">
                  {(request.finding_code || "readiness").replaceAll("_", " ")} · requested by {request.requested_by || "unknown actor"}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {isStale && <span className="rounded-full bg-surface-overlay px-2 py-1 text-[10px] font-medium text-text-muted">Stale</span>}
                <button
                  type="button"
                  className="rounded-md px-2 py-1.5 text-xs font-medium text-text-muted hover:bg-surface-overlay/60 hover:text-text"
                  onClick={() => onOpen(request)}
                >
                  Open bot
                </button>
                <button
                  type="button"
                  disabled={isApplying || isStale}
                  className="inline-flex min-h-7 items-center gap-1.5 rounded-md bg-accent/[0.08] px-2.5 text-xs font-medium text-accent hover:bg-accent/[0.12] disabled:opacity-50"
                  onClick={() => onApply(request)}
                >
                  {isApplying ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  {isApplying ? "Applying" : "Apply"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function BriefMetric({ label, value, tone }: { label: string; value: number; tone: "accent" | "warning" | "danger" | "muted" }) {
  const toneClass = tone === "accent" ? "text-accent" : tone === "warning" ? "text-warning" : tone === "danger" ? "text-danger" : "text-text-muted";
  return (
    <div className="rounded-md bg-surface-overlay/30 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function BriefTile({
  eyebrow,
  title,
  body,
  actionLabel,
  secondaryLabel,
  onAction,
  onSecondary,
}: {
  eyebrow: string;
  title: string;
  body: string;
  actionLabel: string;
  secondaryLabel?: string;
  onAction: () => void;
  onSecondary?: () => void;
}) {
  return (
    <section className="min-w-0 rounded-md bg-surface-overlay/30 px-3 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">{eyebrow}</div>
      <div className="mt-1 truncate text-sm font-medium text-text">{title}</div>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-text-muted">{body}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" className="rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08]" onClick={onAction}>
          {actionLabel}
        </button>
        {secondaryLabel && onSecondary && (
          <button type="button" className="rounded-md px-2 py-1.5 text-xs font-medium text-text-muted hover:bg-surface-overlay/60 hover:text-text" onClick={onSecondary}>
            {secondaryLabel}
          </button>
        )}
      </div>
    </section>
  );
}

function DeckItemDetail({ item, onReply }: { item: WorkspaceAttentionItem; onReply?: (item: WorkspaceAttentionItem) => void }) {
  const acknowledge = useAcknowledgeAttentionItem();
  const resolve = useResolveAttentionItem();
  const triageFeedback = useSubmitAttentionTriageFeedback();
  const triage = getOperatorTriage(item);
  const botReport = getBotReport(item);
  const workflowState = getAttentionWorkflowState(item);
  const reviewed = workflowState === "operator_review";
  const readonly = workflowState === "processed" || workflowState === "closed";
  const suggestedAction = humanizeSuggestedAction(triage?.suggested_action);
  const toolSignal = getToolErrorReviewSignal(item);
  const reviewVerdict = triage?.review?.verdict;

  return (
    <article className="mx-auto max-w-3xl">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            {botReport ? "Bot-reported issue" : reviewed ? "Operator finding" : "Raw signal"}
          </div>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-text">{item.title}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-muted">
            <span>{item.severity} · {attentionItemTriageLabel(item)} · {targetLabel(item)} · {formatItemTime(item)}</span>
            {toolSignal && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] ${toolSignalClass(toolSignal.tone)}`}>
                {toolSignal.label}
              </span>
            )}
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
              Reply in channel
            </button>
          )}
          {!readonly && (
            <>
              <button type="button" className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-text-muted hover:bg-surface-overlay/60 hover:text-text" onClick={() => acknowledge.mutate(item.id)}>
                <Check size={15} />
                Clear
              </button>
              <button type="button" className="inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-text-muted hover:bg-surface-overlay/60 hover:text-text" onClick={() => resolve.mutate(item.id)}>
                <XCircle size={15} />
                Resolve
              </button>
            </>
          )}
        </div>
      </div>

      {toolSignal && (
        <section className="mb-4 rounded-md bg-surface-overlay/35 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] ${toolSignalClass(toolSignal.tone)}`}>
              {toolSignal.label}
            </span>
            {toolSignal.errorKind && (
              <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
                {toolSignal.errorKind.replaceAll("_", " ")}
              </span>
            )}
            {toolSignal.errorCode && (
              <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
                {toolSignal.errorCode.replaceAll("_", " ")}
              </span>
            )}
          </div>
          {toolSignal.nextAction && (
            <p className="mt-3 text-sm leading-6 text-text">
              <span className="text-text-dim">Next: </span>
              {toolSignal.nextAction}
            </p>
          )}
        </section>
      )}

      {botReport && (
        <section className="mb-4 rounded-md bg-accent/[0.08] px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">
              <Bot size={13} />
              Bot report
            </span>
            {botReport.category && (
              <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
                {String(botReport.category).replaceAll("_", " ")}
              </span>
            )}
          </div>
          <p className="mt-3 text-sm leading-6 text-text-muted">
            Reported by {botReport.reported_by ?? item.source_id}. This came from a task or heartbeat because the bot found something it could not safely finish alone.
          </p>
          {botReport.suggested_action && (
            <p className="mt-3 text-sm leading-6 text-text">
              <span className="text-text-dim">Next: </span>
              {humanizeSuggestedAction(botReport.suggested_action)}
            </p>
          )}
        </section>
      )}

      {triage && (
        <section className="mb-4 rounded-md bg-surface-overlay/35 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">
              <Sparkles size={13} />
              Operator finding
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
              {reviewVerdict === "confirmed" ? (
                <span className="rounded-md bg-accent/[0.08] px-2.5 py-1.5 text-sm text-accent">Finding kept</span>
              ) : (
                <button type="button" className="rounded-md px-2.5 py-1.5 text-sm text-accent hover:bg-accent/[0.08]" onClick={() => triageFeedback.mutate({ itemId: item.id, verdict: "confirmed" })}>
                  Keep finding
                </button>
              )}
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
                Change next action
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
  selectedRun,
  activeRunId,
}: {
  pending: boolean;
  selectedRun: AttentionTriageRunResponse | null;
  activeRunId: string | null;
}) {
  const waitingForSelectedRun = Boolean(pending && activeRunId && !selectedRun);

  return (
    <div className="mx-auto max-w-5xl" data-testid="attention-run-workspace">
      {pending && (
        <section className="mb-3 rounded-md bg-accent/[0.08] px-4 py-3 text-sm text-accent">
          <span className="inline-flex items-center gap-2">
            <Loader2 size={15} className="animate-spin" />
            Starting Operator sweep
          </span>
        </section>
      )}

      {waitingForSelectedRun ? (
        <StartingSweepReceipt taskId={activeRunId} />
      ) : selectedRun ? (
        <RunReceipt run={selectedRun} />
      ) : pending ? (
        <StartingSweepReceipt />
      ) : (
        <div className="rounded-md bg-surface-raised/45 px-4 py-10 text-center text-sm text-text-dim">
          Start a sweep to create a receipt.
        </div>
      )}
    </div>
  );
}

function StartingSweepReceipt({ taskId }: { taskId?: string | null }) {
  return (
    <section className="relative space-y-4 rounded-md bg-surface-raised/75 px-4 py-4 before:absolute before:left-4 before:top-0 before:h-[2px] before:w-10 before:rounded-full before:bg-emphasis/70" data-testid="attention-run-starting">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">Operator sweep</div>
          <div className="mt-1 inline-flex items-center gap-2 text-lg font-semibold text-text">
            <Loader2 size={15} className="animate-spin" />
            Starting Operator sweep
          </div>
          <p className="mt-1 text-xs leading-5 text-text-muted">
            Creating the run receipt and attaching the Operator feed. This view will update without showing an older sweep.
          </p>
        </div>
        {taskId ? <span className="max-w-48 truncate text-[10px] uppercase tracking-[0.08em] text-text-dim">{taskId}</span> : null}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <SkeletonBlock className="h-9" />
        <SkeletonBlock className="h-9" />
        <SkeletonBlock className="h-9" />
      </div>
      <section className="min-h-[260px] rounded-md bg-surface-raised/35 px-4 py-6">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Operator feed</div>
        <div className="mt-6 rounded-md bg-surface-overlay/25 px-3 py-4 text-center text-sm text-text-dim">Waiting for the first run event...</div>
      </section>
    </section>
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
  const runItems = runBucketItems(run);
  const reviewCount = run.counts?.ready_for_review ?? runItems.review.length;
  const clearedCount = run.counts?.processed ?? runItems.cleared.length;
  const runningCount = run.counts?.running ?? runItems.running.length;
  return (
    <div className="relative space-y-4 rounded-md bg-surface-raised/75 px-4 py-4 before:absolute before:left-4 before:top-0 before:h-[2px] before:w-10 before:rounded-full before:bg-emphasis/70" data-testid="attention-run-receipt">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">Sweep receipt</div>
          <h2 className="mt-1 text-2xl font-semibold text-text">Operator sweep</h2>
          <div className="mt-1 text-sm text-text-muted">
            {run.item_count} items · {run.effective_model || run.model_override || "default model"} · {formatRunTime(run.created_at)}
          </div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.08em] ${
          status === "failed" ? "bg-danger/10 text-danger-muted" : status === "running" || status === "queued" ? "bg-accent/[0.08] text-accent" : "bg-surface-overlay text-text-muted"
        }`}>{status}</span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-sm">
        <div className="rounded-md bg-surface-overlay/35 px-3 py-2"><span className="font-medium text-text">{reviewCount}</span> review</div>
        <div className="rounded-md bg-surface-overlay/35 px-3 py-2"><span className="font-medium text-text">{clearedCount}</span> cleared</div>
        <div className="rounded-md bg-surface-overlay/35 px-3 py-2"><span className="font-medium text-text">{runningCount}</span> running</div>
      </div>

      {run.error && (
        <div className="rounded-md bg-danger/10 px-4 py-3 text-sm text-danger-muted">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em]">Failed</div>
          <div className="mt-1">{run.error}</div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <RunItemList title="Ready for review" items={runItems.review} empty="No review items from this run." />
        <RunItemList title="Cleared by Operator" items={runItems.cleared} empty="No cleared items from this run." />
      </div>

      <OperatorRunFeed run={run} status={status} />
    </div>
  );
}

function OperatorRunFeed({ run, status }: { run: AttentionTriageRunResponse; status: string }) {
  const hasTranscript = Boolean(run.session_id && run.parent_channel_id);
  const stillRunning = status === "queued" || status === "running";
  return (
    <section className="rounded-md bg-surface-overlay/25 px-4 py-3" data-testid="attention-run-feed">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Operator feed</div>
          <p className="mt-1 text-xs leading-5 text-text-muted">
            {hasTranscript
              ? "Live session transcript for this sweep."
              : stillRunning
                ? "Waiting for the Operator session to attach. The run receipt above will keep updating."
                : "No transcript was attached to this run."}
          </p>
        </div>
        <span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">{status}</span>
      </div>
      {hasTranscript ? (
        <div className="mt-3 overflow-hidden rounded-md bg-surface-raised/35" style={{ contain: "paint" }}>
          <div className="relative h-[min(62vh,680px)] min-h-[420px]">
            <SessionChatView
              sessionId={run.session_id!}
              parentChannelId={run.parent_channel_id!}
              botId={run.bot_id}
              chatMode="terminal"
              surface="operator-panel"
              emptyStateComponent={<div className="px-4 py-8 text-sm text-text-dim">Waiting for Operator feed...</div>}
            />
          </div>
        </div>
      ) : (
        <div className="mt-3 rounded-md bg-surface-raised/25 px-3 py-4 text-sm text-text-dim">
            <span className="inline-flex items-center gap-2">
              {stillRunning ? <Loader2 size={15} className="animate-spin" /> : null}
              {stillRunning ? "Waiting for Operator feed..." : "No Operator feed is available for this run."}
            </span>
        </div>
      )}
    </section>
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
