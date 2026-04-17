/**
 * PinnedToolWidget — compact widget card for the OmniPanel pinned section.
 *
 * Same rendering pipeline as WidgetCard (ComponentRenderer + WidgetActionContext)
 * but adapted for side panel: drag handle, refresh, unpin controls.
 */
import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { X, GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWidgetAction } from "@/src/api/hooks/useWidgetAction";
import type { WidgetActionResult } from "@/src/api/hooks/useWidgetAction";
import { ComponentRenderer, WidgetActionContext } from "@/src/components/chat/renderers/ComponentRenderer";
import type { PinnedWidget, ToolResultEnvelope } from "@/src/types/api";
import { usePinnedWidgetsStore, envelopeIdentityKey } from "@/src/stores/pinnedWidgets";
import { apiFetch } from "@/src/api/client";

/** Strip MCP server prefix: "homeassistant-HassTurnOn" → "HassTurnOn" */
function cleanToolName(name: string): string {
  const idx = name.indexOf("-");
  return idx >= 0 ? name.slice(idx + 1) : name;
}

/** Get the best display name: display_label from envelope > stored display_name > cleaned tool name */
function resolveDisplayName(widget: PinnedWidget): string {
  // Prefer display_label resolved by the template engine
  if (widget.envelope?.display_label) return widget.envelope.display_label;
  const toolShort = cleanToolName(widget.tool_name);
  if (widget.display_name && widget.display_name !== toolShort) return widget.display_name;
  return toolShort;
}

interface PinnedToolWidgetProps {
  widget: PinnedWidget;
  channelId: string;
  onUnpin: (widgetId: string) => void;
  onEnvelopeUpdate: (widgetId: string, envelope: ToolResultEnvelope) => void;
}

export function PinnedToolWidget({
  widget,
  channelId,
  onUnpin,
  onEnvelopeUpdate,
}: PinnedToolWidgetProps) {
  const t = useThemeTokens();
  const [currentEnvelope, setCurrentEnvelope] = useState(widget.envelope);
  const broadcastEnvelope = usePinnedWidgetsStore((s) => s.broadcastEnvelope);

  // Subscribe to shared envelope map — sync from inline WidgetCard actions
  const envelopeKey = `${channelId}::${envelopeIdentityKey(widget.tool_name, currentEnvelope)}`;
  const sharedEnvelope = usePinnedWidgetsStore((s) => s.widgetEnvelopes[envelopeKey]);
  const envelopeRef = useRef(currentEnvelope);
  envelopeRef.current = currentEnvelope;
  useEffect(() => {
    if (sharedEnvelope && sharedEnvelope !== envelopeRef.current) {
      setCurrentEnvelope(sharedEnvelope);
    }
  }, [sharedEnvelope]);

  // Refresh on mount — try fetching fresh state from the poll tool.
  // Always attempt (not gated on envelope.refreshable) so widgets pinned before
  // the state_poll feature was added still get refreshed. Backend returns error
  // if no state_poll config exists, which we silently ignore.
  // Key by widget.id so re-pinning triggers a fresh poll.
  const refreshedForRef = useRef<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const actionInFlightRef = useRef(false);
  useEffect(() => {
    if (refreshedForRef.current === widget.id) return;
    refreshedForRef.current = widget.id;

    // Resolve entity name: prefer display_label, fall back to display_name,
    // and if display_name is just the tool name, try extracting from envelope body
    let displayLabel = widget.envelope?.display_label || "";
    if (!displayLabel) {
      const toolShort = cleanToolName(widget.tool_name);
      if (widget.display_name && widget.display_name !== toolShort) {
        displayLabel = widget.display_name;
      } else {
        try {
          const parsed = typeof widget.envelope?.body === "string" ? JSON.parse(widget.envelope.body) : widget.envelope?.body;
          for (const c of parsed?.components ?? []) {
            if (c.type === "properties" && Array.isArray(c.items)) {
              const ent = c.items.find((it: any) => it.label?.toLowerCase() === "entity" && it.value);
              if (ent) { displayLabel = ent.value; break; }
            }
          }
        } catch { /* not JSON */ }
      }
    }
    setRefreshing(true);

    apiFetch<{ ok: boolean; envelope?: Record<string, unknown> | null; error?: string }>("/api/v1/widget-actions/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_name: widget.tool_name,
        display_label: displayLabel,
        channel_id: channelId,
        bot_id: widget.bot_id,
      }),
    })
      .then((resp) => {
        // Skip if user dispatched an action while poll was in-flight
        if (actionInFlightRef.current) return;
        if (resp.ok && resp.envelope) {
          const fresh = resp.envelope as unknown as ToolResultEnvelope;
          setCurrentEnvelope(fresh);
          onEnvelopeUpdate(widget.id, fresh);
          broadcastEnvelope(channelId, widget.tool_name, fresh);
        }
      })
      .catch(() => {
        // Silently keep cached envelope — stale is better than empty
      })
      .finally(() => setRefreshing(false));
  }, [widget.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: widget.id });

  const rawDispatch = useWidgetAction(channelId, widget.bot_id);

  // Intercepting dispatcher: captures response envelopes, updates state, and broadcasts
  const interceptingDispatch = useCallback(
    async (action: import("@/src/types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      actionInFlightRef.current = true;
      const result = await rawDispatch(action, value);
      if (
        result.envelope &&
        result.envelope.content_type === "application/vnd.spindrel.components+json" &&
        result.envelope.body
      ) {
        setCurrentEnvelope(result.envelope);
        onEnvelopeUpdate(widget.id, result.envelope);
        broadcastEnvelope(channelId, widget.tool_name, result.envelope);
      }
      return result;
    },
    [rawDispatch, widget.id, channelId, widget.tool_name, onEnvelopeUpdate, broadcastEnvelope],
  );

  const actionCtx = useMemo(
    () => ({ dispatchAction: interceptingDispatch }),
    [interceptingDispatch],
  );

  // Normalize body to string — guard against missing envelope
  const rawBody = currentEnvelope?.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  if (!currentEnvelope || body == null) return null;

  const sortableStyle = {
    transform: CSS.Transform.toString(transform),
    transition,
    borderColor: `${t.surfaceBorder}80`,
    opacity: isDragging ? 0.5 : refreshing ? 0.6 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      className="rounded-lg border transition-colors duration-150 hover:bg-white/[0.02]"
      style={sortableStyle}
      {...attributes}
    >
      {/* Header */}
      <div className="flex items-center gap-1 px-1.5 pt-1.5 pb-0.5">
        <GripVertical
          size={12}
          className="opacity-30 hover:opacity-70 cursor-grab transition-opacity duration-150 flex-shrink-0"
          style={{ color: t.textMuted }}
          {...listeners}
        />
        <span
          className="flex-1 text-[10px] font-medium uppercase tracking-wider truncate"
          style={{ color: t.textDim }}
        >
          {resolveDisplayName(widget)}
        </span>
        <button
          type="button"
          onClick={() => onUnpin(widget.id)}
          className="p-0.5 rounded hover:bg-white/[0.06] transition-colors duration-150 flex-shrink-0"
          title="Unpin"
        >
          <X size={12} style={{ color: t.textMuted, opacity: 0.5 }} />
        </button>
      </div>

      {/* Body: component content */}
      <div className="px-2 pb-2 max-h-[350px] overflow-y-auto">
        <WidgetActionContext.Provider value={actionCtx}>
          <ComponentRenderer body={body} t={t} />
        </WidgetActionContext.Provider>
      </div>
    </div>
  );
}
