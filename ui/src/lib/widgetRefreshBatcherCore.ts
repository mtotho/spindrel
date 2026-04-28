import type { ToolResultEnvelope } from "../types/api";

export interface WidgetRefreshBatchItem {
  tool_name: string;
  display_label?: string;
  channel_id?: string | null;
  bot_id?: string | null;
  dashboard_pin_id?: string | null;
  widget_config?: Record<string, unknown> | null;
}

export interface WidgetRefreshBatchResult {
  request_id: string;
  ok: boolean;
  envelope?: ToolResultEnvelope | null;
  error?: string | null;
}

interface BatchResponse {
  ok: boolean;
  results: WidgetRefreshBatchResult[];
}

type FetchBatch = (body: { requests: Array<WidgetRefreshBatchItem & { request_id: string }> }) => Promise<BatchResponse>;

interface PendingRefresh {
  request: WidgetRefreshBatchItem & { request_id: string };
  resolve: (result: WidgetRefreshBatchResult) => void;
  reject: (error: unknown) => void;
}

export function createWidgetRefreshBatcher(fetchBatch: FetchBatch, flushDelayMs = 40) {
  let seq = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: PendingRefresh[] = [];

  async function flush() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    const batch = pending;
    pending = [];
    if (batch.length === 0) return;

    try {
      const resp = await fetchBatch({ requests: batch.map((item) => item.request) });
      const byId = new Map(resp.results.map((result) => [result.request_id, result]));
      for (const item of batch) {
        item.resolve(
          byId.get(item.request.request_id)
          ?? {
            request_id: item.request.request_id,
            ok: false,
            error: "Refresh response missing result",
          },
        );
      }
    } catch (error) {
      for (const item of batch) item.reject(error);
    }
  }

  return {
    request(request: WidgetRefreshBatchItem): Promise<WidgetRefreshBatchResult> {
      const request_id = `widget-refresh:${Date.now()}:${seq++}`;
      const promise = new Promise<WidgetRefreshBatchResult>((resolve, reject) => {
        pending.push({
          request: {
            ...request,
            request_id,
            display_label: request.display_label ?? "",
            widget_config: request.widget_config ?? {},
          },
          resolve,
          reject,
        });
      });
      if (!timer) timer = setTimeout(() => { void flush(); }, flushDelayMs);
      return promise;
    },
    flush,
  };
}
