import { useMemo, useState } from "react";
import { AlertTriangle, Bot, Check, ExternalLink, MessageSquare, Plus, Radar, ShieldAlert, X } from "lucide-react";
import {
  useAcknowledgeAttentionItem,
  useAssignAttentionItem,
  useCreateAttentionItem,
  useResolveAttentionItem,
  useWorkspaceAttention,
  type AttentionAssignmentMode,
  type AttentionSeverity,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";
import { useBots } from "../../api/hooks/useBots";
import { useChannels } from "../../api/hooks/useChannels";
import { BotPicker } from "../shared/BotPicker";
import { useUIStore } from "../../stores/ui";
import { openTraceInspector } from "../../stores/traceInspector";

const severityRank: Record<string, number> = { info: 0, warning: 1, error: 2, critical: 3 };

function markerClass(item: WorkspaceAttentionItem): string {
  if (item.source_type === "system") return "border-danger/60 bg-danger/15 text-danger";
  if (item.severity === "critical" || item.severity === "error") return "border-danger/60 bg-danger/15 text-danger";
  if (item.severity === "warning") return "border-warning/70 bg-warning/15 text-warning";
  return "border-accent/50 bg-accent/10 text-accent";
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
  return items.filter((item) => item.status !== "resolved");
}

interface BadgeStackProps {
  items: WorkspaceAttentionItem[];
  scale: number;
  onSelect: (item: WorkspaceAttentionItem) => void;
}

export function SpatialAttentionBadgeStack({ items, scale, onSelect }: BadgeStackProps) {
  const visible = activeItems(items).sort((a, b) => severityRank[b.severity] - severityRank[a.severity]).slice(0, 3);
  if (!visible.length) return null;
  const inv = 1 / Math.max(scale, 0.05);
  const size = 28;
  return (
    <div
      className="pointer-events-none absolute -right-3 -top-3 z-[50] flex items-center"
      style={{ transform: `scale(${inv})`, transformOrigin: "top right" }}
    >
      {visible.map((item, idx) => {
        const system = item.source_type === "system";
        return (
          <button
            key={item.id}
            type="button"
            className={`pointer-events-auto -ml-1 flex items-center justify-center rounded-full border shadow-sm transition-transform duration-100 hover:scale-110 ${markerClass(item)}`}
            style={{ width: size, height: size, zIndex: 20 - idx }}
            title={`${item.title} - ${statusLabel(item)}`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(item);
            }}
          >
            {system ? <ShieldAlert size={14} /> : <AlertTriangle size={14} />}
            {item.occurrence_count > 1 && idx === 0 && (
              <span className="absolute -right-1 -top-1 rounded-full bg-surface-overlay px-1 text-[10px] leading-4 text-text">
                {item.occurrence_count}
              </span>
            )}
          </button>
        );
      })}
      {activeItems(items).length > visible.length && (
        <span className="pointer-events-auto -ml-1 rounded-full border border-surface-border bg-surface-raised px-1.5 text-[10px] leading-5 text-text-muted">
          +{activeItems(items).length - visible.length}
        </span>
      )}
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
  const { data: items } = useWorkspaceAttention();
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

function laneFor(item: WorkspaceAttentionItem): "needs" | "assigned" | "system" | "recent" {
  if (item.status === "resolved" || item.assignment_status === "reported") return "recent";
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
  const [creating, setCreating] = useState(false);
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const grouped = useMemo(() => {
    const lanes = { needs: [] as WorkspaceAttentionItem[], assigned: [] as WorkspaceAttentionItem[], system: [] as WorkspaceAttentionItem[], recent: [] as WorkspaceAttentionItem[] };
    for (const item of items) lanes[laneFor(item)].push(item);
    for (const lane of Object.values(lanes)) lane.sort((a, b) => severityRank[b.severity] - severityRank[a.severity]);
    return lanes;
  }, [items]);
  if (!open) return null;
  return (
    <aside
      className="fixed bottom-4 right-4 top-16 z-[70] flex w-[460px] max-w-[calc(100vw-2rem)] flex-col rounded-md bg-surface-raised/95 text-sm text-text shadow-xl ring-1 ring-surface-border backdrop-blur"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.08em] text-text-dim">
            <Radar size={14} />
            Attention Hub
          </div>
          <div className="mt-1 text-xs text-text-muted">{activeItems(items).length} active items</div>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text" onClick={() => setCreating((v) => !v)} title="Create Attention Item">
            <Plus size={16} />
          </button>
          <button type="button" className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text" onClick={onClose} title="Close">
            <X size={16} />
          </button>
        </div>
      </div>
      {creating ? (
        <CreateAttentionForm onCreated={(item) => { setCreating(false); onSelect(item); }} />
      ) : selected ? (
        <AttentionDetail item={selected} onBack={() => onSelect(null)} onReply={onReply} />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <AttentionLane title="Needs Reply" items={grouped.needs} onSelect={onSelect} />
          <AttentionLane title="Assigned" items={grouped.assigned} onSelect={onSelect} />
          <AttentionLane title="System Errors" items={grouped.system} onSelect={onSelect} />
          <AttentionLane title="Recent / Reported" items={grouped.recent} onSelect={onSelect} />
        </div>
      )}
    </aside>
  );
}

function AttentionLane({ title, items, onSelect }: { title: string; items: WorkspaceAttentionItem[]; onSelect: (item: WorkspaceAttentionItem) => void }) {
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.08em] text-text-dim">
        <span>{title}</span>
        <span>{items.length}</span>
      </div>
      <div className="space-y-1">
        {items.length === 0 ? (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-3 text-xs text-text-dim">No items</div>
        ) : items.map((item) => (
          <button
            key={item.id}
            type="button"
            className="block w-full rounded-md border border-surface-border bg-surface/70 px-3 py-2 text-left hover:border-accent/40 hover:bg-surface-overlay/50"
            onClick={() => onSelect(item)}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0 truncate font-medium">{item.title}</span>
              <span className={`shrink-0 text-[10px] ${item.severity === "critical" || item.severity === "error" ? "text-danger" : item.severity === "warning" ? "text-warning" : "text-accent"}`}>
                {item.severity}
              </span>
            </div>
            <div className="mt-1 truncate text-xs text-text-dim">{statusLabel(item)} · {item.channel_name ?? item.target_kind}</div>
          </button>
        ))}
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
      <input className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea className="min-h-28 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent" placeholder="Message" value={message} onChange={(e) => setMessage(e.target.value)} />
      <div className="grid grid-cols-2 gap-2">
        <select className="rounded-md border border-surface-border bg-surface px-2 py-2 text-sm" value={severity} onChange={(e) => setSeverity(e.target.value as AttentionSeverity)}>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
        </select>
        <select className="rounded-md border border-surface-border bg-surface px-2 py-2 text-sm" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
          <option value="">Target channel...</option>
          {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
        </select>
      </div>
      <div className="space-y-2 rounded-md border border-surface-border p-3">
        <div className="text-[11px] uppercase tracking-[0.08em] text-text-dim">Assign Bot</div>
        <BotPicker value={botId} onChange={setBotId} bots={bots} allowNone />
        <div className="grid grid-cols-2 gap-2">
          <button type="button" className={`rounded-md border px-2 py-1.5 text-xs ${mode === "next_heartbeat" ? "border-accent text-accent" : "border-surface-border text-text-muted"}`} onClick={() => setMode("next_heartbeat")}>Next heartbeat</button>
          <button type="button" className={`rounded-md border px-2 py-1.5 text-xs ${mode === "run_now" ? "border-accent text-accent" : "border-surface-border text-text-muted"}`} onClick={() => setMode("run_now")}>Run now</button>
        </div>
        <textarea className="min-h-20 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent" placeholder="Assignment instructions" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
      </div>
      <button type="submit" disabled={!canSubmit || create.isPending || assign.isPending} className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-foreground disabled:opacity-50">
        Create Attention Item
      </button>
    </form>
  );
}

