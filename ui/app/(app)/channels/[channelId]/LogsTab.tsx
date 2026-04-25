import { useState, useMemo, useCallback } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useNavigate } from "react-router-dom";
import { ExternalLink, AlertTriangle, Wrench, X } from "lucide-react";
import { EmptyState } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  SettingsSearchBox,
  SettingsSegmentedControl,
} from "@/src/components/shared/SettingsControls";
import { TurnCard } from "@/src/components/shared/TurnCard";
import { useTurns } from "@/src/api/hooks/useTurns";
import { openTraceInspector } from "@/src/stores/traceInspector";

const PAGE_SIZE = 20;
type LogFilter = "all" | "errors" | "tools";

export function LogsTab({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const { width } = useWindowSize();
  const isMobile = width < 768;

  const [searchText, setSearchText] = useState("");
  const [filter, setFilter] = useState<LogFilter>("all");
  const [beforeCursor, setBeforeCursor] = useState<string | undefined>(undefined);

  const params = useMemo(() => ({
    count: PAGE_SIZE,
    channel_id: channelId,
    ...(searchText ? { search: searchText } : {}),
    ...(filter === "errors" ? { has_error: true as const } : {}),
    ...(filter === "tools" ? { has_tool_calls: true as const } : {}),
    ...(beforeCursor ? { before: beforeCursor } : {}),
  }), [beforeCursor, channelId, filter, searchText]);

  const { data, isLoading } = useTurns(params);
  const hasFilters = !!(searchText || filter !== "all");

  const clearFilters = useCallback(() => {
    setSearchText("");
    setFilter("all");
    setBeforeCursor(undefined);
  }, []);

  const handleLoadMore = useCallback(() => {
    if (data?.turns.length) {
      const lastTurn = data.turns[data.turns.length - 1];
      setBeforeCursor(lastTurn.created_at);
    }
  }, [data]);

  if (isLoading && !data) return <Spinner />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <SettingsSearchBox
          value={searchText}
          onChange={(value) => {
            setSearchText(value);
            setBeforeCursor(undefined);
          }}
          placeholder="Search messages..."
          className={isMobile ? "w-full" : "w-64"}
        />
        <div className="flex flex-wrap items-center gap-2">
          <SettingsSegmentedControl
            value={filter}
            onChange={(next) => {
              setFilter(next);
              setBeforeCursor(undefined);
            }}
            options={[
              { key: "all", label: "All" },
              { key: "errors", label: "Errors" },
              { key: "tools", label: "Tools" },
            ]}
          />
          {hasFilters && (
            <ActionButton
              label="Clear"
              onPress={clearFilters}
              variant="ghost"
              size="small"
              icon={<X size={12} />}
            />
          )}
        </div>
      </div>

      {data && data.turns.length > 0 && (
        <div className="flex items-center gap-2 text-[11px] text-text-dim">
          <span>{data.turns.length}{data.turns.length >= PAGE_SIZE ? "+" : ""} turns</span>
          {filter === "errors" && (
            <span className="inline-flex items-center gap-1 text-danger"><AlertTriangle size={11} /> errors only</span>
          )}
          {filter === "tools" && (
            <span className="inline-flex items-center gap-1 text-purple"><Wrench size={11} /> tools only</span>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        {data?.turns.map((turn) => (
          <TurnCard
            key={turn.correlation_id}
            turn={turn}
            isMobile={isMobile}
            onPress={(cid) => openTraceInspector(cid)}
            showBotBadge={false}
            showChannelBadge={false}
          />
        ))}
        {data?.turns.length === 0 && (
          <EmptyState message="No turns found." />
        )}
      </div>

      {data && data.turns.length >= PAGE_SIZE && (
        <div className="flex justify-center py-2">
          <ActionButton label="Load older turns" onPress={handleLoadMore} variant="secondary" />
        </div>
      )}

      <div>
        <ActionButton
          label="View all in Logs"
          onPress={() => navigate(`/admin/logs?channel_id=${channelId}`)}
          variant="primary"
          icon={<ExternalLink size={12} />}
        />
      </div>
    </div>
  );
}
