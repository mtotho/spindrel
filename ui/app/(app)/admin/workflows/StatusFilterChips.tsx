/**
 * Reusable status filter chip bar for workflow runs.
 */

import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import type { WorkflowRun } from "@/src/types/api";

const STATUSES = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "awaiting_approval", label: "Awaiting Approval" },
  { key: "complete", label: "Complete" },
  { key: "failed", label: "Failed" },
  { key: "cancelled", label: "Cancelled" },
] as const;

export type RunStatusFilter = typeof STATUSES[number]["key"];

interface Props {
  runs: WorkflowRun[];
  active: RunStatusFilter;
  onChange: (status: RunStatusFilter) => void;
}

function matchStatus(run: WorkflowRun, filter: string): boolean {
  if (filter === "complete") return run.status === "complete" || run.status === "done";
  return run.status === filter;
}

export function countByStatus(runs: WorkflowRun[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const s of STATUSES) {
    if (s.key === "all") {
      counts.all = runs.length;
    } else {
      counts[s.key] = runs.filter((r) => matchStatus(r, s.key)).length;
    }
  }
  return counts;
}

export function filterRuns(runs: WorkflowRun[], filter: RunStatusFilter): WorkflowRun[] {
  if (filter === "all") return runs;
  return runs.filter((r) => matchStatus(r, filter));
}

export function StatusFilterChips({ runs, active, onChange }: Props) {
  const t = useThemeTokens();
  const counts = countByStatus(runs);

  return (
    <div style={{
      display: "flex", flexDirection: "row", gap: 6, flexWrap: "wrap", alignItems: "center",
    }}>
      {STATUSES.map((s) => {
        const count = counts[s.key] ?? 0;
        if (s.key !== "all" && count === 0) return null;
        const isActive = active === s.key;
        return (
          <button type="button"
            key={s.key}
            onClick={() => onChange(s.key)}
            style={{
              display: "flex",
              flexDirection: "row", alignItems: "center", gap: 4,
              paddingInline: 10, paddingBlock: 4, borderRadius: 12,
              backgroundColor: isActive ? t.accentSubtle : t.codeBg,
              borderWidth: 1,
              borderColor: isActive ? t.accentBorder : t.surfaceBorder,
            }}
          >
            <span style={{
              fontSize: 11, fontWeight: isActive ? "600" : "400",
              color: isActive ? t.accent : t.textMuted,
            }}>
              {s.label}
            </span>
            <span style={{
              fontSize: 10,
              color: isActive ? t.accent : t.textDim,
            }}>
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
