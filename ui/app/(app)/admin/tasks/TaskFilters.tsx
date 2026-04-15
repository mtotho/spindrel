import { AlertTriangle, XCircle } from "lucide-react";
import {
  type TaskTypeFilter, type StatusFilter,
  TASK_TYPE_FILTERS, STATUS_FILTERS,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// Filter toolbar (type + status pills, conflict/disabled indicators)
// ---------------------------------------------------------------------------
export function TaskFilters({
  typeFilter, setTypeFilter,
  statusFilter, setStatusFilter,
  disabledScheduleCount,
  conflictCount,
}: {
  typeFilter: TaskTypeFilter;
  setTypeFilter: (f: TaskTypeFilter) => void;
  statusFilter: StatusFilter;
  setStatusFilter: (f: StatusFilter) => void;
  disabledScheduleCount: number;
  conflictCount: number;
}) {
  return (
    <div className="flex flex-row items-center gap-1.5 px-5 py-2 border-b border-surface-raised overflow-x-auto flex-wrap">
      {/* Type filter pills */}
      <div className="flex flex-row items-center gap-1">
        <span className="text-[10px] text-text-dim font-semibold mr-0.5">TYPE</span>
        {TASK_TYPE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setTypeFilter(f.key)}
            className={`px-2.5 py-1 text-[11px] font-semibold border-none cursor-pointer rounded-full whitespace-nowrap transition-colors duration-100 ${
              typeFilter === f.key
                ? "bg-accent text-white"
                : "bg-surface-raised text-text-muted hover:text-text"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-surface-overlay mx-1" />

      {/* Status filter pills */}
      <div className="flex flex-row items-center gap-1">
        <span className="text-[10px] text-text-dim font-semibold mr-0.5">STATUS</span>
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatusFilter(f.key)}
            className={`px-2.5 py-1 text-[11px] font-semibold border-none cursor-pointer rounded-full whitespace-nowrap transition-colors duration-100 ${
              statusFilter === f.key
                ? f.key === "cancelled"
                  ? "bg-surface-border text-text-muted"
                  : f.key === "failed"
                    ? "bg-danger/[0.08] text-danger"
                    : "bg-accent text-white"
                : "bg-surface-raised text-text-muted hover:text-text"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Disabled schedules indicator */}
      {disabledScheduleCount > 0 && statusFilter !== "cancelled" && (
        <>
          <div className="w-px h-5 bg-surface-overlay mx-1" />
          <button
            onClick={() => setStatusFilter("cancelled")}
            className="inline-flex flex-row items-center gap-1 text-[11px] font-semibold text-text-dim bg-surface-raised px-2.5 py-[3px] rounded-full border-none cursor-pointer hover:text-text"
          >
            <XCircle size={11} className="text-text-dim" />
            {disabledScheduleCount} disabled
          </button>
        </>
      )}

      {/* Conflict indicator */}
      {conflictCount > 0 && (
        <>
          <div className="w-px h-5 bg-surface-overlay mx-1" />
          <span className="inline-flex flex-row items-center gap-1 text-[11px] font-bold text-warning-muted bg-warning/[0.08] px-2.5 py-[3px] rounded-full">
            <AlertTriangle size={11} className="text-warning-muted" />
            {conflictCount} bot{conflictCount !== 1 ? "s" : ""} with overlapping schedules
          </span>
        </>
      )}
    </div>
  );
}
