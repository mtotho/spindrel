/**
 * PinnedToolWidget — compact widget card for the OmniPanel pinned section.
 *
 * Same rendering pipeline as WidgetCard (ComponentRenderer + WidgetActionContext)
 * but adapted for side panel: drag handle, refresh, unpin controls.
 */
import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { Pencil, X, GripVertical, RefreshCw } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ExternalDragBinding } from "@/app/(app)/widgets/DashboardDnd";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWidgetAction } from "@/src/api/hooks/useWidgetAction";
import type { WidgetActionResult } from "@/src/api/hooks/useWidgetAction";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import type { PinnedWidget, ToolResultEnvelope, WidgetScope } from "@/src/types/api";
import { usePinnedWidgetsStore, envelopeIdentityKey } from "@/src/stores/pinnedWidgets";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
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
  scope: WidgetScope;
  onUnpin: (widgetId: string) => void;
  onEnvelopeUpdate: (widgetId: string, envelope: ToolResultEnvelope) => void;
  /** Dashboard-scope only: when true, the drag handle and Edit button are
   *  visible; when false, they stay hidden so viewing the dashboard is calm. */
  editMode?: boolean;
  /** Dashboard-scope only: opens the EditPinDrawer for this pin. */
  onEdit?: (pinId: string) => void;
  /** OmniPanel rail variant: expose the drag handle with hover-only opacity
   *  (so react-grid-layout can pick it up via `.widget-drag-handle`) without
   *  revealing the full edit chrome (pencil / unpin). The rail uses RGL for
   *  in-place reorder + resize; everything else stays calm. */
  railMode?: boolean;
  /** Dashboard-level chrome flags (`grid_config.borderless` /
   *  `grid_config.hover_scrollbars`). Default to a bordered card with a
   *  persistent scrollbar — matches legacy behavior for every other surface. */
  borderless?: boolean;
  hoverScrollbars?: boolean;
  /** Channel multi-canvas dashboard: the enclosing `DndContext` supplies a
   *  pre-wired draggable binding (useSortable or useDraggable) so the grip
   *  icon becomes the single drag handle — intra-canvas AND cross-canvas.
   *  When omitted, the widget falls back to its own internal useSortable
   *  (used by the channel-scope OmniPanel rail in runtime chat). */
  externalDrag?: ExternalDragBinding;
}

