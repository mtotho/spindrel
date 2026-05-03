import { Activity, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { useLatestHealthSummary } from "../../../api/hooks/useSystemHealth";
import { DAILY_HEALTH_HREF } from "../../../lib/hubRoutes";
import { contextualNavigationState } from "../../../lib/contextualNavigation";
import { StatusBadge } from "../../shared/SettingsControls";
import { SectionHeading } from "./SectionHeading";
const HUB_BACK_STATE = contextualNavigationState("/", "Home");

function formatRelative(value: string | null | undefined): string {
  if (!value) return "never";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "never";
  const diff = Date.now() - dt.getTime();
  if (diff < 0) return "now";
  const min = Math.round(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  return `${d}d ago`;
}

/**
 * Daily Health rollup of yesterday's structured server errors. Always
 * visible — the absence of errors is itself useful information.
 */
export function DailyHealthSection({ onOpen }: { onOpen?: () => void }) {
  const { data } = useLatestHealthSummary();
  const summary = data?.summary ?? null;
  const errorCount = summary?.error_count ?? 0;
  const criticalCount = summary?.critical_count ?? 0;
  const qualityFindings = Number(summary?.source_counts?.agent_quality || 0);
  const services = summary
    ? Object.keys(summary.source_counts || {}).filter((key) => key !== "agent_quality").length
    : 0;

  let badge: { label: string; variant: "success" | "warning" | "danger" | "neutral" };
  let detail: string;

  if (summary === null) {
    badge = { label: "Pending", variant: "neutral" };
    detail = "First daily rollup hasn't run yet";
  } else if (criticalCount > 0) {
    badge = { label: `${criticalCount} crit`, variant: "danger" };
    detail = `${errorCount} err · ${services} svc · ${formatRelative(summary.generated_at)}`;
  } else if (errorCount > 0) {
    badge = { label: `${errorCount} err`, variant: "warning" };
    detail = `${services} svc · ${formatRelative(summary.generated_at)}`;
  } else if (qualityFindings > 0) {
    badge = { label: `${qualityFindings} quality`, variant: "warning" };
    detail = formatRelative(summary.generated_at);
  } else {
    badge = { label: "Clean", variant: "success" };
    detail = formatRelative(summary.generated_at);
  }

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading icon={<Activity size={14} />} label="Daily Health" />
      <Link
        to={DAILY_HEALTH_HREF}
        state={HUB_BACK_STATE}
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
        <StatusBadge label={badge.label} variant={badge.variant} />
        <span className="min-w-0 flex-1 truncate text-sm text-text-muted">{detail}</span>
        <ChevronRight
          size={14}
          className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
        />
      </Link>
    </section>
  );
}
