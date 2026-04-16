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
import { useState, useMemo, useCallback } from "react";
import type { ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { useWidgetAction } from "../../api/hooks/useWidgetAction";
import type { WidgetActionResult } from "../../api/hooks/useWidgetAction";
import { ComponentRenderer, WidgetActionContext } from "./renderers/ComponentRenderer";
import { JsonTreeRenderer } from "./renderers/JsonTreeRenderer";

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
  /** Future: callback when user pins this widget to a side panel */
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
}: WidgetCardProps) {
  const [currentEnvelope, setCurrentEnvelope] = useState(envelope);
  const [showJson, setShowJson] = useState(false);

  const rawDispatch = useWidgetAction(channelId, botId ?? "default");

  // Intercepting dispatcher: captures response envelopes and replaces card state
  const interceptingDispatch = useCallback(
    async (action: import("../../types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      const result = await rawDispatch(action, value);

      if (
        result.envelope &&
        result.envelope.content_type === "application/vnd.spindrel.components+json" &&
        result.envelope.body
      ) {
        setCurrentEnvelope(result.envelope);
      }

      return result;
    },
    [rawDispatch],
  );

  const actionCtx = useMemo(
    () => (channelId ? { dispatchAction: interceptingDispatch } : null),
    [channelId, interceptingDispatch],
  );

  // Normalize body to string
  const rawBody = currentEnvelope.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  if (body == null) return null;

  const displayName = cleanToolName(toolName);

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

  return (
    <div
      className="rounded-lg border mt-1.5"
      style={{
        borderColor: t.surfaceBorder,
        backgroundColor: t.surfaceRaised,
        maxWidth: 400,
      }}
    >
      {/* Header: tool name */}
      <div className="px-3 pt-2 pb-0.5 flex items-center justify-between">
        <span
          className="text-[10px] font-medium uppercase tracking-wider"
          style={{ color: t.textDim }}
        >
          {displayName}
        </span>
      </div>

      {/* Body: component content */}
      <div className="px-3 pb-2">
        {wrapped}
      </div>

      {/* Footer: json toggle */}
      <div className="flex justify-end px-2 pb-1">
        <button
          type="button"
          onClick={() => setShowJson(!showJson)}
          className="text-[10px] px-1 py-0.5 transition-opacity"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: t.textDim,
            opacity: 0.5,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
          onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.5"; }}
        >
          {showJson ? "widget" : "json"}
        </button>
      </div>
    </div>
  );
}
