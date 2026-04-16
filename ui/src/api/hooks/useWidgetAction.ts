import { useCallback } from "react";
import { apiFetch } from "../client";
import type { WidgetAction, ToolResultEnvelope } from "../../types/api";

interface WidgetActionRequest {
  dispatch: "tool" | "api";
  tool?: string;
  args?: Record<string, unknown>;
  endpoint?: string;
  method?: string;
  body?: Record<string, unknown>;
  channel_id: string;
  bot_id: string;
  source_record_id?: string;
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

export function useWidgetAction(channelId?: string, botId?: string) {
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

      if (action.dispatch === "tool") {
        req.tool = action.tool;
        req.args = args;
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
    [channelId, botId],
  );

  return dispatchAction;
}
