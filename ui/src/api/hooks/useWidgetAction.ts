import { useCallback } from "react";
import { apiFetch } from "../client";
import type { WidgetAction, ToolResultEnvelope } from "../../types/api";

interface WidgetActionRequest {
  dispatch: "tool" | "api" | "widget_config";
  tool?: string;
  args?: Record<string, unknown>;
  endpoint?: string;
  method?: string;
  body?: Record<string, unknown>;
  // widget_config dispatch
  pin_id?: string;
  config?: Record<string, unknown>;
  channel_id: string;
  bot_id: string;
  source_record_id?: string;
  /** When the dispatching widget has a state_poll, include display_label so the
   * backend can fetch fresh polled state after the action and return it. */
  display_label?: string;
  /** Current per-pin config — substituted into tool/state_poll args as {{config.*}}. */
  widget_config?: Record<string, unknown>;
}

interface WidgetActionResponse {
  ok: boolean;
  envelope?: Record<string, unknown> | null;
  error?: string | null;
  api_response?: Record<string, unknown> | null;
}

export interface WidgetActionResult {
  envelope: ToolResultEnvelope | null;
  apiResponse: Record<string, unknown> | null;
}

export function useWidgetAction(
  channelId?: string,
  botId?: string,
  displayLabel?: string | null,
  /** Pin ID of the enclosing PinnedToolWidget, if any — required for dispatch:"widget_config". */
  pinId?: string | null,
  /** Current widget config from the pin store, sent on tool/state_poll calls so
   *  {{config.*}} substitutes to live values. */
  widgetConfig?: Record<string, unknown> | null,
) {
  const dispatchAction = useCallback(
    async (action: WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      if (!channelId || !botId) {
        throw new Error("Missing channelId or botId for widget action");
      }

      // Build args — merge static args with dynamic value
      const args = { ...(action.args ?? {}) };
      if (action.value_key) {
        args[action.value_key] = value;
      }

      const req: WidgetActionRequest = {
        dispatch: action.dispatch,
        channel_id: channelId,
        bot_id: botId,
      };
      if (displayLabel) req.display_label = displayLabel;
      if (widgetConfig) req.widget_config = widgetConfig;

      if (action.dispatch === "tool") {
        req.tool = action.tool;
        req.args = args;
      } else if (action.dispatch === "widget_config") {
        if (!pinId) {
          throw new Error("widget_config dispatch requires an enclosing pinned widget");
        }
        req.pin_id = pinId;
        req.config = action.config ?? {};
      } else {
        req.endpoint = action.endpoint;
        req.method = action.method ?? "POST";
        req.body = args;
      }

      const resp = await apiFetch<WidgetActionResponse>(
        "/api/v1/widget-actions",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(req),
        },
      );

      if (!resp.ok) {
        throw new Error(resp.error ?? "Widget action failed");
      }

      return {
        envelope: (resp.envelope as ToolResultEnvelope | undefined) ?? null,
        apiResponse: resp.api_response ?? null,
      };
    },
    [channelId, botId, displayLabel, pinId, widgetConfig],
  );

  return dispatchAction;
}
