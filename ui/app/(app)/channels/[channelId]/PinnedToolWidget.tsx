/**
 * PinnedToolWidget — compact widget card for the OmniPanel pinned section.
 *
 * Same rendering pipeline as WidgetCard (ComponentRenderer + WidgetActionContext)
 * but adapted for side panel: drag handle, refresh, unpin controls.
 */
import { useState, useMemo, useCallback } from "react";
import { X, RefreshCw, GripVertical } from "lucide-react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWidgetAction } from "@/src/api/hooks/useWidgetAction";
import type { WidgetActionResult } from "@/src/api/hooks/useWidgetAction";
import { ComponentRenderer, WidgetActionContext } from "@/src/components/chat/renderers/ComponentRenderer";
import type { PinnedWidget, ToolResultEnvelope } from "@/src/types/api";

/** Strip MCP server prefix: "homeassistant-HassTurnOn" → "HassTurnOn" */
function cleanToolName(name: string): string {
  const idx = name.indexOf("-");
  return idx >= 0 ? name.slice(idx + 1) : name;
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
  const [refreshing, setRefreshing] = useState(false);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: widget.id });

  const rawDispatch = useWidgetAction(channelId, widget.bot_id);

  // Intercepting dispatcher: captures response envelopes and updates state
  const interceptingDispatch = useCallback(
    async (action: import("@/src/types/api").WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      const result = await rawDispatch(action, value);
      if (
        result.envelope &&
        result.envelope.content_type === "application/vnd.spindrel.components+json" &&
        result.envelope.body
      ) {
        setCurrentEnvelope(result.envelope);
        onEnvelopeUpdate(widget.id, result.envelope);
      }
      return result;
    },
    [rawDispatch, widget.id, onEnvelopeUpdate],
  );

  const actionCtx = useMemo(
    () => ({ dispatchAction: interceptingDispatch }),
    [interceptingDispatch],
  );

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const result = await rawDispatch(
        { dispatch: "tool", tool: widget.tool_name, args: {} },
        undefined,
      );
      if (result.envelope) {
        setCurrentEnvelope(result.envelope);
        onEnvelopeUpdate(widget.id, result.envelope);
      }
    } catch (err) {
      console.error("Widget refresh failed:", err);
    } finally {
      setRefreshing(false);
    }
  }, [rawDispatch, widget.tool_name, widget.id, onEnvelopeUpdate]);

  // Normalize body to string — guard against missing envelope
  const rawBody = currentEnvelope?.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  if (!currentEnvelope || body == null) return null;

  const sortableStyle = {
    transform: CSS.Transform.toString(transform),
    transition,
    borderColor: `${t.surfaceBorder}80`,
    opacity: isDragging ? 0.5 : 1,
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
          {widget.display_name || cleanToolName(widget.tool_name)}
        </span>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="p-0.5 rounded hover:bg-white/[0.06] transition-colors duration-150 flex-shrink-0"
          title="Refresh"
        >
          <RefreshCw
            size={12}
            className={refreshing ? "animate-spin" : ""}
            style={{ color: t.textMuted, opacity: 0.5 }}
          />
        </button>
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
      <div className="px-2 pb-2">
        <WidgetActionContext.Provider value={actionCtx}>
          <ComponentRenderer body={body} t={t} />
        </WidgetActionContext.Provider>
      </div>
    </div>
  );
}
