/**
 * Global activity page — aggregates daily logs and recent turns across all channels.
 */

import { useQuery } from "@tanstack/react-query";
import { fetchFileChannels, fetchDailyLogs } from "../lib/api";
import MarkdownViewer from "../components/MarkdownViewer";
import EmptyState from "../components/EmptyState";
import LoadingSpinner from "../components/LoadingSpinner";
import type { DailyLog, FileChannel } from "../lib/types";

interface AggregatedLog extends DailyLog {
  channelId: string;
  channelName: string;
}

export default function Activity() {
  const { data, isLoading } = useQuery({
    queryKey: ["globalActivity"],
    queryFn: async () => {
      const channels = await fetchFileChannels();
      const allLogs: AggregatedLog[] = [];

      const batch = channels.slice(0, 10);
      const results = await Promise.allSettled(
        batch.map(async (ch: FileChannel) => {
          const logs = await fetchDailyLogs(ch.id, 7);
          return logs.map((log) => ({
            ...log,
            channelId: ch.id,
            channelName: ch.display_name || ch.id.slice(0, 8),
          }));
        }),
      );

      for (const result of results) {
        if (result.status === "fulfilled") {
          allLogs.push(...result.value);
        }
      }

      allLogs.sort((a, b) => b.date.localeCompare(a.date));
      return allLogs;
    },
    staleTime: 60_000,
  });

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content">Activity</h1>
        <p className="text-sm text-content-dim mt-1">Recent activity across all channels</p>
      </div>

      {!data?.length ? (
        <EmptyState
          icon="◉"
          title="No activity yet"
          description="Activity logs will appear here as bots work in channels. Each bot writes daily logs to memory/logs/ in its workspace."
        />
      ) : (
        <div className="space-y-4">
          {data.map((log) => (
            <div
              key={`${log.channelId}-${log.date}`}
              className="bg-surface-1 rounded-xl border border-surface-3 p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-medium text-content">
                  {log.date}
                </span>
                <span className="text-xs text-content-dim bg-surface-3 px-2 py-0.5 rounded">
                  {log.channelName}
                </span>
              </div>
              <MarkdownViewer content={log.content} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
