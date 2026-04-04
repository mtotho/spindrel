import { Database, AlertTriangle, Clock } from "lucide-react";
import type { StoreOverview } from "../lib/api";

interface Props {
  store: StoreOverview;
  selected: boolean;
  onClick: () => void;
}

export default function StoreCard({ store, selected, onClick }: Props) {
  const stats = store.stats;
  const hasErrors = store.classifier_error_count > 0;
  const hasQuarantine = stats && stats.total_quarantined > 0;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-lg border p-4 transition-all
        ${
          selected
            ? "border-accent bg-accent/5 ring-1 ring-accent/30"
            : "border-surface-3 bg-surface-1 hover:border-surface-4 hover:bg-surface-2"
        }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-content-muted" />
          <span className="font-medium text-sm">{store.name}</span>
        </div>
        {store.error && (
          <span className="text-xs text-status-red">error</span>
        )}
      </div>

      {stats ? (
        <>
          {/* Main stats */}
          <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-xs mb-3">
            <div>
              <span className="text-content-dim">Processed</span>
              <span className="ml-2 font-mono text-content">
                {stats.total_processed.toLocaleString()}
              </span>
            </div>
            <div>
              <span className="text-content-dim">Quarantined</span>
              <span
                className={`ml-2 font-mono ${hasQuarantine ? "text-status-yellow" : "text-content"}`}
              >
                {stats.total_quarantined.toLocaleString()}
              </span>
            </div>
          </div>

          {/* Classifier errors */}
          {hasErrors && (
            <div className="flex items-center gap-1.5 mb-3 px-2 py-1 rounded bg-amber-500/10 text-amber-400 text-xs">
              <AlertTriangle className="w-3 h-3 flex-shrink-0" />
              <span>
                {store.classifier_error_count} classifier error
                {store.classifier_error_count !== 1 ? "s" : ""}
              </span>
            </div>
          )}

          {/* 24h activity */}
          <div className="flex items-center gap-1.5 text-xs text-content-dim">
            <Clock className="w-3 h-3" />
            <span>
              24h: {stats.processed_24h} processed / {stats.quarantined_24h}{" "}
              quarantined
            </span>
          </div>

          {/* Cursor info */}
          {stats.last_cursor.length > 0 && (
            <div className="mt-2 text-xs text-content-dim truncate">
              {stats.last_cursor.map((c) => (
                <div key={c.key} className="truncate">
                  <span className="text-content-muted">{c.key}:</span>{" "}
                  <span className="font-mono">{c.value}</span>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="text-xs text-content-dim">
          {store.error || "No data available"}
        </div>
      )}
    </button>
  );
}
