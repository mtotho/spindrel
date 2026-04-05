import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Rss, RefreshCw, AlertTriangle } from "lucide-react";
import { fetchOverview } from "./lib/api";
import type { StoreOverview } from "./lib/api";
import StoreCard from "./components/StoreCard";
import QuarantineTable from "./components/QuarantineTable";

export default function App() {
  const queryClient = useQueryClient();
  const [selectedStore, setSelectedStore] = useState<string | null>(null);

  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ["overview"],
    queryFn: fetchOverview,
    refetchInterval: 30_000,
  });

  const stores = data?.stores ?? [];
  const activeStore = stores.find((s) => s.name === selectedStore) ?? null;

  // Auto-select first store with quarantine items
  useEffect(() => {
    if (!selectedStore && stores.length > 0) {
      const withQuarantine = stores.find(
        (s) => s.stats && s.stats.total_quarantined > 0,
      );
      setSelectedStore(withQuarantine?.name ?? stores[0].name);
    }
  }, [selectedStore, stores]);

  const totalQuarantined = stores.reduce(
    (sum, s) => sum + (s.stats?.total_quarantined ?? 0),
    0,
  );
  const totalClassifierErrors = stores.reduce(
    (sum, s) => sum + s.classifier_error_count,
    0,
  );

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Rss className="w-6 h-6 text-accent" />
          <h1 className="text-xl font-semibold">Content Feeds</h1>
          {totalClassifierErrors > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 text-xs font-medium">
              <AlertTriangle className="w-3 h-3" />
              {totalClassifierErrors} classifier error
              {totalClassifierErrors !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <button
          onClick={() => queryClient.invalidateQueries({ queryKey: ["overview"] })}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs
                     bg-surface-2 hover:bg-surface-3 text-content-muted
                     transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Loading / Error */}
      {isLoading && (
        <div className="text-content-muted text-sm">Loading feed data...</div>
      )}
      {error && (
        <div className="text-status-red text-sm mb-4">
          Failed to load: {(error as Error).message}
        </div>
      )}

      {/* Store cards */}
      {stores.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
          {stores.map((store: StoreOverview) => (
            <StoreCard
              key={store.name}
              store={store}
              selected={store.name === selectedStore}
              onClick={() => setSelectedStore(store.name)}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && stores.length === 0 && (
        <div className="text-center py-16 text-content-dim">
          <Rss className="w-10 h-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No feed stores found.</p>
          <p className="text-xs mt-1">
            Content feeds will appear here once configured.
          </p>
        </div>
      )}

      {/* Quarantine section */}
      {activeStore && (
        <QuarantineTable
          storeName={activeStore.name}
          classifierErrorCount={activeStore.classifier_error_count}
          onRelease={() =>
            queryClient.invalidateQueries({ queryKey: ["overview"] })
          }
        />
      )}

      {/* Footer with last update time */}
      {dataUpdatedAt > 0 && (
        <div className="mt-8 text-center text-xs text-content-dim">
          Last updated: {new Date(dataUpdatedAt).toLocaleTimeString()}
          {" · "}{totalQuarantined} total quarantined across {stores.length} store
          {stores.length !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
