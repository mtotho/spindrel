import { AlertTriangle, Check, ExternalLink, MessageSquare, ShieldAlert, X } from "lucide-react";
import {
  useAcknowledgeAttentionItem,
  useMarkAttentionResponded,
  useResolveAttentionItem,
  type WorkspaceAttentionItem,
} from "../../api/hooks/useWorkspaceAttention";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import { openTraceInspector } from "../../stores/traceInspector";

interface SpatialAttentionLayerProps {
  items: WorkspaceAttentionItem[];
  nodes: SpatialNode[];
  scale: number;
  worldTransform: string;
  selectedId: string | null;
  onSelect: (item: WorkspaceAttentionItem | null) => void;
  onReply: (item: WorkspaceAttentionItem) => void;
}

const severityRank: Record<string, number> = { info: 0, warning: 1, error: 2, critical: 3 };

function markerClass(item: WorkspaceAttentionItem): string {
  if (item.source_type === "system") return "border-danger/60 bg-danger/15 text-danger";
  if (item.severity === "critical" || item.severity === "error") return "border-danger/60 bg-danger/15 text-danger";
  if (item.severity === "warning") return "border-warning/70 bg-warning/15 text-warning";
  return "border-accent/50 bg-accent/10 text-accent";
}

function statusLabel(item: WorkspaceAttentionItem): string {
  if (item.status === "responded") return "responded";
  if (item.status === "acknowledged") return "acknowledged";
  if (item.requires_response) return "needs reply";
  return item.status;
}

export function SpatialAttentionLayer({
  items,
  nodes,
  scale,
  worldTransform,
  selectedId,
  onSelect,
  onReply,
}: SpatialAttentionLayerProps) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const targetNode = (item: WorkspaceAttentionItem): SpatialNode | null => {
    if (item.target_node_id) return nodeById.get(item.target_node_id) ?? null;
    return nodes.find((node) => {
      if (item.target_kind === "channel") return node.channel_id === item.target_id;
      if (item.target_kind === "bot") return node.bot_id === item.target_id;
      if (item.target_kind === "widget") return node.widget_pin_id === item.target_id;
      return false;
    }) ?? null;
  };

  const rendered = items
    .filter((item) => item.status !== "resolved")
    .map((item) => ({ item, node: targetNode(item) }))
    .filter((entry): entry is { item: WorkspaceAttentionItem; node: SpatialNode } => Boolean(entry.node))
    .sort((a, b) => severityRank[b.item.severity] - severityRank[a.item.severity]);

  return (
    <>
      <div className="pointer-events-none absolute inset-0 z-[4] overflow-hidden">
        <div className="absolute left-0 top-0 h-0 w-0 origin-top-left" style={{ transform: worldTransform }}>
        {rendered.map(({ item, node }) => {
          const size = Math.max(28 / scale, 18);
          const x = node.world_x + node.world_w - size * 0.65;
          const y = node.world_y - size * 0.35;
          const system = item.source_type === "system";
          return (
            <button
              key={item.id}
              type="button"
              className={`pointer-events-auto absolute flex items-center justify-center rounded-full border shadow-none transition-transform duration-100 hover:scale-110 ${markerClass(item)}`}
              style={{
                left: x,
                top: y,
                width: size,
                height: size,
              }}
              title={`${item.title} · ${statusLabel(item)}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(item);
              }}
            >
              {system ? (
                <span className="relative flex h-full w-full items-center justify-center">
                  <span className="absolute h-[72%] w-[72%] rotate-45 rounded-sm bg-current opacity-20" />
                  <ShieldAlert style={{ width: size * 0.48, height: size * 0.48 }} />
                </span>
              ) : (
                <AlertTriangle style={{ width: size * 0.48, height: size * 0.48 }} />
              )}
              {item.occurrence_count > 1 && (
                <span className="absolute -right-1 -top-1 rounded-full bg-surface-overlay px-1 text-[10px] leading-4 text-text">
                  {item.occurrence_count}
                </span>
              )}
            </button>
          );
        })}
        </div>
      </div>
      <SpatialAttentionDrawer
        item={items.find((item) => item.id === selectedId) ?? null}
        onClose={() => onSelect(null)}
        onReply={onReply}
      />
    </>
  );
}

function SpatialAttentionDrawer({
  item,
  onClose,
  onReply,
}: {
  item: WorkspaceAttentionItem | null;
  onClose: () => void;
  onReply: (item: WorkspaceAttentionItem) => void;
}) {
  const acknowledge = useAcknowledgeAttentionItem();
  const resolve = useResolveAttentionItem();
  const responded = useMarkAttentionResponded();

  if (!item) return null;
  const correlationId = item.latest_correlation_id;
  return (
    <aside
      className="absolute bottom-4 right-4 top-16 z-[6] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-4 rounded-md bg-surface-raised/95 p-4 text-sm text-text shadow-none ring-1 ring-surface-border backdrop-blur"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Attention Beacon</div>
          <h2 className="mt-1 text-lg font-medium">{item.title}</h2>
          <div className="mt-1 text-xs text-text-muted">
            {item.severity} · {statusLabel(item)} · {item.source_type}
          </div>
        </div>
        <button type="button" className="rounded-md p-1 text-text-muted hover:bg-surface-overlay hover:text-text" onClick={onClose}>
          <X size={16} />
        </button>
      </div>

      <p className="whitespace-pre-wrap text-sm leading-5 text-text-muted">{item.message}</p>

      {item.next_steps.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Next Steps</div>
          <ul className="space-y-1 text-sm text-text-muted">
            {item.next_steps.map((step, idx) => (
              <li key={`${step}-${idx}`}>{step}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-xs text-text-dim">
        <span>Target: {item.target_kind}</span>
        <span>Count: {item.occurrence_count}</span>
        <span>Channel: {item.channel_name ?? item.channel_id ?? "none"}</span>
        <span>Last: {item.last_seen_at ? new Date(item.last_seen_at).toLocaleString() : "unknown"}</span>
      </div>

      {correlationId && (
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-accent hover:bg-accent/10"
          onClick={() => openTraceInspector({ correlationId, title: item.title })}
        >
          <ExternalLink size={14} />
          Open trace evidence
        </button>
      )}

      <div className="mt-auto flex flex-wrap gap-2">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-accent hover:bg-accent/10"
          onClick={() => onReply(item)}
        >
          <MessageSquare size={15} />
          Reply
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay hover:text-text"
          disabled={acknowledge.isPending}
          onClick={() => acknowledge.mutate(item.id)}
        >
          <Check size={15} />
          Acknowledge
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-text-muted hover:bg-surface-overlay hover:text-text"
          disabled={resolve.isPending || responded.isPending}
          onClick={() => resolve.mutate(item.id)}
        >
          Resolve
        </button>
      </div>
    </aside>
  );
}
