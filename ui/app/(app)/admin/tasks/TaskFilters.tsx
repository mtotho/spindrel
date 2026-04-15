import { AlertTriangle, XCircle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
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
  const t = useThemeTokens();

  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
      padding: "8px 20px", borderBottom: `1px solid ${t.surfaceRaised}`,
      overflowX: "auto", flexWrap: "wrap",
    }}>
      {/* Type filter pills */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, marginRight: 2 }}>TYPE</span>
        {TASK_TYPE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setTypeFilter(f.key)}
            style={{
              padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 12,
              background: typeFilter === f.key ? t.accent : t.surfaceRaised,
              color: typeFilter === f.key ? "#fff" : t.textMuted,
              whiteSpace: "nowrap",
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Separator */}
      <div style={{ width: 1, height: 20, background: t.surfaceOverlay, margin: "0 4px" }} />

      {/* Status filter pills */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, marginRight: 2 }}>STATUS</span>
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatusFilter(f.key)}
            style={{
              padding: "4px 10px", fontSize: 11, fontWeight: 600, border: "none", cursor: "pointer",
              borderRadius: 12,
              background: statusFilter === f.key
                ? (f.key === "cancelled" ? t.surfaceBorder : f.key === "failed" ? t.dangerSubtle : t.accent)
                : t.surfaceRaised,
              color: statusFilter === f.key
                ? (f.key === "cancelled" ? t.textMuted : f.key === "failed" ? t.danger : "#fff")
                : t.textMuted,
              whiteSpace: "nowrap",
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Disabled schedules indicator (clickable - switch to cancelled filter) */}
      {disabledScheduleCount > 0 && statusFilter !== "cancelled" && (
        <>
          <div style={{ width: 1, height: 20, background: t.surfaceOverlay, margin: "0 4px" }} />
          <button
            onClick={() => setStatusFilter("cancelled")}
            style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
              fontSize: 11, fontWeight: 600, color: t.textDim,
              background: t.surfaceRaised, padding: "3px 10px", borderRadius: 12,
              border: "none", cursor: "pointer",
            }}
          >
            <XCircle size={11} color={t.textDim} />
            {disabledScheduleCount} disabled
          </button>
        </>
      )}

      {/* Conflict indicator */}
      {conflictCount > 0 && (
        <>
          <div style={{ width: 1, height: 20, background: t.surfaceOverlay, margin: "0 4px" }} />
          <span style={{
            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
            fontSize: 11, fontWeight: 700, color: t.warningMuted,
            background: t.warningSubtle, padding: "3px 10px", borderRadius: 12,
          }}>
            <AlertTriangle size={11} color={t.warningMuted} />
            {conflictCount} bot{conflictCount !== 1 ? "s" : ""} with overlapping schedules
          </span>
        </>
      )}
    </div>
  );
}
