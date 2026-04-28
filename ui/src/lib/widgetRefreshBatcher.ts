import { apiFetch } from "../api/client";
import {
  createWidgetRefreshBatcher,
  type WidgetRefreshBatchItem,
  type WidgetRefreshBatchResult,
} from "./widgetRefreshBatcherCore";

interface BatchResponse {
  ok: boolean;
  results: WidgetRefreshBatchResult[];
}

export type { WidgetRefreshBatchItem, WidgetRefreshBatchResult };
export { createWidgetRefreshBatcher };

export const widgetRefreshBatcher = createWidgetRefreshBatcher((body) =>
  apiFetch<BatchResponse>("/api/v1/widget-actions/refresh-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
);

export function requestWidgetRefresh(request: WidgetRefreshBatchItem): Promise<WidgetRefreshBatchResult> {
  return widgetRefreshBatcher.request(request);
}
