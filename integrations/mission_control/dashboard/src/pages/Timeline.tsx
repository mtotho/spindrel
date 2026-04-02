import { useState, useMemo } from "react";
import { Plus, ArrowRight, CheckCircle, Circle, Ban, CornerDownRight, ListChecks, ThumbsUp, ThumbsDown } from "lucide-react";
import { useTimeline } from "../hooks/useMC";
import { useOverview } from "../hooks/useOverview";
import { useScope } from "../lib/ScopeContext";
import { channelColor } from "../lib/colors";
import { dateLabel } from "../lib/dates";
import ChannelFilterBar from "../components/ChannelFilterBar";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import InfoPanel from "../components/InfoPanel";
import ScopeToggle from "../components/ScopeToggle";

const DAY_OPTIONS = [7, 14, 30, 60];

function eventMeta(event: string): { Icon: typeof Circle; color: string; tint: string } {
  const e = event.toLowerCase();
  if (e.includes("complete") || e.includes("done"))
    return { Icon: CheckCircle, color: "#22c55e", tint: "rgba(34,197,94,0.08)" };
  if (e.includes("create") || e.includes("add"))
    return { Icon: Plus, color: "#3b82f6", tint: "rgba(59,130,246,0.08)" };
  if (e.includes("move"))
    return { Icon: ArrowRight, color: "#f59e0b", tint: "rgba(245,158,11,0.08)" };
  if (e.includes("plan"))
    return { Icon: ListChecks, color: "#a855f7", tint: "rgba(168,85,247,0.08)" };
  if (e.includes("approve"))
    return { Icon: ThumbsUp, color: "#22c55e", tint: "rgba(34,197,94,0.08)" };
  if (e.includes("reject") || e.includes("abandon"))
    return { Icon: ThumbsDown, color: "#ef4444", tint: "rgba(239,68,68,0.08)" };
  if (e.includes("skip"))
    return { Icon: CornerDownRight, color: "#9ca3af", tint: "rgba(156,163,175,0.08)" };
  return { Icon: Circle, color: "#9ca3af", tint: "transparent" };
}

export default function Timeline() {
  const { scope } = useScope();
  const [days, setDays] = useState(7);
  const [channelFilter, setChannelFilter] = useState<string | null>(null);

  const { data: events, isLoading, error, refetch } = useTimeline(days, scope);
  const { data: overview } = useOverview(scope);

  const channels = useMemo(() => {
    if (!overview?.channels) return [];
    return overview.channels.filter((ch) => ch.workspace_enabled);
  }, [overview]);

  const filtered = useMemo(() => {
    if (!events) return [];
    if (!channelFilter) return events;
    return events.filter((e) => e.channel_id === channelFilter);
  }, [events, channelFilter]);

  const grouped = useMemo(() => {
    const groups = new Map<string, typeof filtered>();
    for (const e of filtered) {
      if (!groups.has(e.date)) groups.set(e.date, []);
      groups.get(e.date)!.push(e);
    }
    return Array.from(groups);
  }, [filtered]);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Timeline</h1>
          <p className="text-sm text-gray-500 mt-1">Activity feed across channels</p>
        </div>
        <ScopeToggle />
      </div>

      <InfoPanel
        id="timeline"
        description="Activity events from task operations and plan state changes."
        tips={[
          "Events are auto-logged when cards are moved/created and plan statuses change.",
          "Filter by channel or time range to find specific events.",
        ]}
      />

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 mb-6">
        <div className="flex gap-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                days === d
                  ? "border-accent bg-accent text-white"
                  : "border-surface-3 text-gray-400 hover:text-gray-200"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>

        {channels.length > 1 && (
          <>
            <div className="w-px h-5 bg-surface-3" />
            <ChannelFilterBar channels={channels} value={channelFilter} onChange={setChannelFilter} />
          </>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="◉"
          title="No timeline events"
          description="Events from kanban moves, plan updates, and task completions will appear here."
          tips={[
            "Events are auto-logged on card moves and plan changes.",
          ]}
        />
      ) : (
        <div className="space-y-6">
          {grouped.map(([date, items]) => {
            const isToday = dateLabel(date) === "Today";
            const label = dateLabel(date);

            return (
              <div key={date}>
                <div className="flex items-center gap-2 mb-3 sticky top-0 bg-surface-0 py-1 z-10">
                  <h2 className="text-sm font-semibold text-gray-300">{label}</h2>
                  {isToday && (
                    <span className="px-1.5 py-px text-[10px] font-semibold rounded-full bg-accent/15 text-accent-hover">
                      Today
                    </span>
                  )}
                  <span className="text-[10px] text-gray-500">{items.length} event{items.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="space-y-1.5">
                  {items.map((ev, idx) => {
                    const { Icon, color, tint } = eventMeta(ev.event);
                    return (
                      <div
                        key={`${ev.channel_id}-${ev.time}-${idx}`}
                        className="flex items-start gap-3 py-2.5 px-3 rounded-lg border border-surface-3 transition-colors hover:border-surface-4"
                        style={{ borderLeftWidth: 3, borderLeftColor: color, backgroundColor: tint }}
                      >
                        <div
                          className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                          style={{ backgroundColor: `${color}20` }}
                        >
                          <Icon size={13} style={{ color }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-200">
                            <InlineBold text={ev.event} />
                          </p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span
                              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                              style={{ backgroundColor: channelColor(ev.channel_id) }}
                            />
                            <span className="text-xs text-gray-500">{ev.channel_name}</span>
                            <span className="text-xs text-gray-600">&middot;</span>
                            <span className="text-xs text-gray-500">{ev.time}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function InlineBold({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? (
          <strong key={i} className="font-semibold text-gray-100">{p.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
