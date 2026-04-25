import { AlertTriangle, XCircle } from "lucide-react";
import { SelectDropdown } from "@/src/components/shared/SelectDropdown";
import {
  type TaskTypeFilter, type StatusFilter,
  TASK_TYPE_FILTERS, STATUS_FILTERS,
} from "./taskUtils";

// ---------------------------------------------------------------------------
// Filter toolbar (type + status — dropdowns on mobile, pills on desktop)
// ---------------------------------------------------------------------------
export function TaskFilters({
  typeFilter, setTypeFilter,
  statusFilter, setStatusFilter,
  disabledScheduleCount,
  conflictCount,
  isMobile,
  botFilter, setBotFilter, bots,
}: {
  typeFilter: TaskTypeFilter;
  setTypeFilter: (f: TaskTypeFilter) => void;
  statusFilter: StatusFilter;
  setStatusFilter: (f: StatusFilter) => void;
  disabledScheduleCount: number;
  conflictCount: number;
  isMobile?: boolean;
  botFilter?: string;
  setBotFilter?: (v: string) => void;
  bots?: Array<{ id: string; name?: string }>;
}) {
  if (isMobile) {
    return (
      <div className="flex flex-row items-center gap-2 px-4 py-2 border-b border-surface-raised overflow-x-auto">
        <SelectDropdown
          value={typeFilter}
          onChange={(next) => setTypeFilter(next as TaskTypeFilter)}
          options={TASK_TYPE_FILTERS.map((f) => ({ value: f.key, label: f.label }))}
          size="compact"
          popoverWidth="content"
          triggerClassName="min-h-[30px] min-w-[92px] bg-surface-raised/50 text-[11px]"
        />

        <SelectDropdown
          value={statusFilter}
          onChange={(next) => setStatusFilter(next as StatusFilter)}
          options={STATUS_FILTERS.map((f) => ({ value: f.key, label: f.label }))}
          size="compact"
          popoverWidth="content"
          triggerClassName="min-h-[30px] min-w-[92px] bg-surface-raised/50 text-[11px]"
        />

        {setBotFilter && (
          <SelectDropdown
            value={botFilter ?? ""}
            onChange={setBotFilter}
            options={[
              { value: "", label: "All Bots" },
              ...(bots?.map((b) => ({ value: b.id, label: b.name || b.id, searchText: `${b.name ?? ""} ${b.id}` })) ?? []),
            ]}
            searchable={(bots?.length ?? 0) > 8}
            size="compact"
            popoverWidth="content"
            triggerClassName="min-h-[30px] min-w-[104px] bg-surface-raised/50 text-[11px]"
          />
        )}

        {disabledScheduleCount > 0 && statusFilter !== "cancelled" && (
          <button
            onClick={() => setStatusFilter("cancelled")}
            className="inline-flex flex-row items-center gap-1 text-[11px] font-semibold text-text-dim bg-surface-raised px-2 py-[3px] rounded-full border-none cursor-pointer hover:text-text"
          >
            <XCircle size={10} className="text-text-dim" />
            {disabledScheduleCount}
          </button>
        )}

        {conflictCount > 0 && (
          <span className="inline-flex flex-row items-center gap-1 text-[10px] font-bold text-warning-muted bg-warning/[0.08] px-2 py-[3px] rounded-full shrink-0">
            <AlertTriangle size={10} className="text-warning-muted" />
            {conflictCount}
          </span>
        )}
      </div>
    );
  }

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
                ? "bg-surface-overlay text-text"
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
                    : "bg-surface-overlay text-text"
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
