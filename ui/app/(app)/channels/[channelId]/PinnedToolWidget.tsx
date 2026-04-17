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

  // Resolve the entity name we'll pass to the state_poll refresh endpoint.
  // Prefer display_label on the latest envelope (template-resolved), then
  // display_name, finally scan the envelope body for a `label: entity` row.
  const resolveDisplayLabel = useCallback((env: ToolResultEnvelope | undefined): string => {
    if (env?.display_label) return env.display_label;
    const toolShort = cleanToolName(widget.tool_name);
    if (widget.display_name && widget.display_name !== toolShort) return widget.display_name;
    try {
      const parsed = typeof env?.body === "string" ? JSON.parse(env.body) : env?.body;
      for (const c of parsed?.components ?? []) {
        if (c.type === "properties" && Array.isArray(c.items)) {
          const ent = c.items.find((it: { label?: string; value?: string }) =>
            it.label?.toLowerCase() === "entity" && it.value,
          );
          if (ent?.value) return ent.value;
        }
      }
    } catch { /* not JSON */ }
    return "";
  }, [widget.tool_name, widget.display_name]);

  // Subscribe to shared envelope map — sync from inline WidgetCard actions.
  // Key by the ORIGINAL envelope (from initial paint); if we re-keyed on every
  // currentEnvelope change, an incoming broadcast (e.g., chat message) and
  // our own state_poll output could drift to different keys and miss updates.
  const envelopeKey = useMemo(
    () => `${channelId}::${envelopeIdentityKey(widget.tool_name, widget.envelope)}`,
    [channelId, widget.tool_name, widget.envelope],
  );
  const sharedEnvelope = usePinnedWidgetsStore((s) => s.widgetEnvelopes[envelopeKey]);
  const envelopeRef = useRef(currentEnvelope);
  envelopeRef.current = currentEnvelope;

  // Refresh state from the poll tool. Always try (even without envelope.refreshable)
  // so widgets pinned before the state_poll feature still refresh. Backend returns
  // an error for tools with no state_poll config, which we ignore.
  const [refreshing, setRefreshing] = useState(false);
  const actionInFlightRef = useRef(false);
  const selfBroadcastRef = useRef<ToolResultEnvelope | null>(null);
  const refreshState = useCallback(async () => {
    const displayLabel = resolveDisplayLabel(envelopeRef.current);
    setRefreshing(true);
    try {
      const resp = await apiFetch<{ ok: boolean; envelope?: Record<string, unknown> | null; error?: string }>(
        "/api/v1/widget-actions/refresh",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tool_name: widget.tool_name,
            display_label: displayLabel,
            channel_id: channelId,
            bot_id: widget.bot_id,
          }),
        },
      );
      // Skip if user dispatched an action while poll was in-flight — the action's
      // own polled envelope is more authoritative than a concurrent background poll.
      if (actionInFlightRef.current) return;
      if (resp.ok && resp.envelope) {
        const fresh = resp.envelope as unknown as ToolResultEnvelope;
        selfBroadcastRef.current = fresh;
        setCurrentEnvelope(fresh);
        onEnvelopeUpdate(widget.id, fresh);
        broadcastEnvelope(channelId, widget.tool_name, fresh);
      }
    } catch {
      // Silently keep current envelope — stale is better than empty.
    } finally {
      setRefreshing(false);
    }
  }, [widget.id, widget.tool_name, widget.bot_id, channelId, onEnvelopeUpdate, broadcastEnvelope, resolveDisplayLabel]);

  // Initial refresh on mount / re-pin.
  const refreshedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (refreshedForRef.current === widget.id) return;
    refreshedForRef.current = widget.id;
    refreshState();
  }, [widget.id, refreshState]);

  // Automatic interval refresh — driven by envelope.refresh_interval_seconds.
  // The template engine sets this from state_poll.refresh_interval_seconds in
  // the integration's widget YAML (e.g. OpenWeather uses 3600 for hourly).
  const intervalSec = currentEnvelope?.refresh_interval_seconds;
  useEffect(() => {
    if (!intervalSec || intervalSec <= 0) return;
    const handle = setInterval(refreshState, intervalSec * 1000);
    return () => clearInterval(handle);
  }, [intervalSec, refreshState]);

  // React to external envelope updates (chat broadcasts, other pinned widgets).
  // Two cases:
  //   1. Another pinned widget for the SAME entity just polled — its body JSON
  //      is byte-equal to what our own poll would produce. Accept without
  //      re-polling (otherwise duplicate widgets ping-pong forever, each
  //      treating the other's write as an "external" change).
  //   2. Chat broadcast with the (often stateless) tool-action template —
  //      body differs from polled truth. Accept as transient display and
  //      re-poll to overwrite with live state.
  useEffect(() => {
    if (!sharedEnvelope) return;
    if (sharedEnvelope === envelopeRef.current) return;
    if (sharedEnvelope === selfBroadcastRef.current) return;
    // Body equality = same rendered state. No re-poll, just adopt.
    if (sharedEnvelope.body === envelopeRef.current?.body) {
      selfBroadcastRef.current = sharedEnvelope;
      setCurrentEnvelope(sharedEnvelope);
      return;
    }
    setCurrentEnvelope(sharedEnvelope);
    refreshState();
  }, [sharedEnvelope, refreshState]);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: widget.id });

  // Pass the current display_label so the backend can fetch fresh polled state
  // after the action and return that envelope (instead of the action template's
  // often-stateless output).
  const currentDisplayLabel = resolveDisplayLabel(currentEnvelope);
  const rawDispatch = useWidgetAction(channelId, widget.bot_id, currentDisplayLabel);

  // Intercepting dispatcher: captures the (polled) response envelope, updates
  // local state, and broadcasts so the inline chat widget stays in sync.
  const interceptingDispatch = useCallback(
    async (action: import("@/src/types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      actionInFlightRef.current = true;
      try {
        const result = await rawDispatch(action, value);
        if (
          result.envelope &&
          result.envelope.content_type === "application/vnd.spindrel.components+json" &&
          result.envelope.body
        ) {
          selfBroadcastRef.current = result.envelope;
          setCurrentEnvelope(result.envelope);
          onEnvelopeUpdate(widget.id, result.envelope);
          broadcastEnvelope(channelId, widget.tool_name, result.envelope);
        }
        return result;
      } finally {
        actionInFlightRef.current = false;
      }
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
