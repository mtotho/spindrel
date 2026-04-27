import { ChevronRight, Wind } from "lucide-react";
import { Link } from "react-router-dom";

import { useAgentSmell } from "../../../api/hooks/useUsage";
import { CONTEXT_BLOAT_HREF } from "../../../lib/hubRoutes";
import { StatusBadge } from "../../shared/SettingsControls";
import { SectionHeading } from "./SectionHeading";

function fmtTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
  return String(value);
}

function severityVariant(s: string | undefined): "danger" | "warning" | "info" | "success" {
  if (s === "critical") return "danger";
  if (s === "smelly") return "warning";
  if (s === "watch") return "info";
  return "success";
}

/**
 * Compact context-bloat callout. Renders only when at least one bot is
 * carrying unused tools/skills; tap opens the full Context Bloat panel.
 */
export function BloatSection({ onOpen }: { onOpen?: () => void }) {
  const { data } = useAgentSmell({ hours: 24, baseline_days: 7, limit: 25 });
  const summary = data?.summary;
  const bloated = summary?.bloated_bot_count ?? 0;
  if (!data || bloated === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading icon={<Wind size={14} />} label="Context bloat" />
      <Link
        to={CONTEXT_BLOAT_HREF}
        onClick={
          onOpen
            ? (event) => {
                event.preventDefault();
                onOpen();
              }
            : undefined
        }
        className="group flex min-h-[56px] items-center gap-3 rounded-md bg-surface-raised/40 px-3 py-2.5 transition-colors hover:bg-surface-overlay/45"
      >
        <StatusBadge
          label={String(bloated)}
          variant={severityVariant(summary?.max_severity)}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-text">
            {bloated} bot{bloated === 1 ? "" : "s"} carrying unused tools
          </div>
          <div className="truncate text-xs text-warning-muted">
            ~{fmtTokens(summary?.total_estimated_bloat_tokens ?? 0)} bloat tokens/turn
          </div>
        </div>
        <ChevronRight
          size={14}
          className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
        />
      </Link>
    </section>
  );
}
