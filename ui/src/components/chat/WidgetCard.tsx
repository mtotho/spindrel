/**
 * WidgetCard — standalone card wrapper for inline interactive widget envelopes.
 *
 * Renders directly below the message text (outside ToolBadges chrome).
 * Manages its own envelope state: when a widget action returns a new component
 * envelope, the card replaces its body and re-renders — fixing the toggle
 * state bug where local state went stale after the first interaction.
 *
 * Pin-ready: accepts optional widgetId + onPin for future side-panel pinning.
 */
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { Pin, ChevronDown } from "lucide-react";
import type { ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { useWidgetAction } from "../../api/hooks/useWidgetAction";
import type { WidgetActionResult } from "../../api/hooks/useWidgetAction";
import { ComponentRenderer, WidgetActionContext } from "./renderers/ComponentRenderer";
import { JsonTreeRenderer } from "./renderers/JsonTreeRenderer";
import { InteractiveHtmlRenderer } from "./renderers/InteractiveHtmlRenderer";
import { usePinnedWidgetsStore, envelopeIdentityKey } from "../../stores/pinnedWidgets";
import { useDashboardPinsStore } from "../../stores/dashboardPins";
import { apiFetch } from "../../api/client";

/** Strip MCP server prefix: "homeassistant-HassTurnOn" → "HassTurnOn" */
function cleanToolName(name: string): string {
  const idx = name.indexOf("-");
  return idx >= 0 ? name.slice(idx + 1) : name;
}

interface WidgetCardProps {
  envelope: ToolResultEnvelope;
  toolName: string;
  sessionId?: string;
  channelId?: string;
  botId?: string;
  t: ThemeTokens;
  /** Stable identity for pin references (derived from tool call record_id) */
  widgetId?: string;
  /** When true, this is part of the latest bot message — keep expanded */
  isLatestBotMessage?: boolean;
  /** When true, start in collapsed state (used for stacked multi-widget messages) */
  defaultCollapsed?: boolean;
  /** Callback when user pins this widget to a side panel */
  onPin?: (info: {
    widgetId: string;
    envelope: ToolResultEnvelope;
    toolName: string;
    channelId: string;
    /** Null when no bot id could be resolved — the pin persists with
     * `source_bot_id = null` rather than silently substituting a wrong bot. */
    botId: string | null;
  }) => void;
}

export function WidgetCard({
  envelope,
  toolName,
  channelId,
  botId,
  t,
  widgetId,
  isLatestBotMessage,
  defaultCollapsed,
  onPin,
}: WidgetCardProps) {
  const [currentEnvelope, setCurrentEnvelope] = useState(envelope);
  const [showJson, setShowJson] = useState(false);
  const [manualExpand, setManualExpand] = useState<boolean | null>(null);

  // Check if this exact widget is already pinned on the channel's implicit
  // dashboard. Pins live in `widget_dashboard_pins` now; we read them from
  // the dashboard-pins store when its currentSlug matches this channel.
  // Identity is delegated to `envelopeIdentityKey` so HTML widgets keyed by
  // source_path don't collide with other emit_html_widget pins.
  const thisKey = envelopeIdentityKey(toolName, envelope);
  const isPinned = useDashboardPinsStore((s) => {
    if (!channelId) return false;
    if (s.currentSlug !== `channel:${channelId}`) return false;
    return s.pins.some(
      (w) => envelopeIdentityKey(w.tool_name, w.envelope) === thisKey,
    );
  });

  // Pass display_label so post-action polling can refetch state-bearing tools
  // (e.g. schedule_task) using whatever identifier the template stored.
  const rawDispatch = useWidgetAction(
    channelId,
    botId ?? "default",
    currentEnvelope.display_label ?? null,
  );
  const broadcastEnvelope = usePinnedWidgetsStore((s) => s.broadcastEnvelope);

  // Intercepting dispatcher: captures response envelopes, updates local state, and broadcasts
  const interceptingDispatch = useCallback(
    async (action: import("../../types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      const result = await rawDispatch(action, value);

      if (
        result.envelope &&
        result.envelope.content_type === "application/vnd.spindrel.components+json" &&
        result.envelope.body
      ) {
        setCurrentEnvelope(result.envelope);
        if (channelId) {
          broadcastEnvelope(channelId, toolName, result.envelope);
        }
      }

      return result;
    },
    [rawDispatch, channelId, toolName, broadcastEnvelope],
  );

  // ── Live state refresh via state_poll ───────────────────────────────
  // When the envelope declares a refresh_interval_seconds (set by the
  // template engine from state_poll), poll the backend so the card shows
  // current status (e.g. a scheduled task flipping pending → running →
  // complete) without requiring a new tool call or page reload.
  const displayLabel = currentEnvelope.display_label ?? "";
  const intervalSec = currentEnvelope.refresh_interval_seconds;
  const refreshable = currentEnvelope.refreshable;
  const envelopeForRefreshRef = useRef(currentEnvelope);
  envelopeForRefreshRef.current = currentEnvelope;

  const refreshState = useCallback(async () => {
    if (!channelId || !botId || !refreshable) return;
    try {
      const resp = await apiFetch<{
        ok: boolean;
        envelope?: Record<string, unknown> | null;
        error?: string;
      }>("/api/v1/widget-actions/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool_name: toolName,
          display_label: envelopeForRefreshRef.current.display_label ?? "",
          channel_id: channelId,
          bot_id: botId,
        }),
      });
      if (resp.ok && resp.envelope) {
        const fresh = resp.envelope as unknown as ToolResultEnvelope;
        setCurrentEnvelope(fresh);
        broadcastEnvelope(channelId, toolName, fresh);
      }
    } catch {
      // Stale content is better than a flashing error banner here.
    }
  }, [channelId, botId, toolName, refreshable, broadcastEnvelope]);

  // Initial sync on mount: if the cached envelope is stale (e.g., scrolled
  // back to an older message), refresh once so the UI reflects current state.
  const initialRefreshKey = widgetId ?? `${toolName}:${displayLabel}`;
  const refreshedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!refreshable) return;
    if (refreshedForRef.current === initialRefreshKey) return;
    refreshedForRef.current = initialRefreshKey;
    refreshState();
  }, [initialRefreshKey, refreshable, refreshState]);

  // Interval refresh while status is non-terminal. The state_poll YAML sets
  // refresh_interval_seconds; we clear it client-side once the rendered body
  // reports a terminal status so idle/complete cards don't poll forever.
  const isTerminal = useMemo(() => {
    if (!currentEnvelope.body) return false;
    try {
      const parsed = typeof currentEnvelope.body === "string"
        ? JSON.parse(currentEnvelope.body)
        : currentEnvelope.body;
      for (const c of parsed?.components ?? []) {
        if (c.type === "status" && typeof c.text === "string") {
          const s = c.text.toLowerCase();
          if (s === "complete" || s === "completed" || s === "failed" ||
              s === "cancelled" || s === "canceled" || s === "done") {
            return true;
          }
        }
      }
    } catch { /* not JSON */ }
    return false;
  }, [currentEnvelope.body]);

  useEffect(() => {
    if (!refreshable || !intervalSec || intervalSec <= 0) return;
    if (isTerminal) return;
    const handle = setInterval(refreshState, intervalSec * 1000);
    return () => clearInterval(handle);
  }, [refreshable, intervalSec, isTerminal, refreshState]);

  // Subscribe to shared envelope map — sync from pinned widget actions
  const envelopeKey = channelId ? `${channelId}::${envelopeIdentityKey(toolName, currentEnvelope)}` : null;
  const sharedEnvelope = usePinnedWidgetsStore((s) =>
    envelopeKey ? s.widgetEnvelopes[envelopeKey] : undefined,
  );
  const envelopeRef = useRef(currentEnvelope);
  envelopeRef.current = currentEnvelope;
  useEffect(() => {
    if (sharedEnvelope && sharedEnvelope !== envelopeRef.current) {
      setCurrentEnvelope(sharedEnvelope);
    }
  }, [sharedEnvelope]);

  const actionCtx = useMemo(
    () => (channelId ? { dispatchAction: interceptingDispatch } : null),
    [channelId, interceptingDispatch],
  );

  const isHtmlWidget =
    currentEnvelope.content_type === "application/vnd.spindrel.html+interactive";

  // Normalize body to string. HTML widgets in path mode ship with an empty
  // body (renderer fetches the source file) — keep rendering in that case.
  const rawBody = currentEnvelope.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  if (body == null && !isHtmlWidget) return null;
  const hasPathSource = !!(currentEnvelope.source_path && currentEnvelope.source_channel_id);
  if (isHtmlWidget && !hasPathSource && !body) return null;

  const displayName = cleanToolName(toolName);

  // Auto-collapse: when pinned (older messages) or when defaultCollapsed is set (stacked widgets)
  const autoCollapsed = (isPinned && !isLatestBotMessage) || (defaultCollapsed ?? false);
  const isCollapsed = manualExpand !== null ? !manualExpand : autoCollapsed;

  const content = isHtmlWidget ? (
    <InteractiveHtmlRenderer envelope={currentEnvelope} channelId={channelId} t={t} />
  ) : showJson ? (
    <JsonTreeRenderer body={body ?? ""} t={t} />
  ) : (
    <ComponentRenderer body={body ?? ""} t={t} />
  );

  const wrapped = actionCtx ? (
    <WidgetActionContext.Provider value={actionCtx}>
      {content}
    </WidgetActionContext.Provider>
  ) : content;

  // Collapsed state: compact one-liner with pinned badge
  if (isCollapsed) {
    return (
      <button
        type="button"
        onClick={() => setManualExpand(true)}
        className="rounded-lg border mt-1.5 px-3 py-1.5 flex items-center gap-2 w-full text-left hover:bg-white/[0.02] transition-colors duration-150"
        style={{
          borderColor: isPinned ? `${t.accent}40` : t.surfaceBorder,
          backgroundColor: t.surfaceRaised,
        }}
      >
        <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: t.textDim }}>
          {displayName}
        </span>
        {isPinned && (
          <span className="flex items-center gap-0.5">
            <Pin size={9} fill={t.accent} style={{ color: t.accent }} />
            <span className="text-[9px] font-medium" style={{ color: t.accent, opacity: 0.8 }}>
              pinned
            </span>
          </span>
        )}
        <span className="ml-auto text-[10px]" style={{ color: t.textDim, opacity: 0.4 }}>
          expand
        </span>
      </button>
    );
  }

  return (
    <div
      className="rounded-lg border mt-1.5"
      style={{
        borderColor: isPinned ? `${t.accent}40` : t.surfaceBorder,
        backgroundColor: t.surfaceRaised,
      }}
    >
      {/* Header: tool name + pinned badge + pin button. Clicking the row
          (outside inner buttons) collapses the card. */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setManualExpand(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setManualExpand(false);
          }
        }}
        className="px-3 pt-2 pb-0.5 flex items-center gap-2 cursor-pointer hover:bg-white/[0.02] transition-colors duration-150"
        title="Collapse"
      >
        <ChevronDown size={11} style={{ color: t.textDim, flexShrink: 0 }} />
        <span
          className="text-[10px] font-medium uppercase tracking-wider"
          style={{ color: t.textDim }}
        >
          {displayName}
        </span>
        {isPinned && (
          <span className="flex items-center gap-0.5">
            <Pin size={9} fill={t.accent} style={{ color: t.accent }} />
            <span className="text-[9px] font-medium" style={{ color: t.accent, opacity: 0.8 }}>
              pinned
            </span>
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowJson(!showJson);
          }}
          className="text-[10px] px-1 py-0.5 transition-opacity bg-transparent border-0 cursor-pointer opacity-40 hover:opacity-100"
          style={{ color: t.textDim }}
          title={showJson ? "Show widget" : "Show JSON"}
        >
          {showJson ? "widget" : "json"}
        </button>
        {channelId && onPin && !isPinned && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onPin({
                widgetId: widgetId ?? `${toolName}-${Date.now()}`,
                envelope: currentEnvelope,
                toolName,
                channelId,
                // Prefer the envelope's own source_bot_id (stamped by
                // emit_html_widget / declarative widget templates at emit
                // time). The `"default"` literal fallback used to land here
                // whenever message metadata didn't carry a bot id — and
                // "default" happens to be a real bot row with no API key,
                // which poisoned the pin (mint 400 forever, refresh spam).
                botId: botId ?? currentEnvelope.source_bot_id ?? null,
              });
            }}
            className="p-0.5 rounded hover:bg-white/[0.06] transition-colors duration-150"
            title="Pin to side panel"
          >
            <Pin size={12} style={{ color: t.textDim, opacity: 0.5 }} />
          </button>
        )}
      </div>

      {/* Body: component or HTML content. HTML widgets own their own scroll
          inside the iframe (capped at 800px there), so we drop the outer
          max-height / overflow clip that would otherwise fight with it. */}
      <div
        className={
          isHtmlWidget
            ? "px-3 pb-2"
            : "px-3 pb-2 max-h-[400px] overflow-y-auto"
        }
      >
        {wrapped}
      </div>

    </div>
  );
}
