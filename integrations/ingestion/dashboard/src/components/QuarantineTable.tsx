import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield, ShieldAlert, Loader2, Check } from "lucide-react";
import { fetchQuarantine, reprocess } from "../lib/api";
import type { QuarantineItem } from "../lib/api";

interface Props {
  storeName: string;
  classifierErrorCount: number;
  onRelease: () => void;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function isClassifierError(item: QuarantineItem): boolean {
  return (item.reason ?? "").startsWith("classifier error:");
}

export default function QuarantineTable({
  storeName,
  classifierErrorCount,
  onRelease,
}: Props) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["quarantine", storeName],
    queryFn: () => fetchQuarantine(storeName, 100),
    refetchInterval: 30_000,
  });

  const items = data?.items ?? [];

  const releaseMutation = useMutation({
    mutationFn: (body: {
      quarantine_ids?: number[];
      reason_pattern?: string;
    }) => reprocess(storeName, body),
    onSuccess: () => {
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["quarantine", storeName] });
      onRelease();
    },
  });

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === items.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(items.map((it) => it.id)));
    }
  };

  const releaseSelected = () => {
    if (selected.size === 0) return;
    releaseMutation.mutate({ quarantine_ids: Array.from(selected) });
  };

  const releaseAllClassifierErrors = () => {
    releaseMutation.mutate({ reason_pattern: "classifier error:%" });
  };

  return (
    <div>
      {/* Section header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-content-muted" />
          <h2 className="text-sm font-semibold">
            Quarantine — {storeName}
          </h2>
          <span className="text-xs text-content-dim">
            ({items.length} item{items.length !== 1 ? "s" : ""})
          </span>
        </div>

        {/* Bulk actions */}
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={releaseSelected}
              disabled={releaseMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs
                         bg-accent hover:bg-accent-hover text-white
                         disabled:opacity-50 transition-colors"
            >
              {releaseMutation.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Check className="w-3 h-3" />
              )}
              Release {selected.size} Selected
            </button>
          )}
          {classifierErrorCount > 0 && (
            <button
              onClick={releaseAllClassifierErrors}
              disabled={releaseMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs
                         bg-amber-600 hover:bg-amber-500 text-white
                         disabled:opacity-50 transition-colors"
            >
              {releaseMutation.isPending ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <ShieldAlert className="w-3 h-3" />
              )}
              Release All Classifier Errors ({classifierErrorCount})
            </button>
          )}
        </div>
      </div>

      {/* Success message */}
      {releaseMutation.isSuccess && (
        <div className="mb-3 px-3 py-2 rounded-md bg-status-green/10 text-status-green text-xs">
          Released {releaseMutation.data.released} item
          {releaseMutation.data.released !== 1 ? "s" : ""}. They will be
          re-ingested on the next poll cycle.
        </div>
      )}

      {/* Error message */}
      {releaseMutation.isError && (
        <div className="mb-3 px-3 py-2 rounded-md bg-status-red/10 text-status-red text-xs">
          Release failed: {(releaseMutation.error as Error).message}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="text-content-muted text-sm py-8 text-center">
          Loading quarantine...
        </div>
      )}

      {/* Empty state */}
      {!isLoading && items.length === 0 && (
        <div className="text-center py-8 text-content-dim text-sm">
          No quarantined items. All clear!
        </div>
      )}

      {/* Table */}
      {items.length > 0 && (
        <div className="rounded-lg border border-surface-3 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-surface-2 text-content-muted">
                <th className="w-8 px-3 py-2 text-left">
                  <input
                    type="checkbox"
                    checked={selected.size === items.length && items.length > 0}
                    onChange={toggleAll}
                    className="rounded border-surface-4"
                  />
                </th>
                <th className="px-3 py-2 text-left">Source ID</th>
                <th className="px-3 py-2 text-left">Reason</th>
                <th className="px-3 py-2 text-left">Risk</th>
                <th className="px-3 py-2 text-right">When</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item: QuarantineItem) => {
                const isError = isClassifierError(item);
                return (
                  <tr
                    key={item.id}
                    className={`border-t border-surface-3 transition-colors
                      ${
                        isError
                          ? "bg-amber-500/5 hover:bg-amber-500/10"
                          : item.risk_level === "high"
                            ? "bg-red-500/5 hover:bg-red-500/10"
                            : "hover:bg-surface-2"
                      }`}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(item.id)}
                        onChange={() => toggleSelect(item.id)}
                        className="rounded border-surface-4"
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-content-muted truncate max-w-[160px]">
                      {item.source_id}
                    </td>
                    <td className="px-3 py-2 truncate max-w-[300px]">
                      <span
                        className={
                          isError ? "text-amber-400" : "text-content-muted"
                        }
                      >
                        {item.reason || "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium
                          ${
                            item.risk_level === "high"
                              ? "bg-red-500/15 text-red-400"
                              : item.risk_level === "medium"
                                ? "bg-yellow-500/15 text-yellow-400"
                                : "bg-blue-500/15 text-blue-400"
                          }`}
                      >
                        {item.risk_level}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right text-content-dim whitespace-nowrap">
                      {timeAgo(item.quarantined_at)}
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
