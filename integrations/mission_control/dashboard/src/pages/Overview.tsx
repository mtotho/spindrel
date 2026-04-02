import { useOverview } from "../hooks/useOverview";
import StatCard from "../components/StatCard";
import ChannelCard from "../components/ChannelCard";
import SetupGuide from "../components/SetupGuide";
import EmptyState from "../components/EmptyState";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";

export default function Overview() {
  const { data, isLoading, error, refetch } = useOverview();

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

  const pendingTasks = data.task_counts["pending"] || 0;
  const runningTasks = data.task_counts["running"] || 0;
  const workspaceChannels = data.channels.filter((ch) => ch.workspace_enabled);
  const needsSetup = workspaceChannels.length === 0;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">Overview</h1>
        <p className="text-sm text-gray-500 mt-1">Global status across all channels and bots</p>
      </div>

      {/* Setup guide — shown until first workspace channel exists */}
      {needsSetup && (
        <div className="mb-8">
          <SetupGuide
            hasServer={true}
            hasChannels={workspaceChannels.length > 0}
            hasBots={data.bot_count > 0}
          />
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Channels" value={data.channel_count} sub={`${workspaceChannels.length} with workspace`} />
        <StatCard label="Bots" value={data.bot_count} />
        <StatCard
          label="Pending Tasks"
          value={pendingTasks + runningTasks}
          color={pendingTasks + runningTasks > 0 ? "text-status-yellow" : "text-gray-100"}
        />
        <StatCard label="Sessions" value={data.session_count} />
      </div>

      {/* Channel grid */}
      <div className="mb-6">
        <h2 className="text-lg font-semibold text-gray-200 mb-3">Channels</h2>
        {workspaceChannels.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {workspaceChannels.map((ch) => (
              <ChannelCard key={ch.id} channel={ch} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon="◈"
            title="No workspace channels yet"
            description="Create a channel with workspace enabled in the admin UI, then it will appear here with file browsing, kanban boards, and activity logs."
          />
        )}
      </div>

      {/* Bots grid */}
      <div>
        <h2 className="text-lg font-semibold text-gray-200 mb-3">Bots</h2>
        {data.bots.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {data.bots.map((bot) => (
              <div
                key={bot.id}
                className="bg-surface-2 rounded-xl p-4 border border-surface-3"
              >
                <h3 className="text-sm font-medium text-gray-100">{bot.name}</h3>
                {bot.model && (
                  <p className="text-xs text-gray-500 mt-0.5 truncate" title={bot.model}>
                    {bot.model}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon="◉"
            title="No bots configured"
            description="Create a bot YAML file in bots/ or use the admin UI. Add the mission_control skill for structured task tracking."
          />
        )}
      </div>
    </div>
  );
}
