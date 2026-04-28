import { Link } from "react-router-dom";
import { Bot, ChevronRight, Radar, Route, Sparkles } from "lucide-react";

import { useMissionControl } from "../../../api/hooks/useMissionControl";
import { contextualNavigationState } from "../../../lib/contextualNavigation";
import { SectionHeading } from "./SectionHeading";

const HUB_BACK_STATE = contextualNavigationState("/", "Home");

function formatRelative(value?: string | null): string {
  if (!value) return "manual";
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return "unknown";
  const minutes = Math.round((ts - Date.now()) / 60000);
  if (minutes < 0) return "due";
  if (minutes < 1) return "now";
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

export function MissionControlSection() {
  const { data } = useMissionControl();
  if (!data) return null;

  const activeRows = data.lanes
    .flatMap((lane) => lane.missions.map((row) => ({ lane, row })))
    .slice(0, 2);
  const hasSignal =
    data.summary.active_missions > 0 ||
    data.summary.paused_missions > 0 ||
    data.summary.spatial_warnings > 0 ||
    data.summary.recent_updates > 0 ||
    data.drafts.length > 0 ||
    Boolean(data.assistant_brief);

  if (!hasSignal) return null;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading
        icon={<Radar size={14} />}
        label="Mission Control"
        count={data.summary.active_missions + data.drafts.length}
        action={
          <Link to="/hub/mission-control" state={HUB_BACK_STATE} className="text-[11px] font-medium text-accent">
            Open
          </Link>
        }
      />
      <Link
        to="/hub/mission-control"
        state={HUB_BACK_STATE}
        className="group rounded-md bg-surface-raised/45 px-3 py-3 transition-colors hover:bg-surface-overlay/45"
      >
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
            <Sparkles size={15} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-text">
              {data.assistant_brief?.summary ?? "Workspace operator summary"}
            </div>
            <div className="mt-1 truncate text-xs text-text-dim">
              {data.summary.active_missions} active · {data.drafts.length} staged · {data.summary.spatial_warnings} spatial warnings · {data.summary.recent_updates} updates
            </div>
          </div>
          <ChevronRight size={14} className="mt-1 shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
        {activeRows.length > 0 ? (
          <div className="mt-3 flex flex-col gap-1">
            {activeRows.map(({ lane, row }) => (
              <div key={`${lane.bot_id}-${row.mission.id}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-md bg-surface-overlay/35 px-2 py-2">
                <Route size={13} className="text-accent" />
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium text-text">{row.mission.title}</div>
                  <div className="truncate text-[11px] text-text-dim">
                    <Bot size={11} className="mr-1 inline" />
                    {lane.bot_name}
                    {row.mission.channel_name ? ` · #${row.mission.channel_name}` : ""}
                  </div>
                </div>
                <span className="text-[11px] tabular-nums text-text-dim">{formatRelative(row.mission.next_run_at)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </Link>
    </section>
  );
}
