export function createWidgetRefreshBatcher(fetchBatch, flushDelayMs = 40) {
    let seq = 0;
    let timer = null;
    let pending = [];
    async function flush() {
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
        const batch = pending;
        pending = [];
        if (batch.length === 0)
            return;
        try {
            const resp = await fetchBatch({ requests: batch.map((item) => item.request) });
            const byId = new Map(resp.results.map((result) => [result.request_id, result]));
            for (const item of batch) {
                item.resolve(byId.get(item.request.request_id)
                    ?? {
                        request_id: item.request.request_id,
                        ok: false,
                        error: "Refresh response missing result",
                    });
            }
        }
        catch (error) {
            for (const item of batch)
                item.reject(error);
        }
    }
    return {
        request(request) {
            const request_id = `widget-refresh:${Date.now()}:${seq++}`;
            const promise = new Promise((resolve, reject) => {
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
            if (!timer)
                timer = setTimeout(() => { void flush(); }, flushDelayMs);
            return promise;
        },
        flush,
    };
}
export const widgetRefreshBatcher = createWidgetRefreshBatcher(async (body) => {
    const { apiFetch } = await import("../api/client");
    return apiFetch("/api/v1/widget-actions/refresh-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
});
export function requestWidgetRefresh(request) {
    return widgetRefreshBatcher.request(request);
}