export function PinnedToolWidget({
  widget,
  scope,
  onUnpin,
  onEnvelopeUpdate,
  editMode = false,
  onEdit,
  railMode = false,
  borderless = false,
  hoverScrollbars = false,
  externalDrag,
}: PinnedToolWidgetProps) {
  const isDashboard = scope.kind === "dashboard";
  const channelId =
    scope.kind === "channel" ? scope.channelId : scope.channelId ?? null;
  const isChip = scope.kind === "channel" && scope.compact === "chip";

  const t = useThemeTokens();
  const [currentEnvelope, setCurrentEnvelope] = useState(widget.envelope);
  // Channel pins now live in the dashboard-pins store under the implicit
  // slug `channel:<uuid>`. Both scope.kind values read/write the same
  // store; the channel variant still fires the chat-side envelope
  // broadcast so inline WidgetCards can pick up changes.
  const channelBroadcast = usePinnedWidgetsStore((s) => s.broadcastEnvelope);
  const dashboardBroadcast = useDashboardPinsStore((s) => s.broadcastEnvelope);
  const dashboardPatchConfig = useDashboardPinsStore((s) => s.patchWidgetConfig);
  const dashboardWidgetConfig = useDashboardPinsStore(
    (s) => s.pins.find((p) => p.id === widget.id)?.widget_config,
  );
  const widgetConfig = dashboardWidgetConfig;
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
  const identity = useMemo(
    () => envelopeIdentityKey(widget.tool_name, widget.envelope),
    [widget.tool_name, widget.envelope],
  );
  const channelEnvelopeKey = useMemo(
    () => (channelId ? `${channelId}::${identity}` : null),
    [channelId, identity],
  );
  const channelShared = usePinnedWidgetsStore(
    (s) => (channelEnvelopeKey ? s.widgetEnvelopes[channelEnvelopeKey] : undefined),
  );
  const dashboardShared = useDashboardPinsStore((s) => s.widgetEnvelopes[identity]);
  const sharedEnvelope = isDashboard ? dashboardShared : channelShared;
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
      const body: Record<string, unknown> = {
        tool_name: widget.tool_name,
        display_label: displayLabel,
        widget_config: widgetConfigRef.current ?? {},
        // All pins (dashboard-scope and channel-scope) are dashboard pins now.
        dashboard_pin_id: widget.id,
      };
      if (channelId) {
        body.channel_id = channelId;
        body.bot_id = widget.bot_id;
      }
      const resp = await apiFetch<{ ok: boolean; envelope?: Record<string, unknown> | null; error?: string }>(
        "/api/v1/widget-actions/refresh",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
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
        dashboardBroadcast(widget.tool_name, fresh);
        if (channelId) {
          channelBroadcast(channelId, widget.tool_name, fresh);
        }
        setLastRefreshedAt(new Date().toISOString());
      }
    } catch {
      // Silently keep current envelope — stale is better than empty.
    } finally {
      setRefreshing(false);
    }
  }, [widget.id, widget.tool_name, widget.bot_id, channelId, onEnvelopeUpdate, channelBroadcast, dashboardBroadcast, resolveDisplayLabel]);

  // Initial refresh on mount / re-pin.
  const refreshedForRef = useRef<string | null>(null);
  const [hasCompletedInitialRefresh, setHasCompletedInitialRefresh] = useState(false);
  // HTML widgets own their own freshness UNLESS they declare state_poll.
  //   - emit_html_widget output is either a static inline snapshot or a
  //     path-mode envelope polled against the workspace file — refreshable=false.
  //   - Declarative html_template widgets (e.g. frigate_snapshot) run through
  //     state_poll like component widgets, so they get refreshable=true + a
  //     refresh_interval_seconds. The refresh endpoint re-emits the envelope
  //     with fresh source_bot_id/source_channel_id so `window.spindrel` stays
  //     intact across polls.
  const isHtmlWidget = currentEnvelope?.content_type
    === "application/vnd.spindrel.html+interactive";
  const skipHtmlAutoRefresh = isHtmlWidget && !currentEnvelope?.refreshable;
  useEffect(() => {
    if (refreshedForRef.current === widget.id) return;
    refreshedForRef.current = widget.id;
    if (skipHtmlAutoRefresh) {
      setHasCompletedInitialRefresh(true);
      return;
    }
    refreshState().finally(() => setHasCompletedInitialRefresh(true));
  }, [widget.id, refreshState, skipHtmlAutoRefresh]);

  // Automatic interval refresh — driven by envelope.refresh_interval_seconds.
  // The template engine sets this from state_poll.refresh_interval_seconds in
  // the integration's widget YAML (e.g. OpenWeather uses 3600 for hourly).
  const intervalSec = currentEnvelope?.refresh_interval_seconds;
  useEffect(() => {
    if (skipHtmlAutoRefresh) return;
    if (!intervalSec || intervalSec <= 0) return;
    const handle = setInterval(refreshState, intervalSec * 1000);
    return () => clearInterval(handle);
  }, [intervalSec, refreshState, skipHtmlAutoRefresh]);

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

  // Fallback drag binding for surfaces that don't pass `externalDrag` (the
  // channel-scope OmniPanel rail uses dnd-kit's SortableContext internally).
  // Dashboard-scope edit mode supplies its own binding from the enclosing
  // DndContext in `ChannelDashboardMultiCanvas` via the `externalDrag` prop.
  const fallbackSortable = useSortable({ id: widget.id });
  const {
    attributes: fbAttrs,
    listeners: fbListeners,
    setNodeRef: fbSetRef,
    transform: fbTransform,
    transition: fbTransition,
  } = fallbackSortable;
  const fallbackIsDragging = isDashboard ? false : fallbackSortable.isDragging;

  // Pass the current display_label so the backend can fetch fresh polled state
  // after the action and return that envelope (instead of the action template's
  // often-stateless output). pin_id + widgetConfig let dispatch:"widget_config"
  // patch the enclosing pin and let tool args reference {{config.*}}.
  const currentDisplayLabel = resolveDisplayLabel(currentEnvelope);
  // All pins (dashboard + channel) are dashboard pins server-side; pass the
  // pin id as `dashboardPinId` in both scopes. `pinId` (the legacy channel
  // branch in useWidgetAction) stays null.
  const rawDispatch = useWidgetAction(
    channelId ?? undefined,
    widget.bot_id,
    currentDisplayLabel,
    null,
    widgetConfig ?? null,
    widget.id,
  );

  // Intercepting dispatcher: captures the (polled) response envelope, updates
  // local state, and broadcasts so the inline chat widget stays in sync.
  const interceptingDispatch = useCallback(
    async (action: import("@/src/types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      actionInFlightRef.current = true;
      // Optimistic config merge before the server responds — lets subtle
      // toggle buttons flip their visible state immediately. Both scopes
      // now share the dashboard-pins store.
      if (action.dispatch === "widget_config" && action.config) {
        dashboardPatchConfig(widget.id, action.config);
      }
      try {
        const result = await rawDispatch(action, value);
        if (
          result.envelope &&
          result.envelope.body &&
          (result.envelope.content_type === "application/vnd.spindrel.components+json"
            || result.envelope.content_type === "application/vnd.spindrel.html+interactive")
        ) {
          selfBroadcastRef.current = result.envelope;
          setCurrentEnvelope(result.envelope);
          onEnvelopeUpdate(widget.id, result.envelope);
          dashboardBroadcast(widget.tool_name, result.envelope);
          if (channelId) {
            channelBroadcast(channelId, widget.tool_name, result.envelope);
          }
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
    [rawDispatch, widget.id, channelId, widget.tool_name, onEnvelopeUpdate, channelBroadcast, dashboardBroadcast, dashboardPatchConfig, refreshState],
  );

  const dispatcher = useMemo(
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
          ref={externalDrag?.setNodeRef ?? fbSetRef}
          className="rounded-lg border animate-pulse"
          style={{ borderColor: `${t.surfaceBorder}80` }}
          {...(externalDrag?.attributes ?? fbAttrs)}
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

  // Borderless mode drops the border + borderColor entirely so the tiles read
  // as a clean grid of content blocks rather than admin chrome. Callers pass
  // this from the per-dashboard `grid_config.borderless` flag — applies
  // consistently across all rendering surfaces (dashboard grid, OmniPanel
  // rail, WidgetDockRight).
  const showBorder = !borderless;
  const borderColorStyle = showBorder ? { borderColor: `${t.surfaceBorder}80` } : {};
  // Edit-mode dashboard pins get their drag transform/transition from the
  // external DndContext; view-mode dashboard pins skip all drag styling;
  // channel-scope falls back to the internal sortable. Keep opacity
  // coordination here so refresh-in-flight tiles dim consistently across
  // surfaces.
  const dragStyle: CSSProperties = externalDrag
    ? externalDrag.style
    : isDashboard
      ? {}
      : {
          transform: CSS.Transform.toString(fbTransform),
          transition: fbTransition,
          opacity: fallbackIsDragging ? 0.5 : 1,
        };
  const sortableStyle: CSSProperties = {
    ...dragStyle,
    ...borderColorStyle,
    opacity:
      (dragStyle.opacity as number | undefined) !== undefined && (dragStyle.opacity as number) < 1
        ? (dragStyle.opacity as number)
        : refreshing
          ? 0.6
          : 1,
  };

  // Drag wiring: prefer the enclosing DndContext's binding (`externalDrag`)
  // when provided — that's the channel-dashboard edit-mode case. Otherwise
  // fall back to the internal sortable (channel-scope OmniPanel rail). View
  // mode dashboard pins skip drag entirely.
  const rootRef = externalDrag?.setNodeRef ?? (isDashboard ? undefined : fbSetRef);
  const rootAttrs = externalDrag?.attributes ?? (isDashboard ? {} : fbAttrs);
  const handleListeners = externalDrag?.listeners ?? (isDashboard ? undefined : fbListeners);

  const updatedLabel = lastRefreshedAt ? formatRelativeTime(lastRefreshedAt) : "";
  const refreshTooltip = lastRefreshedAt
    ? `${updatedLabel === "now" ? "Updated just now" : `Updated ${updatedLabel} ago`} · ${new Date(lastRefreshedAt).toLocaleString()} · Click to refresh`
    : "Refresh";

  // Dashboard cards live inside react-grid-layout tiles — fill height so the
  // body expands to the resized dimensions rather than clipping at 350px.
  const cardSizeClass = isDashboard
    ? "h-full flex flex-col"
    : "";

  // Dashboard-scope controls get roomier padding so the touch target is
  // practical on tablet; channel scope stays compact in the OmniPanel.
  const ctrlBtnClass = isDashboard
    ? "p-1.5 rounded hover:bg-white/[0.06] transition-colors duration-150 flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
    : "p-0.5 rounded hover:bg-white/[0.06] transition-colors duration-150 flex-shrink-0";
  const ctrlIconSize = isDashboard ? 14 : 12;

  const cardBorderClass = showBorder ? "border" : "";
  if (isChip) {
    // Edit mode (only reachable when the parent DndContext provides
    // `externalDrag`) exposes a grip handle on the left edge + an unpin X on
    // the right so header chips are DnD-actionable alongside rail/dock/grid
    // tiles. View mode keeps the chip minimal — name + body text.
    const chipEditable = editMode && !!externalDrag;
    return (
      <div
        ref={externalDrag?.setNodeRef}
        className={
          "group flex h-8 items-center rounded-md border border-surface-border/60 bg-surface-raised/40 px-2 overflow-hidden "
          + (externalDrag ? "w-full" : "w-[180px]")
        }
        title={resolveDisplayName(widget)}
        style={{
          color: t.textMuted,
          ...(externalDrag?.style ?? {}),
        }}
        {...(externalDrag?.attributes ?? {})}
      >
        {chipEditable && (
          <GripVertical
            size={11}
            className="widget-drag-handle cursor-grab flex-shrink-0 mr-1 opacity-50 group-hover:opacity-100 transition-opacity"
            aria-label="Drag to reorder"
            {...(externalDrag?.listeners ?? {})}
          />
        )}
        <div
          className="flex-1 min-w-0 overflow-hidden [mask-image:linear-gradient(to_right,black_80%,transparent)]"
        >
          <RichToolResult
            envelope={currentEnvelope}
            channelId={channelId ?? undefined}
            dispatcher={dispatcher}
            fillHeight={false}
            dashboardPinId={widget.id}
            t={t}
          />
        </div>
        {chipEditable && (
          <button
            type="button"
            onClick={() => onUnpin(widget.id)}
            className="ml-1 p-0.5 rounded hover:bg-white/[0.06] flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
            aria-label="Unpin chip"
            title="Unpin"
          >
            <X size={11} style={{ color: t.textMuted, opacity: 0.6 }} />
          </button>
        )}
      </div>
    );
  }
  return (
    <div
      ref={rootRef}
      className={`group rounded-lg ${cardBorderClass} transition-colors duration-150 hover:bg-white/[0.02] ${cardSizeClass}`}
      style={sortableStyle}
      {...rootAttrs}
    >
      {/* Header */}
      <div className="flex items-center gap-1 px-1.5 pt-1.5 pb-0.5">
        {/* In dashboard scope the handle is gated by editMode so view mode
            stays calm; channel scope always shows it (the OmniPanel dnd-kit
            reorder flow relies on it). Rail mode reveals the handle too, but
            hover-only so the tile stays calm at rest. */}
        {(!isDashboard || editMode || railMode) && (
          <GripVertical
            size={ctrlIconSize}
            className={
              "widget-drag-handle text-text-muted cursor-grab transition-opacity duration-150 flex-shrink-0 " +
              (editMode
                ? "opacity-80 hover:opacity-100"
                : "opacity-50 group-hover:opacity-100") +
              (isDashboard ? " p-0.5 -m-0.5" : "")
            }
            aria-label="Drag to reorder"
            {...(handleListeners ?? {})}
          />
        )}
        <span
          className="flex-1 text-[10px] font-medium uppercase tracking-wider truncate"
          style={{ color: t.textDim }}
        >
          {resolveDisplayName(widget)}
        </span>
        {isDashboard && editMode && onEdit && (
          <button
            type="button"
            onClick={() => onEdit(widget.id)}
            className={ctrlBtnClass}
            aria-label="Edit pin"
            title="Edit pin"
          >
            <Pencil size={ctrlIconSize} style={{ color: t.textMuted, opacity: 0.6 }} />
          </button>
        )}
        <button
          type="button"
          onClick={() => { void refreshState(); }}
          className={`${ctrlBtnClass} opacity-0 group-hover:opacity-100`}
          aria-label="Refresh widget"
          title={refreshTooltip}
          disabled={refreshing}
        >
          <RefreshCw
            size={ctrlIconSize}
            className={refreshing ? "animate-spin" : ""}
            style={{ color: t.textMuted, opacity: 0.6 }}
          />
        </button>
        {(!isDashboard || editMode) && (
          <button
            type="button"
            onClick={() => onUnpin(widget.id)}
            className={ctrlBtnClass}
            aria-label="Unpin widget"
            title="Unpin"
          >
            <X size={ctrlIconSize} style={{ color: t.textMuted, opacity: 0.5 }} />
          </button>
        )}
      </div>

      {/* Body: component content. Dashboard scope fills the tile; channel
          scope retains the fixed cap so the OmniPanel column stays compact.
          `pb-2` gives range-slider thumbs (which render outside the input's
          box) a bit of room to escape the overflow clip. `scroll-subtle`
          (dashboard flag) hides the scrollbar until the tile is hovered. */}
      <div
        className={
          (isDashboard
            ? "px-2 pb-2 flex-1 min-h-0 "
            : "px-2 pb-2 max-h-[350px] ")
          + (hoverScrollbars
            ? "overflow-y-auto scroll-subtle"
            : "overflow-y-auto")
        }
      >
        <RichToolResult
          envelope={currentEnvelope}
          channelId={channelId ?? undefined}
          dispatcher={dispatcher}
          fillHeight={isDashboard}
          dashboardPinId={widget.id}
          t={t}
        />
      </div>
    </div>
  );
}
