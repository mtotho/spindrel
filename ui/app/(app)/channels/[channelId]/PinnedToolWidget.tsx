/**
 * PinnedToolWidget — compact widget card for the OmniPanel pinned section.
 *
 * Same rendering pipeline as WidgetCard (ComponentRenderer + WidgetActionContext)
 * but adapted for side panel: drag handle, refresh, unpin controls.
 */
import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { Pencil, X, GripVertical, RefreshCw, Bug } from "lucide-react";
import { useMatch, useSearchParams } from "react-router-dom";
import { WidgetInspector } from "./WidgetInspector";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ExternalDragBinding } from "@/app/(app)/widgets/DashboardDnd";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWidgetAction } from "@/src/api/hooks/useWidgetAction";
import type { WidgetActionResult } from "@/src/api/hooks/useWidgetAction";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import {
  hasPinnedWidgetIframeEntry,
  type WidgetLayout,
} from "@/src/components/chat/renderers/InteractiveHtmlRenderer";
import type { PinnedWidget, ToolResultEnvelope, WidgetScope } from "@/src/types/api";
import { usePinnedWidgetsStore, envelopeIdentityKey } from "@/src/stores/pinnedWidgets";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { apiFetch } from "@/src/api/client";
import { formatRelativeTime } from "@/src/utils/format";
import {
  DEFAULT_CHROME,
  resolveShowTitle,
  resolveWrapperSurface,
} from "@/src/lib/dashboardGrid";

const INITIAL_REFRESH_GRACE_MS = 2 * 60 * 1000;
// Session-local freshness cache so dashboard <-> chat route switches don't
// immediately re-poll the same pin after a just-completed refresh.
const recentPinRefreshById = new Map<string, string>();

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

