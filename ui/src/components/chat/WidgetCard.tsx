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
import { usePinnedWidgetsStore, envelopeIdentityKey } from "../../stores/pinnedWidgets";

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
    botId: string;
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

  // Check if this exact widget is already pinned.
  // Identity: record_id when available, else body content (distinguishes same tool on different entities)
  const isPinned = usePinnedWidgetsStore((s) => {
    if (!channelId) return false;
    return (s.byChannel[channelId] ?? []).some((w) => {
      if (w.tool_name !== toolName) return false;
      if (w.envelope.record_id && envelope.record_id) {
        return w.envelope.record_id === envelope.record_id;
      }
      // Fallback: compare body content — different entities produce different bodies
      const pinnedBody = typeof w.envelope.body === "string" ? w.envelope.body : JSON.stringify(w.envelope.body);
      const thisBody = typeof envelope.body === "string" ? envelope.body : JSON.stringify(envelope.body);
      return pinnedBody === thisBody;
    });
  });

  const rawDispatch = useWidgetAction(channelId, botId ?? "default");
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

  // Normalize body to string
  const rawBody = currentEnvelope.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  if (body == null) return null;

  const displayName = cleanToolName(toolName);

  // Auto-collapse: when pinned (older messages) or when defaultCollapsed is set (stacked widgets)
  const autoCollapsed = (isPinned && !isLatestBotMessage) || (defaultCollapsed ?? false);
  const isCollapsed = manualExpand !== null ? !manualExpand : autoCollapsed;

  const content = showJson ? (
    <JsonTreeRenderer body={body} t={t} />
  ) : (
    <ComponentRenderer body={body} t={t} />
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
                botId: botId ?? "default",
              });
            }}
            className="p-0.5 rounded hover:bg-white/[0.06] transition-colors duration-150"
            title="Pin to side panel"
          >
            <Pin size={12} style={{ color: t.textDim, opacity: 0.5 }} />
          </button>
        )}
      </div>

      {/* Body: component content */}
      <div className="px-3 pb-2 max-h-[400px] overflow-y-auto">
        {wrapped}
      </div>

    </div>
  );
}