function AttentionDetail({ item, onBack, onReply }: { item: WorkspaceAttentionItem; onBack: () => void; onReply?: (item: WorkspaceAttentionItem) => void }) {
  const acknowledge = useAcknowledgeAttentionItem();
  const resolve = useResolveAttentionItem();
  const assign = useAssignAttentionItem();
  const { data: bots = [] } = useBots();
  const [botId, setBotId] = useState(item.assigned_bot_id ?? "");
  const [mode, setMode] = useState<AttentionAssignmentMode>(item.assignment_mode ?? "next_heartbeat");
  const [instructions, setInstructions] = useState(item.assignment_instructions ?? "");
  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
      <button type="button" className="text-xs text-text-dim hover:text-text" onClick={onBack}>Back to list</button>
      <div>
        <h2 className="text-lg font-medium">{item.title}</h2>
        <div className="mt-1 text-xs text-text-muted">{item.severity} · {statusLabel(item)} · {item.source_type}</div>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-5 text-text-muted">{item.message}</p>
      {item.assignment_report && (
        <div className="rounded-md border border-accent/25 bg-accent/10 p-3">
          <div className="mb-1 text-[11px] uppercase tracking-[0.08em] text-accent">Bot Findings</div>
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
        <button type="button" className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-accent hover:bg-accent/10" onClick={() => openTraceInspector({ correlationId: item.latest_correlation_id!, title: item.title })}>
          <ExternalLink size={14} />
          Open trace evidence
        </button>
      )}
      <div className="space-y-2 rounded-md border border-surface-border p-3">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.08em] text-text-dim"><Bot size={13} /> Assignment</div>
        <BotPicker value={botId} onChange={setBotId} bots={bots} allowNone />
        <div className="grid grid-cols-2 gap-2">
          <button type="button" className={`rounded-md border px-2 py-1.5 text-xs ${mode === "next_heartbeat" ? "border-accent text-accent" : "border-surface-border text-text-muted"}`} onClick={() => setMode("next_heartbeat")}>Next heartbeat</button>
          <button type="button" className={`rounded-md border px-2 py-1.5 text-xs ${mode === "run_now" ? "border-accent text-accent" : "border-surface-border text-text-muted"}`} onClick={() => setMode("run_now")}>Run now</button>
        </div>
        <textarea className="min-h-20 w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent" placeholder="Assignment instructions" value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        <button type="button" disabled={!botId || assign.isPending} className="rounded-md border border-accent/40 px-3 py-2 text-sm text-accent disabled:opacity-50" onClick={() => assign.mutate({ itemId: item.id, bot_id: botId, mode, instructions })}>
          Assign
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {onReply && (
          <button type="button" className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-accent hover:bg-accent/10" onClick={() => onReply(item)}>
            <MessageSquare size={15} />
            Reply
          </button>
        )}
        <button type="button" className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay hover:text-text" disabled={acknowledge.isPending} onClick={() => acknowledge.mutate(item.id)}>
          <Check size={15} />
          Acknowledge
        </button>
        <button type="button" className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay hover:text-text" disabled={resolve.isPending} onClick={() => resolve.mutate(item.id, { onSuccess: onBack })}>
          Resolve
        </button>
      </div>
    </div>
  );
}