function resolvePinnedTitle(widget: PinnedWidget): string {
  const toolShort = cleanToolName(widget.tool_name);
  if (widget.display_name && widget.display_name !== toolShort) return widget.display_name;
  const rawPanelTitle = widget.envelope?.panel_title;
  if (typeof rawPanelTitle === "string" && rawPanelTitle.trim()) return rawPanelTitle.trim();
  return resolveDisplayName(widget);
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
  /** Host-zone override. When omitted, the component infers it:
   *  chip (compact scope) → "chip"; railMode + channel dashboard → inferred by
   *  the enclosing `WidgetRailSection` which passes it explicitly; dashboard
   *  grid tile → "grid"; fallback → "grid". Forwarded into the iframe as
   *  ``window.spindrel.layout`` so widgets can adapt. */
  layout?: WidgetLayout;
  /** Dashboard-level chrome flags (`grid_config.borderless` /
   *  `grid_config.hover_scrollbars` / `grid_config.hide_titles`). Default to
   *  a bordered card with hover-only scrollbars and the title row shown. */
  borderless?: boolean;
  hoverScrollbars?: boolean;
  hideTitles?: boolean;
  /** Panel surfaces use authored host chrome (`panel_title` /
   *  `show_panel_title`) instead of the generic compact title row. */
  panelSurface?: boolean;
  /** Chat runtime rail/dock mirror: placement is dashboard-owned, so hide
   *  edit/debug/refresh/unpin chrome and let the widget body own its title. */
  runtimeRail?: boolean;
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
  hoverScrollbars = DEFAULT_CHROME.hoverScrollbars,
  hideTitles = false,
  panelSurface = false,
  runtimeRail = false,
  externalDrag,
  layout,
}: PinnedToolWidgetProps) {
  const isDashboard = scope.kind === "dashboard";
  const channelId =
    scope.kind === "channel" ? scope.channelId : scope.channelId ?? null;
  const scratchSessionRouteMatch = useMatch("/channels/:channelId/session/:sessionId");
  const [searchParams] = useSearchParams();
  const scratchRouteSessionId =
    searchParams.get("scratch") === "true"
      ? scratchSessionRouteMatch?.params.sessionId ?? null
      : null;
  const dashboardScratchSessionId = searchParams.get("scratch_session_id");
  const viewedSessionId = scratchRouteSessionId ?? dashboardScratchSessionId ?? null;
  const isChip = scope.kind === "channel" && scope.compact === "chip";
  // Resolve the effective layout: explicit prop wins, otherwise chip is
  // implied by the compact scope, and everything else is the dashboard grid.
  const effectiveLayout: WidgetLayout = layout ?? (isChip ? "chip" : "grid");
  // InteractiveHtmlRenderer pools iframes by dashboard pin id for every
  // pinned widget surface, including channel-scope chip rendering inside the
  // channel-dashboard editor. Keep the readiness gate keyed the same way so
  // cross-panel moves do not re-show the preload skeleton forever after the
  // pooled iframe is reattached under a different host.
  const keepAliveKey = `dashboard-pin:${widget.id}`;

  const t = useThemeTokens();
  const [currentEnvelope, setCurrentEnvelope] = useState(widget.envelope);
  const [inspectorOpen, setInspectorOpen] = useState(false);
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

  const markPinRefreshed = useCallback((atIso: string) => {
    recentPinRefreshById.set(widget.id, atIso);
    setLastRefreshedAt(atIso);
  }, [widget.id]);

  // Last-refreshed timestamp (ISO). Drives the "Updated Xm ago" chip.
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(
    () => recentPinRefreshById.get(widget.id) ?? null,
  );
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
  // Per-pin in-flight guard. A single chat-broadcast can fan out to N widgets
  // sharing the same identity; each previously started its own POST to
  // /widget-actions/refresh on top of any in-flight timer-driven refresh.
  // Coalesce: if a refresh is already running for this pin, join it instead
  // of firing a second request.
  const refreshInFlightRef = useRef<Promise<void> | null>(null);
  const selfBroadcastRef = useRef<ToolResultEnvelope | null>(null);
  const refreshState = useCallback((): Promise<void> => {
    if (refreshInFlightRef.current) return refreshInFlightRef.current;
    const displayLabel = resolveDisplayLabel(envelopeRef.current);
    setRefreshing(true);
    const run = (async () => {
      try {
        const body: Record<string, unknown> = {
          tool_name: widget.tool_name,
          display_label: displayLabel,
          widget_config: widgetConfigRef.current ?? {},
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
          markPinRefreshed(new Date().toISOString());
        }
      } catch {
        // Silently keep current envelope — stale is better than empty.
      } finally {
        setRefreshing(false);
        refreshInFlightRef.current = null;
      }
    })();
    refreshInFlightRef.current = run;
    return run;
  }, [widget.id, widget.tool_name, widget.bot_id, channelId, onEnvelopeUpdate, channelBroadcast, dashboardBroadcast, resolveDisplayLabel, markPinRefreshed]);

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
  const recentRefreshIso = recentPinRefreshById.get(widget.id) ?? null;
  const lastRefreshAgeMs = recentRefreshIso
    ? Date.now() - Date.parse(recentRefreshIso)
    : Number.POSITIVE_INFINITY;
  const mountRefreshGraceMs = (() => {
    const intervalMs = (currentEnvelope?.refresh_interval_seconds ?? 0) * 1000;
    if (intervalMs > 0) return Math.min(intervalMs, INITIAL_REFRESH_GRACE_MS);
    if (currentEnvelope?.refreshable) return INITIAL_REFRESH_GRACE_MS;
    return 0;
  })();
  const shouldRefreshOnMount =
    !skipHtmlAutoRefresh
    && (!mountRefreshGraceMs || !Number.isFinite(lastRefreshAgeMs) || lastRefreshAgeMs >= mountRefreshGraceMs);
  useEffect(() => {
    if (refreshedForRef.current === widget.id) return;
    refreshedForRef.current = widget.id;
    if (!shouldRefreshOnMount) {
      setHasCompletedInitialRefresh(true);
      return;
    }
    refreshState().finally(() => setHasCompletedInitialRefresh(true));
  }, [widget.id, refreshState, shouldRefreshOnMount]);

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
      markPinRefreshed(new Date().toISOString());
      return;
    }
    setCurrentEnvelope(sharedEnvelope);
    markPinRefreshed(new Date().toISOString());
    refreshState();
  }, [sharedEnvelope, refreshState, markPinRefreshed]);

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
          markPinRefreshed(new Date().toISOString());
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
    [rawDispatch, widget.id, channelId, widget.tool_name, onEnvelopeUpdate, channelBroadcast, dashboardBroadcast, dashboardPatchConfig, refreshState, markPinRefreshed],
  );

  const dispatcher = useMemo(
    () => ({ dispatchAction: interceptingDispatch }),
    [interceptingDispatch],
  );

  // Measure the tile's rendered size so the interactive-HTML iframe can
  // initialise at the right height instead of popping from 200px on every
  // dashboard↔chat switch. Works on all surfaces uniformly (dashboard RGL
  // cell, rail strip, mobile sheet) because every parent CSS-sizes us.
  const [measuredSize, setMeasuredSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  const measureNodeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = measureNodeRef.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width <= 0 || height <= 0) continue;
        setMeasuredSize((prev) =>
          prev
            && Math.abs(prev.width - width) < 1
            && Math.abs(prev.height - height) < 1
            ? prev
            : { width, height },
        );
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Track iframe-ready so we can hold a pre-load skeleton over interactive-
  // HTML pins until the widget's preamble posts its `ready` handshake. Reset
  // when the pin identity changes so a slot reused for a different pin
  // re-shows the skeleton.
  const [iframeReady, setIframeReady] = useState(() => hasPinnedWidgetIframeEntry(keepAliveKey));
  useEffect(() => {
    setIframeReady(hasPinnedWidgetIframeEntry(keepAliveKey));
  }, [keepAliveKey]);
  const handleIframeReady = useCallback(() => {
    setIframeReady(true);
  }, []);
  const isHtmlInteractive =
    currentEnvelope?.content_type === "application/vnd.spindrel.html+interactive";
  // Skeleton overlay only kicks in for interactive-HTML pins — component
  // widgets render synchronously so there's no flash window to cover.
  const showIframeSkeleton = isHtmlInteractive && !iframeReady;

  // Drag wiring: prefer the enclosing DndContext's binding (`externalDrag`)
  // when provided — that's the channel-dashboard edit-mode case. Otherwise
  // fall back to the internal sortable (channel-scope OmniPanel rail). View
  // mode dashboard pins skip drag entirely. Declared up here (before any
  // conditional returns) so the hook call order stays stable across renders.
  const baseRootRef = externalDrag?.setNodeRef ?? (isDashboard ? undefined : fbSetRef);
  // Compose the drag-library's ref with our own measurement ref so the
  // ResizeObserver tracks the same node react-dnd attaches to.
  const rootRef = useCallback(
    (node: HTMLDivElement | null) => {
      measureNodeRef.current = node;
      if (baseRootRef) baseRootRef(node);
    },
    [baseRootRef],
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
          className={`${runtimeRail ? "animate-pulse" : "rounded-lg border animate-pulse"}`}
          style={{ borderColor: `${t.surfaceBorder}80` }}
          {...(externalDrag?.attributes ?? fbAttrs)}
        >
          {!runtimeRail && (
            <div className="flex items-center gap-1 px-1.5 pt-1.5 pb-0.5">
              <div className="w-3 h-3 rounded bg-skeleton/[0.04]" />
              <div className="flex-1 h-[10px] rounded bg-skeleton/[0.04]" style={{ maxWidth: 80 }} />
            </div>
          )}
          <div className={`${runtimeRail ? "px-2 py-2" : "px-2 pb-2"} flex flex-col gap-1.5`}>
            <div className="h-3 rounded bg-skeleton/[0.04]" style={{ width: "90%" }} />
            <div className="h-3 rounded bg-skeleton/[0.04]" style={{ width: "60%" }} />
          </div>
        </div>
      );
    }
    return null;
  }

  // Wrapper surface is host-owned chrome: inherit follows dashboard chrome,
  // but per-pin config can force a surfaced shell or a plain transparent one.
  const wrapperSurface = resolveWrapperSurface(
    { ...DEFAULT_CHROME, borderless, hoverScrollbars, hideTitles },
    (widgetConfig ?? null) as Record<string, unknown> | null,
  );
  const isInteractiveHtml =
    currentEnvelope?.content_type === "application/vnd.spindrel.html+interactive";
  const flushInteractiveHtmlBody = isInteractiveHtml && wrapperSurface === "plain";
  const showBorder = wrapperSurface === "surface";
  const showWrapperBackground = wrapperSurface === "surface";
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
  const editFrameClass = isDashboard && editMode
    ? showBorder
      ? "ring-1 ring-inset ring-white/[0.05] hover:ring-accent/25"
      : "border border-dashed border-white/[0.14] hover:border-accent/40 bg-white/[0.015]"
    : "";
  const resolvedPanelTitle = resolvePinnedTitle({
    ...widget,
    envelope: currentEnvelope,
  });

  // Title row is always present in channel-scope chips (for drag DOM).
  // Dashboard + rail tiles honor the dashboard's hide_titles flag plus the
  // per-pin `widget_config.show_title` override ("inherit" / "show" / "hide").
  // Title visibility follows preview exactly — including in edit mode — so the
  // tile's edit-mode footprint matches what the user will see post-save, and
  // snap / ghost targets line up with real content. When titles are hidden in
  // edit mode the drag handle + pencil/unpin move to a floating hover overlay
  // so the chrome is still reachable.
  const showTitle = resolveShowTitle(
    { ...DEFAULT_CHROME, hideTitles },
    (widgetConfig ?? null) as Record<string, unknown> | null,
  );
  const showPanelTitle =
    panelSurface
    && currentEnvelope?.show_panel_title === true
    && !!resolvedPanelTitle;
  const showGenericTitle = showTitle && !showPanelTitle;
  // Overlay chrome floats the grip + controls on hover instead of reserving
  // a ~30px header row. Only use it when titles are intentionally hidden in
  // edit mode; equivalent widgets should otherwise render the same host header
  // regardless of whether they sit in the center grid or a side rail.
  const overlayChrome =
    ((isDashboard || railMode) && editMode && !showGenericTitle) && !showPanelTitle;
  const showHostHeader = !runtimeRail;
  const showHeaderDragLane = showHostHeader && (!isDashboard || editMode || railMode) && !!handleListeners;
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
          // No left padding in view mode: iframe content fills flush to the
          // rounded border so the chip's raised bg doesn't leak through as a
          // white gap beside widget content (notably error banners).
          "group flex h-8 items-center rounded-md overflow-hidden transition-colors "
          + (chipEditable
            ? `${showBorder ? "border border-accent/50 " : ""}bg-accent/[0.08] hover:bg-accent/[0.14] pl-1 pr-1 `
            : `${showBorder ? "border border-surface-border/60 " : ""}${showWrapperBackground ? "bg-surface-raised/40 " : ""}pr-1 `)
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
          <div
            className="widget-drag-handle cursor-grab flex-shrink-0 mr-1 p-1.5 -m-1.5 opacity-90 hover:opacity-100 transition-opacity"
            aria-label="Drag to reorder"
            {...(externalDrag?.listeners ?? {})}
          >
            <GripVertical
              size={12}
              style={{ color: t.accent }}
            />
          </div>
        )}
        <div
          // self-stretch so the iframe wrapper fills the h-8 cross-axis; the
          // grip icon + unpin button stay centered via the parent's
          // items-center. Without this, an oversized iframe (or any future
          // content > 32px) would vertically center and overflow upward out
          // of the clip box, cutting the chip HTML off the top.
          className="flex-1 min-w-0 self-stretch overflow-hidden [mask-image:linear-gradient(to_right,black_80%,transparent)]"
        >
          <RichToolResult
            envelope={currentEnvelope}
            sessionId={viewedSessionId ?? undefined}
            channelId={channelId ?? undefined}
            dispatcher={dispatcher}
            fillHeight={false}
            dashboardPinId={widget.id}
            gridDimensions={measuredSize ?? undefined}
            onIframeReady={handleIframeReady}
            layout={effectiveLayout}
            hostSurface={wrapperSurface}
            t={t}
          />
        </div>
        {chipEditable && (
          <button
            type="button"
            onClick={() => onUnpin(widget.id)}
            className="ml-1 p-0.5 rounded hover:bg-white/[0.06] flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
            aria-label="Unpin chip"
            title="Unpin"
          >
            <X size={12} style={{ color: t.textMuted }} />
          </button>
        )}
      </div>
    );
  }
  return (
    <div
      ref={rootRef}
      className={`group relative rounded-lg ${cardBorderClass} ${editFrameClass} ${showWrapperBackground ? "bg-surface-raised/40 hover:bg-white/[0.02]" : ""} transition-colors duration-150 ${cardSizeClass}`}
      style={sortableStyle}
      {...rootAttrs}
    >
      {/* Header — suppressed entirely when the widget is titleless in edit
          mode; chrome surfaces as a floating overlay below so the tile's
          footprint matches preview exactly. */}
      {showHostHeader && !overlayChrome && (
        <div
          className={
            showPanelTitle
              ? "flex items-center gap-1.5 px-2 pt-2 pb-1 border-b border-surface-border/40 shrink-0"
              : "flex items-center gap-1 px-1.5 pt-1.5 pb-0.5"
          }
        >
          <div
            className={
              showHeaderDragLane
                ? "widget-drag-handle flex min-w-0 flex-1 items-center gap-1 cursor-grab rounded-md px-0.5 py-0.5 -mx-0.5 -my-0.5 transition-colors duration-150 hover:bg-white/[0.03]"
                : "flex min-w-0 flex-1 items-center gap-1"
            }
            aria-label={showHeaderDragLane ? "Drag to reorder" : undefined}
            {...(showHeaderDragLane ? handleListeners : {})}
          >
            {showHeaderDragLane && (
            <div
              className={
                "transition-opacity duration-150 flex-shrink-0 p-1.5 -m-1.5 " +
                (editMode
                  ? "opacity-80 hover:opacity-100"
                  : "opacity-0 group-hover:opacity-100")
              }
            >
              <GripVertical
                size={ctrlIconSize}
                className="text-text-muted"
              />
            </div>
            )}
            {showPanelTitle ? (
              <div className="flex-1 min-w-0">
                <div
                  className="truncate text-[15px] font-semibold tracking-[-0.01em]"
                  style={{ color: t.text }}
                >
                  {resolvedPanelTitle}
                </div>
              </div>
            ) : showGenericTitle ? (
              <span
                className="flex-1 text-[10px] font-medium uppercase tracking-wider truncate"
                style={{ color: t.textDim }}
              >
                {resolveDisplayName(widget)}
              </span>
            ) : (
              <div className="flex-1" />
            )}
          </div>
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
          <button
            type="button"
            onClick={() => setInspectorOpen(true)}
            className={`${ctrlBtnClass} opacity-0 group-hover:opacity-100`}
            aria-label="Inspect widget"
            title="Inspect — see live tool traffic, errors, logs"
          >
            <Bug size={ctrlIconSize} style={{ color: t.textMuted, opacity: 0.6 }} />
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
      )}

      {/* Floating chrome for titleless tiles in edit mode. Hover-reveal so
          the tile is visually unchanged from preview until the user mouses
          over it, at which point drag + edit + unpin surface in the top-
          right corner. `z-20` keeps it above iframe content; backdrop-blur
          + translucent raised bg gives the chrome a card chip appearance
          without carving dedicated vertical space out of the tile. */}
      {overlayChrome && (
        <div
          className="absolute top-1 right-1 z-20 flex items-center gap-0.5 rounded-md bg-surface-raised/85 backdrop-blur-sm px-0.5 py-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity border border-surface-border/40"
          // Prevent pointer events inside the overlay from falling through
          // to the iframe body during drag initiation.
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div
            className="widget-drag-handle cursor-grab p-1.5 -m-1.5 opacity-80 hover:opacity-100 transition-opacity"
            aria-label="Drag to reorder"
            {...(handleListeners ?? {})}
          >
            <GripVertical
              size={ctrlIconSize}
              className="text-text-muted"
            />
          </div>
          {onEdit && (
            <button
              type="button"
              onClick={() => onEdit(widget.id)}
              className={ctrlBtnClass}
              aria-label="Edit pin"
              title="Edit pin"
            >
              <Pencil size={ctrlIconSize} style={{ color: t.textMuted, opacity: 0.7 }} />
            </button>
          )}
          <button
            type="button"
            onClick={() => setInspectorOpen(true)}
            className={ctrlBtnClass}
            aria-label="Inspect widget"
            title="Inspect — see live tool traffic, errors, logs"
          >
            <Bug size={ctrlIconSize} style={{ color: t.textMuted, opacity: 0.7 }} />
          </button>
          <button
            type="button"
            onClick={() => onUnpin(widget.id)}
            className={ctrlBtnClass}
            aria-label="Unpin widget"
            title="Unpin"
          >
            <X size={ctrlIconSize} style={{ color: t.textMuted, opacity: 0.6 }} />
          </button>
        </div>
      )}

      {/* Body: component content. Dashboard scope fills the tile; channel
          scope retains the fixed cap so the OmniPanel column stays compact.
          `pb-2` gives range-slider thumbs (which render outside the input's
          box) a bit of room to escape the overflow clip. `scroll-subtle`
          (dashboard flag) hides the scrollbar until the tile is hovered. */}
      <div
        className={
          "relative "
          + (isDashboard
            ? (flushInteractiveHtmlBody
              ? "flex-1 min-h-0 "
              : (overlayChrome
                ? "p-2 flex-1 min-h-0 "
                : `${showPanelTitle || !showHostHeader ? "px-2 py-2" : "px-2 pb-2"} flex-1 min-h-0 `))
            : (flushInteractiveHtmlBody ? "max-h-[350px] " : "px-2 pb-2 max-h-[350px] "))
          + (hoverScrollbars
            ? "overflow-y-auto scroll-subtle"
            : "overflow-y-auto")
        }
      >
        <RichToolResult
          envelope={currentEnvelope}
          sessionId={viewedSessionId ?? undefined}
          channelId={channelId ?? undefined}
          dispatcher={dispatcher}
          fillHeight={isDashboard}
          dashboardPinId={widget.id}
          gridDimensions={measuredSize ?? undefined}
          onIframeReady={handleIframeReady}
          hoverScrollbars={hoverScrollbars}
          layout={effectiveLayout}
          hostSurface={wrapperSurface}
          t={t}
        />
        {showIframeSkeleton && (
          <div
            className={
              flushInteractiveHtmlBody
                ? "absolute inset-0 flex flex-col gap-1.5 animate-pulse pointer-events-none"
                : "absolute inset-0 px-2 pb-2 pt-0 flex flex-col gap-1.5 animate-pulse pointer-events-none"
            }
            style={{ background: showWrapperBackground ? t.surface : "transparent" }}
            aria-hidden
          >
            <div className="h-3 rounded bg-skeleton/[0.04]" style={{ width: "90%" }} />
            <div className="h-3 rounded bg-skeleton/[0.04]" style={{ width: "60%" }} />
            <div className="flex-1 rounded bg-skeleton/[0.03] mt-1" />
          </div>
        )}
      </div>
      {inspectorOpen && (
        <WidgetInspector
          pinId={widget.id}
          pinLabel={resolveDisplayName(widget)}
          onClose={() => setInspectorOpen(false)}
        />
      )}
    </div>
  );
}
