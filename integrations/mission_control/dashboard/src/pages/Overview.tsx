import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  LayoutDashboard,
  BookOpen,
  Clock,
  Brain,
  ListChecks,
  CheckCircle2,
} from "lucide-react";
import { useOverview } from "../hooks/useOverview";
import { useTimeline, useAggregatedKanban, usePlans, useReadiness } from "../hooks/useMC";
import { useScope } from "../lib/ScopeContext";
import { botColor, channelColor } from "../lib/colors";
import StatCard from "../components/StatCard";
import ChannelCard from "../components/ChannelCard";
import SetupGuide from "../components/SetupGuide";
import InfoPanel from "../components/InfoPanel";
import EmptyState from "../components/EmptyState";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import ScopeToggle from "../components/ScopeToggle";

// Column colors for task progress bar
const COLUMN_COLORS: Record<string, string> = {
  backlog: "#6b7280",
  "in progress": "#3b82f6",
  review: "#f59e0b",
  done: "#22c55e",
};

export default function Overview() {
  const { scope } = useScope();
  const { data, isLoading, error, refetch } = useOverview(scope);

  if (isLoading) return <LoadingSpinner />;
  if (error) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-100">Mission Control</h1>
          <p className="text-sm text-gray-500 mt-1">Agent workspace dashboard</p>
        </div>
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
        <div className="mt-6">
          <SetupGuide hasServer={false} hasChannels={false} hasBots={false} />
        </div>
      </div>
    );
  }
  if (!data) return null;

  const workspaceChannels = data.channels.filter((ch) => ch.workspace_enabled);
  const needsSetup = workspaceChannels.length === 0;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Overview</h1>
          <p className="text-sm text-gray-500 mt-1">Global status across all channels and bots</p>
        </div>
        <ScopeToggle />
      </div>

      <InfoPanel
        id="overview"
        description="Your fleet at a glance — channels, bots, tasks, and activity."
        tips={[
          "Use the scope toggle (top-right) to switch between fleet-wide and personal views.",
          "Click any channel card to see its workspace, tasks, and config.",
          "The task distribution bar shows kanban column totals across all channels.",
        ]}
      />

      {needsSetup && (
        <div className="mb-8">
          <SetupGuide hasServer={true} hasChannels={false} hasBots={data.total_bots > 0} />
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Channels" value={data.total_channels_all} sub={`${workspaceChannels.length} with workspace`} />
        <StatCard label="Bots" value={data.total_bots} />
        <StatCard
          label="Tasks"
          value={data.total_tasks}
          color={data.total_tasks > 0 ? "text-status-yellow" : "text-gray-100"}
        />
        <StatCard label="Tracked" value={data.total_channels} sub="channels in scope" />
      </div>

      {/* Desktop: two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column (2/3) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Task progress bar */}
          <TaskProgressBar scope={scope} />

          {/* Channel grid */}
          <div>
            <h2 className="text-lg font-semibold text-gray-200 mb-3">Channels</h2>
            {workspaceChannels.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {workspaceChannels.map((ch) => (
                  <ChannelCard key={ch.id} channel={ch} />
                ))}
              </div>
            ) : (
              <EmptyState
                icon="◈"
                title="No workspace channels yet"
                description="Create a channel with workspace enabled in the admin UI."
              />
            )}
          </div>
        </div>

        {/* Right column (1/3) */}
        <div className="space-y-6">
          {/* Quick nav */}
          <QuickNav />

          {/* Activity feed */}
          <ActivityFeed scope={scope} />

          {/* Plans summary */}
          <PlansSummary scope={scope} />

          {/* Bots grid */}
          <div>
            <h2 className="text-sm font-semibold text-gray-200 mb-2">Bots</h2>
            {data.bots.length > 0 ? (
              <div className="space-y-1.5">
                {data.bots.map((bot) => {
                  const bc = botColor(bot.id);
                  return (
                    <div
                      key={bot.id}
                      className="flex items-center gap-2.5 px-3 py-2 bg-surface-2 rounded-lg border border-surface-3"
                    >
                      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: bc.dot }} />
                      <div className="flex-1 min-w-0">
                        <span className="text-xs font-medium text-gray-100">{bot.name}</span>
                        {bot.model && (
                          <span className="text-[10px] text-gray-500 ml-2 truncate">{bot.model}</span>
                        )}
                      </div>
                      {bot.channel_count > 0 && (
                        <span className="text-[10px] text-gray-600">{bot.channel_count} ch</span>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState icon="◉" title="No bots configured" description="Add a bot YAML in bots/." />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget: Task progress bar from aggregated kanban
// ---------------------------------------------------------------------------

function TaskProgressBar({ scope }: { scope: string | undefined }) {
  const { data: columns } = useAggregatedKanban(scope);

  const segments = useMemo(() => {
    if (!columns?.length) return [];
    return columns.map((col) => ({
      name: col.name,
      count: col.cards.length,
      color: COLUMN_COLORS[col.name.toLowerCase()] || "#6b7280",
    }));
  }, [columns]);

  const total = segments.reduce((s, seg) => s + seg.count, 0);
  if (total === 0) return null;

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
      <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider mb-2">Task Distribution</h3>
      <div className="h-3 rounded-full overflow-hidden flex">
        {segments.map((seg) =>
          seg.count > 0 ? (
            <div
              key={seg.name}
              className="h-full transition-all"
              style={{ width: `${(seg.count / total) * 100}%`, backgroundColor: seg.color }}
              title={`${seg.name}: ${seg.count}`}
            />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap gap-3 mt-2">
        {segments.map((seg) => (
          <div key={seg.name} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.color }} />
            <span className="text-[10px] text-gray-400">{seg.name} ({seg.count})</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget: Activity feed (last 5 timeline events)
// ---------------------------------------------------------------------------

function ActivityFeed({ scope }: { scope: string | undefined }) {
  const { data: events } = useTimeline(7, scope);
  const recent = useMemo(() => (events || []).slice(0, 5), [events]);
  if (recent.length === 0) return null;

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Recent Activity</h3>
        <Link to="/timeline" className="text-[10px] text-accent-hover hover:underline">View all &rarr;</Link>
      </div>
      <div className="space-y-1.5">
        {recent.map((ev, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ backgroundColor: channelColor(ev.channel_id) }} />
            <div className="flex-1 min-w-0">
              <p className="text-xs text-gray-300 truncate">
                <InlineBold text={ev.event} />
              </p>
              <p className="text-[10px] text-gray-500">{ev.time}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget: Plans summary
// ---------------------------------------------------------------------------

function PlansSummary({ scope }: { scope: string | undefined }) {
  const { data: plans } = usePlans(scope);

  const counts = useMemo(() => {
    if (!plans?.length) return null;
    const c = { executing: 0, awaiting: 0, draft: 0, complete: 0 };
    for (const p of plans) {
      if (p.status === "executing") c.executing++;
      else if (p.status === "awaiting_approval") c.awaiting++;
      else if (p.status === "draft") c.draft++;
      else if (p.status === "complete") c.complete++;
    }
    return c;
  }, [plans]);

  if (!counts) return null;

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Plans</h3>
        <Link to="/plans" className="text-[10px] text-accent-hover hover:underline">View plans &rarr;</Link>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-green-400" />
          <span className="text-gray-400">Executing: {counts.executing}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-gray-400" />
          <span className="text-gray-400">Complete: {counts.complete}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-yellow-400" />
          <span className="text-gray-400">Draft: {counts.draft}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-purple-400" />
          <span className="text-gray-400">Awaiting: {counts.awaiting}</span>
        </div>
      </div>
      {counts.awaiting > 0 && (
        <div className="mt-2 px-2 py-1 bg-purple-500/10 border border-purple-500/20 rounded-md text-[10px] text-purple-300">
          {counts.awaiting} plan{counts.awaiting !== 1 ? "s" : ""} awaiting approval
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget: Quick nav links
// ---------------------------------------------------------------------------

function QuickNav() {
  const { data: readiness } = useReadiness();

  const links = [
    { label: "Kanban", to: "/kanban", icon: LayoutDashboard, key: "kanban" },
    { label: "Timeline", to: "/timeline", icon: Clock, key: "timeline" },
    { label: "Plans", to: "/plans", icon: ListChecks, key: "plans" },
    { label: "Journal", to: "/journal", icon: BookOpen, key: "journal" },
    { label: "Memory", to: "/memory", icon: Brain, key: "memory" },
  ];

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-3">
      <div className="grid grid-cols-5 gap-1">
        {links.map((l) => {
          const ready = readiness?.[l.key as keyof typeof readiness]?.ready;
          const Icon = l.icon;
          return (
            <Link
              key={l.to}
              to={l.to}
              className="flex flex-col items-center gap-1 py-2 px-1 rounded-lg hover:bg-surface-3 transition-colors group"
            >
              <div className="relative">
                <Icon size={18} className="text-gray-400 group-hover:text-gray-200 transition-colors" />
                {ready !== undefined && (
                  <span
                    className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: ready ? "#22c55e" : "#f59e0b" }}
                  />
                )}
              </div>
              <span className="text-[10px] text-gray-500 group-hover:text-gray-300">{l.label}</span>
              {ready === false && (
                <Link to="/setup" className="text-[9px] text-yellow-500/80 hover:text-yellow-400 leading-none" onClick={(e) => e.stopPropagation()}>
                  Setup needed
                </Link>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline bold parser (**text** → <strong>)
// ---------------------------------------------------------------------------

function InlineBold({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? (
          <strong key={i} className="font-semibold text-gray-200">
            {p.slice(2, -2)}
          </strong>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
