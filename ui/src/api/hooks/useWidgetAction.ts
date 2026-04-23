import { useCallback } from "react";
import { apiFetch } from "../client";
import type { WidgetAction, ToolResultEnvelope } from "../../types/api";

interface WidgetActionRequest {
  dispatch: "tool" | "api" | "widget_config" | "native_widget";
  tool?: string;
  args?: Record<string, unknown>;
  endpoint?: string;
  method?: string;
  body?: Record<string, unknown>;
  // widget_config dispatch — channel pin by id, dashboard pin by dashboard_pin_id.
  pin_id?: string;
  dashboard_pin_id?: string;
  widget_instance_id?: string;
  config?: Record<string, unknown>;
  action?: string;
  channel_id?: string;
  bot_id?: string;
  source_record_id?: string;
  /** When the dispatching widget has a state_poll, include display_label so the
   * backend can fetch fresh polled state after the action and return it. */
  display_label?: string;
  /** Current per-pin config — substituted into tool/state_poll args as {{widget_config.*}}. {{config.*}} remains a compatibility alias. */
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
  /** Channel-pin ID of the enclosing PinnedToolWidget, if any — required for dispatch:"widget_config". */
  pinId?: string | null,
  /** Current widget config from the pin store, sent on tool/state_poll calls so
   *  {{widget_config.*}} substitutes to live values. */
  widgetConfig?: Record<string, unknown> | null,
  /** Dashboard-pin ID — routes widget_config dispatch to the dashboard table.
   *  Mutually exclusive with `pinId`. */
  dashboardPinId?: string | null,
  /** Native widget instance id for dispatch:"native_widget". */
  widgetInstanceId?: string | null,
) {
  const dispatchAction = useCallback(
    async (action: WidgetAction, value: unknown): Promise<WidgetActionResult> => {
      // Channel-scope requires channelId+botId; dashboard-scope can omit them
      // for widget_config dispatch (refresh/tool calls still need a bot).
      const isDashboardScope = !!dashboardPinId;
      if (!isDashboardScope && (!channelId || !botId)) {
        throw new Error("Missing channelId or botId for widget action");
      }

      // Build args — merge static args with dynamic value
      const args = { ...(action.args ?? {}) };
      if (action.value_key) {
        args[action.value_key] = value;
      }

      const req: WidgetActionRequest = {
        dispatch: action.dispatch,
      };
      if (channelId) req.channel_id = channelId;
      if (botId) req.bot_id = botId;
      if (displayLabel) req.display_label = displayLabel;
      if (widgetConfig) req.widget_config = widgetConfig;

      if (action.dispatch === "tool") {
        req.tool = action.tool;
        req.args = args;
      } else if (action.dispatch === "native_widget") {
        req.action = action.action;
        req.args = args;
        if (widgetInstanceId) req.widget_instance_id = widgetInstanceId;
        if (dashboardPinId) req.dashboard_pin_id = dashboardPinId;
        if (!req.widget_instance_id && !req.dashboard_pin_id) {
          throw new Error("native_widget dispatch requires widget instance or pin context");
        }
      } else if (action.dispatch === "widget_config") {
        if (dashboardPinId) {
          req.dashboard_pin_id = dashboardPinId;
        } else if (pinId) {
          req.pin_id = pinId;
        } else {
          throw new Error("widget_config dispatch requires an enclosing pinned widget");
        }
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
    [channelId, botId, displayLabel, pinId, widgetConfig, dashboardPinId, widgetInstanceId],
  );

  return dispatchAction;
}
