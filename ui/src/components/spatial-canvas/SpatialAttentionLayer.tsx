import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bot, Check, ExternalLink, Loader2, MessageSquare, Plus, Radar, Sparkles, X } from "lucide-react";
import {
  getOperatorTriage,
  isOperatorTriageProcessed,
  isOperatorTriageReadyForReview,
  isOperatorTriageRunning,
  useAcknowledgeAttentionItem,
  useAssignAttentionItem,
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
import { useBots } from "../../api/hooks/useBots";
import { useChannels } from "../../api/hooks/useChannels";
import { BotPicker } from "../shared/BotPicker";
import { LlmModelDropdown } from "../shared/LlmModelDropdown";
import { useUIStore } from "../../stores/ui";
import { openTraceInspector } from "../../stores/traceInspector";
import { SessionChatView } from "../chat/SessionChatView";

const severityRank: Record<string, number> = { info: 0, warning: 1, error: 2, critical: 3 };

function signalClass(item: WorkspaceAttentionItem): string {
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
  if (item.assignment_status === "running") return "running";
  if (item.assignment_status === "assigned") return "assigned";
  if (item.assignment_status === "reported") return "reported";
  if (item.status === "responded") return "responded";
  if (item.status === "acknowledged") return "acknowledged";
  if (item.requires_response) return "needs reply";
  return item.status;
}

function activeItems(items: WorkspaceAttentionItem[]): WorkspaceAttentionItem[] {
  return items.filter(isActiveAttentionItem);
}

export function shouldSurfaceAttentionOnMap(item: WorkspaceAttentionItem): boolean {
  if (!isActiveAttentionItem(item)) return false;
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

interface SignalProps {
  items: WorkspaceAttentionItem[];
  scale: number;
  onSelect: (item: WorkspaceAttentionItem) => void;
}

export function SpatialAttentionSignal({ items, scale, onSelect }: SignalProps) {
  const active = activeItems(items).filter(shouldSurfaceAttentionOnMap).sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
  if (!active.length) return null;
  const primary = active[0];
  const count = active.length;
  const inv = 1 / Math.max(scale, 0.05);
  const occurrenceCount = active.reduce((total, item) => total + Math.max(1, item.occurrence_count || 1), 0);
  const urgent = active.some((item) => item.source_type === "system" || item.severity === "critical");
  const label = count === 1
    ? `${targetLabel(primary)}: ${primary.title} - ${statusLabel(primary)}${occurrenceCount > 1 ? ` (${occurrenceCount} occurrences)` : ""}`
    : `${targetLabel(primary)}: ${plural(count, "active issue")} (${occurrenceCount} occurrences)`;
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

function laneFor(item: WorkspaceAttentionItem): "review" | "triage" | "needs" | "assigned" | "system" | "processed" {
  if (isOperatorTriageRunning(item)) return "triage";
  if (isOperatorTriageReadyForReview(item)) return "review";
  if (isOperatorTriageProcessed(item)) return "processed";
  if (item.status === "resolved" || item.status === "acknowledged") return "processed";
  if (item.source_type === "system") return "system";
  if (item.assigned_bot_id) return "assigned";
  return "needs";
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
  const [triageOptionsOpen, setTriageOptionsOpen] = useState(false);
  const [triageModel, setTriageModel] = useState("");
  const [triageProviderId, setTriageProviderId] = useState<string | null>(null);
  const bulkAcknowledge = useBulkAcknowledgeAttentionItems();
  const startTriage = useStartAttentionTriageRun();
  const { data: bots = [] } = useBots();
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const operatorBot = bots.find((bot) => bot.id === "orchestrator");
  const operatorDefaultModel = operatorBot?.model ?? "operator default";
  const active = activeItems(items);
  const activeOccurrenceCount = active.reduce((total, item) => total + Math.max(1, item.occurrence_count || 1), 0);
  const selectedTargetItems = useMemo(() => {
    if (!selected) return [];
    const key = targetKey(selected);
    return active
      .filter((item) => targetKey(item) === key)
      .sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
  }, [active, selected]);
  const grouped = useMemo(() => {
    const lanes = {
      review: [] as WorkspaceAttentionItem[],
      triage: [] as WorkspaceAttentionItem[],
      needs: [] as WorkspaceAttentionItem[],
      assigned: [] as WorkspaceAttentionItem[],
      system: [] as WorkspaceAttentionItem[],
      processed: [] as WorkspaceAttentionItem[],
    };
    for (const item of items) lanes[laneFor(item)].push(item);
    for (const lane of Object.values(lanes)) lane.sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
    return lanes;
  }, [items]);
  const acknowledgeAllActive = () => {
    if (!active.length) return;
    const ok = window.confirm(`Acknowledge all ${active.length} active Attention Items you can see?`);
    if (!ok) return;
    bulkAcknowledge.mutate({ scope: "workspace_visible" }, { onSuccess: () => onSelect(null) });
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
            {plural(active.length, "active item")} · {plural(activeOccurrenceCount, "occurrence")}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={!active.length || bulkAcknowledge.isPending}
            className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-40"
            onClick={acknowledgeAllActive}
            title="Acknowledge all active Attention Items you can see"
          >
            Ack all
          </button>
          <button
            type="button"
            disabled={!active.length || startTriage.isPending}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-accent hover:bg-accent/[0.08] disabled:opacity-40"
            onClick={() => setTriageOptionsOpen((value) => !value)}
            title="Configure an operator triage run for all active Attention Items"
          >
            {startTriage.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Operator
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
      {creating ? (
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
          {triageOptionsOpen && (
            <OperatorTriageSetup
              activeCount={active.length}
              occurrenceCount={activeOccurrenceCount}
              defaultModel={operatorDefaultModel}
              model={triageModel}
              providerId={triageProviderId}
              pending={startTriage.isPending}
              onModelChange={(model, providerId) => {
                setTriageModel(model);
                setTriageProviderId(model ? providerId ?? null : null);
              }}
              onStart={() => {
                startTriage.mutate(
                  {
                    model_override: triageModel || null,
                    model_provider_id_override: triageModel ? triageProviderId ?? null : null,
                  },
                  {
                    onSuccess: (run) => {
                      setTriageRun(run);
                      setTriageOptionsOpen(false);
                    },
                  },
                );
              }}
            />
          )}
          {triageRun && <OperatorTriageRunPanel run={triageRun} />}
          <AttentionLane title="Ready for review" items={grouped.review} onSelect={onSelect} />
          <AttentionLane title="In operator triage" items={grouped.triage} onSelect={onSelect} />
          <AttentionLane title="Unprocessed" items={grouped.needs} onSelect={onSelect} />
          <AttentionLane title="Assigned" items={grouped.assigned} onSelect={onSelect} />
          <AttentionLane title="System Errors" items={grouped.system} onSelect={onSelect} />
          <AttentionLane title="Processed by operator" items={grouped.processed.slice(0, 16)} onSelect={onSelect} />
        </div>
      )}
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
  onStart,
}: {
  activeCount: number;
  occurrenceCount: number;
  defaultModel: string;
  model: string;
  providerId: string | null;
  pending: boolean;
  onModelChange: (model: string, providerId?: string | null) => void;
  onStart: () => void;
}) {
  return (
    <section className="mb-4 space-y-3 rounded-md bg-surface-overlay/35 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Sparkles size={13} />
            Operator triage
          </div>
          <div className="mt-1 text-xs text-text-muted">
            Read-only classify + report · {plural(activeCount, "active item")} · {plural(occurrenceCount, "occurrence")}
          </div>
        </div>
        <button
          type="button"
          disabled={!activeCount || pending}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-accent/10 px-2.5 py-1.5 text-xs font-medium text-accent hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-40"
          onClick={onStart}
        >
          {pending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          Start
        </button>
      </div>
      <div className="space-y-1.5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Model</div>
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
  return (
    <section className="mb-4 space-y-2 rounded-md bg-surface-overlay/35 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
            <Sparkles size={13} />
            Operator run
          </div>
          <div className="mt-1 truncate text-xs text-text-muted">
            {plural(run.item_count, "item")} · {run.effective_model || run.model_override || "default model"}
          </div>
        </div>
        <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] text-accent">live</span>
      </div>
      <div className="relative h-64 min-h-0 overflow-hidden rounded-md bg-surface-raised/70" style={{ contain: "paint" }}>
        <div className="absolute inset-0 overflow-hidden">
          <SessionChatView
            sessionId={run.session_id}
            parentChannelId={run.parent_channel_id}
            botId={run.bot_id}
            chatMode="default"
            emptyStateComponent={<div className="px-3 py-4 text-xs text-text-dim">Waiting for operator transcript...</div>}
          />
        </div>
      </div>
    </section>
  );
}

function AttentionLane({ title, items, onSelect }: { title: string; items: WorkspaceAttentionItem[]; onSelect: (item: WorkspaceAttentionItem) => void }) {
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
        <span>{title}</span>
        <span>{items.length}</span>
      </div>
      <div className="space-y-1">
        {items.length === 0 ? (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-3 text-xs text-text-dim">No items</div>
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

function CreateAttentionForm({ onCreated }: { onCreated: (item: WorkspaceAttentionItem) => void }) {
  const create = useCreateAttentionItem();
  const assign = useAssignAttentionItem();
  const { data: channels = [] } = useChannels();
  const { data: bots = [] } = useBots();
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
        <BotPicker value={botId} onChange={setBotId} bots={bots} allowNone />
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
  const [botId, setBotId] = useState(item.assigned_bot_id ?? "");
  const [mode, setMode] = useState<AttentionAssignmentMode>(item.assignment_mode ?? "next_heartbeat");
  const [instructions, setInstructions] = useState(item.assignment_instructions ?? "");
  useEffect(() => {
    setBotId(item.assigned_bot_id ?? "");
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
    <div className="min-h-0 flex-1 space-y-4 overflow-auto px-3 pb-4 pt-2 md:px-4">
      <button type="button" className="rounded-md px-2 py-1 text-xs text-text-dim hover:bg-surface-overlay/60 hover:text-text" onClick={onBack}>Back to all issues</button>

      <section className="space-y-3 rounded-md bg-surface-raised/50 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">Target</div>
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

      <section className="space-y-3 rounded-md bg-surface-raised/55 p-3">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80"><Bot size={13} /> Assignment</div>
        <BotPicker value={botId} onChange={setBotId} bots={bots} allowNone />
        <div className="grid grid-cols-2 gap-2 rounded-md bg-surface-overlay/45 p-0.5">
          <button type="button" className={`rounded px-2 py-1.5 text-xs font-medium ${mode === "next_heartbeat" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"}`} onClick={() => setMode("next_heartbeat")}>Next heartbeat</button>
          <button type="button" className={`rounded px-2 py-1.5 text-xs font-medium ${mode === "run_now" ? "bg-accent/[0.08] text-accent" : "text-text-muted hover:bg-surface-overlay/60 hover:text-text"}`} onClick={() => setMode("run_now")}>Run now</button>
        </div>
        <textarea className="min-h-24 w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none placeholder:text-text-dim focus:border-accent" placeholder="Assignment instructions" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        <button type="button" disabled={!botId || assign.isPending} className="rounded-md bg-accent/[0.08] px-3 py-2 text-sm font-medium text-accent hover:bg-accent/[0.12] disabled:opacity-50" onClick={() => assign.mutate({ itemId: item.id, bot_id: botId, mode, instructions })}>
          Assign
        </button>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-medium text-text">{item.title}</h2>
          <div className="mt-1 text-xs text-text-muted">{item.severity} · {statusLabel(item)} · {item.source_type}</div>
        </div>
        <OperatorTriageCard
          item={item}
          isPending={triageFeedback.isPending}
          onFeedback={(verdict, note, route) => triageFeedback.mutate({ itemId: item.id, verdict, note, route })}
        />
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
    </div>
  );
}

function OperatorTriageCard({
  item,
  isPending,
  onFeedback,
}: {
  item: WorkspaceAttentionItem;
  isPending: boolean;
  onFeedback: (verdict: "confirmed" | "wrong" | "rerouted", note?: string | null, route?: string | null) => void;
}) {
  const triage = getOperatorTriage(item);
  if (!triage) return null;
  const route = triage.route ? triage.route.replaceAll("_", " ") : null;
  const confirm = () => onFeedback("confirmed");
  const markWrong = () => {
    const note = window.prompt("What should the operator remember next time?", triage.summary ?? "");
    if (note === null) return;
    onFeedback("wrong", note);
  };
  const reroute = () => {
    const note = window.prompt("Route note for future triage", "Treat this as developer-channel work.");
    if (note === null) return;
    onFeedback("rerouted", note, "developer_channel");
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
      {triage.suggested_action && (
        <p className="text-sm leading-5 text-text">
          <span className="text-text-dim">Next: </span>
          {triage.suggested_action}
        </p>
      )}
      {triage.review?.verdict ? (
        <div className="text-xs text-text-dim">Review saved: {triage.review.verdict}</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-accent hover:bg-accent/[0.08] disabled:opacity-50" onClick={confirm}>
            Confirm
          </button>
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-50" onClick={markWrong}>
            Wrong
          </button>
          <button type="button" disabled={isPending} className="rounded-md px-2 py-1.5 text-xs text-text-muted hover:bg-surface-overlay hover:text-text disabled:opacity-50" onClick={reroute}>
            Route to dev
          </button>
        </div>
      )}
    </div>
  );
}
