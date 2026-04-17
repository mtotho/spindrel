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
import { formatRelativeTime } from "@/src/utils/format";

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
  const patchWidgetConfig = usePinnedWidgetsStore((s) => s.patchWidgetConfig);
  // Current pin config — live-read so widget_config on refresh reflects
  // whatever the user just toggled.
  const widgetConfig = usePinnedWidgetsStore(
    (s) => s.byChannel[channelId]?.find((w) => w.id === widget.id)?.config,
  );
  const widgetConfigRef = useRef(widgetConfig);
  widgetConfigRef.current = widgetConfig;

  // Last-refreshed timestamp (ISO). Drives the "Updated Xm ago" chip.
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  // Tick every 60s so relative time re-renders without extra refreshes.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    if (!lastRefreshedAt) return;
    const handle = setInterval(() => setNowTick((n) => n + 1), 60_000);
    return () => clearInterval(handle);
  }, [lastRefreshedAt]);

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
            widget_config: widgetConfigRef.current ?? {},
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
        setLastRefreshedAt(new Date().toISOString());
      }
    } catch {
      // Silently keep current envelope — stale is better than empty.
    } finally {
      setRefreshing(false);
    }
  }, [widget.id, widget.tool_name, widget.bot_id, channelId, onEnvelopeUpdate, broadcastEnvelope, resolveDisplayLabel]);

  // Initial refresh on mount / re-pin.
  const refreshedForRef = useRef<string | null>(null);
  const [hasCompletedInitialRefresh, setHasCompletedInitialRefresh] = useState(false);
  useEffect(() => {
    if (refreshedForRef.current === widget.id) return;
    refreshedForRef.current = widget.id;
    refreshState().finally(() => setHasCompletedInitialRefresh(true));
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
  // often-stateless output). pin_id + widgetConfig let dispatch:"widget_config"
  // patch the enclosing pin and let tool args reference {{config.*}}.
  const currentDisplayLabel = resolveDisplayLabel(currentEnvelope);
  const rawDispatch = useWidgetAction(
    channelId,
    widget.bot_id,
    currentDisplayLabel,
    widget.id,
    widgetConfig ?? null,
  );

  // Intercepting dispatcher: captures the (polled) response envelope, updates
  // local state, and broadcasts so the inline chat widget stays in sync.
  const interceptingDispatch = useCallback(
    async (action: import("@/src/types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      actionInFlightRef.current = true;
      // Optimistic config merge before the server responds — lets subtle
      // toggle buttons flip their visible state immediately.
      if (action.dispatch === "widget_config" && action.config) {
        patchWidgetConfig(channelId, widget.id, action.config);
      }
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
          setLastRefreshedAt(new Date().toISOString());
        }
        // Follow-up refresh — slow devices (e.g. Shelly relays through HA)
        // sometimes haven't propagated state by the time the server's
        // post-action poll fires, so the returned envelope can show stale
        // state alongside an optimistic toggle. A delayed refresh reconciles.
        window.setTimeout(() => { void refreshState(); }, 2500);
        return result;
      } finally {
        actionInFlightRef.current = false;
      }
    },
    [rawDispatch, widget.id, channelId, widget.tool_name, onEnvelopeUpdate, broadcastEnvelope, patchWidgetConfig, refreshState],
  );

  const actionCtx = useMemo(
    () => ({ dispatchAction: interceptingDispatch }),
    [interceptingDispatch],
  );

  // Track whether we've ever had content, to distinguish "loading" from "cleared"
  const hasEverLoadedRef = useRef(false);

  // Normalize body to string — guard against missing envelope
  const rawBody = currentEnvelope?.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  if (currentEnvelope && body != null) {
    hasEverLoadedRef.current = true;
  }

  // Show skeleton while awaiting first poll for refreshable pins. The saved
  // envelope in the store is frozen from whenever the pin was last persisted,
  // so rendering it before the state_poll lands shows stale state (then flips
  // moments later when the poll returns). Skeleton avoids that flash.
  const awaitingFirstPollForRefreshable =
    !hasCompletedInitialRefresh && !!currentEnvelope?.refreshable;

  // Show skeleton placeholder on initial load (before first poll/hydration)
  if (!currentEnvelope || body == null || awaitingFirstPollForRefreshable) {
    if (!hasEverLoadedRef.current || awaitingFirstPollForRefreshable) {
      return (
        <div
          ref={setNodeRef}
          className="rounded-lg border animate-pulse"
          style={{ borderColor: `${t.surfaceBorder}80` }}
          {...attributes}
        >
          <div className="flex items-center gap-1 px-1.5 pt-1.5 pb-0.5">
            <div className="w-3 h-3 rounded bg-skeleton/[0.04]" />
            <div className="flex-1 h-[10px] rounded bg-skeleton/[0.04]" style={{ maxWidth: 80 }} />
          </div>
          <div className="px-2 pb-2 flex flex-col gap-1.5">
            <div className="h-3 rounded bg-skeleton/[0.04]" style={{ width: "90%" }} />
            <div className="h-3 rounded bg-skeleton/[0.04]" style={{ width: "60%" }} />
          </div>
        </div>
      );
    }
    return null;
  }

  const sortableStyle = {
    transform: CSS.Transform.toString(transform),
    transition,
    borderColor: `${t.surfaceBorder}80`,
    opacity: isDragging ? 0.5 : refreshing ? 0.6 : 1,
  };

  const updatedLabel = lastRefreshedAt ? formatRelativeTime(lastRefreshedAt) : "";

  return (
    <div
      ref={setNodeRef}
      className="group rounded-lg border transition-colors duration-150 hover:bg-white/[0.02]"
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
      <div className="px-2 pb-1 max-h-[350px] overflow-y-auto">
        <WidgetActionContext.Provider value={actionCtx}>
          <ComponentRenderer body={body} t={t} />
        </WidgetActionContext.Provider>
      </div>

      {/* Footer: refresh timestamp — fades in on card hover */}
      {updatedLabel && (
        <div
          className="px-2 pb-1.5 text-[9px] tracking-wide opacity-0 group-hover:opacity-60 transition-opacity duration-150 text-right"
          style={{ color: t.textDim }}
          title={`Last refreshed ${new Date(lastRefreshedAt!).toLocaleString()}`}
        >
          Updated {updatedLabel} ago
        </div>
      )}
    </div>
  );
}
