/**
 * Aggregated cross-channel kanban view using swimlane board.
 * The per-channel kanban is in ChannelDetail's kanban tab.
 */
import { useState, useMemo } from "react";
import { useAggregatedKanban, useKanbanMove, useKanbanCreate, useKanbanUpdate } from "../hooks/useMC";
import { useOverview } from "../hooks/useOverview";
import { useScope } from "../lib/ScopeContext";
import KanbanSwimlane from "../components/KanbanSwimlane";
import ChannelFilterBar from "../components/ChannelFilterBar";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import InfoPanel from "../components/InfoPanel";
import ScopeToggle from "../components/ScopeToggle";

export default function Kanban() {
  const { scope } = useScope();
  const { data: columns, isLoading, error, refetch } = useAggregatedKanban(scope);
  const { data: overview } = useOverview(scope);
  const move = useKanbanMove();
  const update = useKanbanUpdate();
  const [channelFilter, setChannelFilter] = useState<string | null>(null);

  const channels = useMemo(() => {
    if (!overview?.channels) return [];
    return overview.channels.filter((ch) => ch.workspace_enabled);
  }, [overview]);

  const handleMove = (cardId: string, channelId: string, fromColumn: string, toColumn: string) => {
    move.mutate({ card_id: cardId, channel_id: channelId, from_column: fromColumn, to_column: toColumn });
  };

  const handleUpdate = (cardId: string, channelId: string, fields: Record<string, string>) => {
    update.mutate({ card_id: cardId, channel_id: channelId, ...fields });
  };

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="p-6"><ErrorBanner message={error.message} onRetry={() => refetch()} /></div>;

  return (
    <div className="h-screen flex flex-col">
      {/* Header area — padded */}
      <div className="px-6 pt-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-lg font-bold text-content">Kanban</h1>
            <p className="text-xs text-content-dim mt-0.5">Cross-channel task board</p>
          </div>
          <ScopeToggle />
        </div>

        <InfoPanel
          id="kanban"
          description="Aggregated task board across all tracked channels. Drag cards between columns."
          tips={[
            "Cards are grouped into swimlanes by channel for easy scanning.",
            "Click any card to see full details and edit inline.",
            "Task data is stored in each channel's workspace database.",
          ]}
        />

        {/* Channel filter */}
        {channels.length > 1 && (
          <div className="mb-3">
            <ChannelFilterBar channels={channels} value={channelFilter} onChange={setChannelFilter} />
          </div>
        )}

        {/* Error banner for move failures */}
        {move.isError && (
          <div className="mb-3">
            <ErrorBanner message="Failed to move card. Please try again." onRetry={() => move.reset()} />
          </div>
        )}
      </div>

      {/* Board area — edge to edge */}
      {columns && columns.length > 0 ? (
        <KanbanSwimlane
          columns={columns}
          onMove={handleMove}
          onUpdate={handleUpdate}
          moveDisabled={move.isPending}
          channelFilter={channelFilter}
        />
      ) : (
        <div className="px-6 pb-6">
          <EmptyState
            icon="▦"
            title="No kanban data"
            description="Channels need tasks.md files. Ask your bots to create task cards or use the kanban tools."
            tips={[
              "Channels need workspace enabled to track tasks.",
              "Ask a bot to create a task, or use + Add Card on the board.",
            ]}
            links={[{ label: "Go to Setup", to: "/setup" }]}
          />
        </div>
      )}
    </div>
  );
}
