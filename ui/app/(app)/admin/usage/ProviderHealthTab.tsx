import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";

interface ProviderHealthRow {
  provider_id: string | null;
  provider_name: string | null;
  model: string;
  sample_count: number;
  latency_ms_p50: number | null;
  latency_ms_p95: number | null;
  cache_hit_rate: number | null;
  last_call_ts: string | null;
  cooldown_until_ts: string | null;
}

interface ProviderHealthResponse {
  window_hours: number;
  rows: ProviderHealthRow[];
}

function fmtLatency(ms: number | null): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function fmtCacheHit(rate: number | null): string {
  if (rate == null) return "--";
  return `${Math.round(rate * 100)}%`;
}

function fmtAgo(iso: string | null): string {
  if (!iso) return "--";
  const delta = Math.max(0, Date.now() - new Date(iso).getTime());
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function ProviderHealthTab({ windowHours = 24 }: { windowHours?: number }) {
  const { data, isLoading, error, refetch, isFetching } = useQuery<ProviderHealthResponse>({
    queryKey: ["admin-usage-provider-health", windowHours],
    queryFn: () =>
      apiFetch<ProviderHealthResponse>(
        `/api/v1/admin/usage/provider-health?hours=${windowHours}`,
      ),
  });

  if (isLoading) {
    return <div className="p-4 text-sm text-text-muted">Loading provider health...</div>;
  }
  if (error) {
    return (
      <div className="p-4 text-sm text-danger">
        Failed to load provider health: {(error as Error).message}
      </div>
    );
  }

  const rows = data?.rows ?? [];

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex flex-row items-center justify-between">
        <div className="text-xs text-text-muted">
          Over the last {data?.window_hours ?? windowHours}h. Latency + cache-hit derived
          from <code>token_usage</code> trace events.
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="px-2.5 py-1 text-xs font-semibold text-text-muted hover:text-text border border-surface-border rounded"
        >
          {isFetching ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="text-xs text-text-dim py-4">
          No LLM traffic in this window.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-text-dim border-b border-surface-border">
                <th className="py-1.5 pr-3 font-medium">Provider</th>
                <th className="py-1.5 pr-3 font-medium">Model</th>
                <th className="py-1.5 pr-3 font-medium text-right">Calls</th>
                <th className="py-1.5 pr-3 font-medium text-right">p50</th>
                <th className="py-1.5 pr-3 font-medium text-right">p95</th>
                <th className="py-1.5 pr-3 font-medium text-right">Cache hit</th>
                <th className="py-1.5 pr-3 font-medium text-right">Last call</th>
                <th className="py-1.5 pr-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => {
                const cooldown = r.cooldown_until_ts !== null;
                return (
                  <tr
                    key={`${r.provider_id ?? "env"}:${r.model}:${idx}`}
                    className="border-b border-surface-border/40"
                  >
                    <td className="py-1.5 pr-3 text-text-muted">
                      {r.provider_name || r.provider_id || <span className="text-text-dim">(.env)</span>}
                    </td>
                    <td className="py-1.5 pr-3 font-mono">{r.model}</td>
                    <td className="py-1.5 pr-3 text-right text-text-muted">{r.sample_count}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtLatency(r.latency_ms_p50)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtLatency(r.latency_ms_p95)}</td>
                    <td className="py-1.5 pr-3 text-right">{fmtCacheHit(r.cache_hit_rate)}</td>
                    <td className="py-1.5 pr-3 text-right text-text-muted">
                      {fmtAgo(r.last_call_ts)}
                    </td>
                    <td className="py-1.5 pr-3">
                      {cooldown ? (
                        <span className="text-danger font-semibold">
                          cooldown
                        </span>
                      ) : (
                        <span className="text-success">ok</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
