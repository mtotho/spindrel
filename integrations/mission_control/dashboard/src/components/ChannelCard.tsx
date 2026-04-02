import { Link } from "react-router-dom";
import type { ChannelSummary } from "../lib/types";

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function ChannelCard({ channel }: { channel: ChannelSummary }) {
  return (
    <Link
      to={`/channels/${channel.id}`}
      className="block bg-surface-2 rounded-xl p-4 border border-surface-3 hover:border-accent/40 transition-colors group"
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-gray-100 truncate group-hover:text-accent-hover transition-colors">
            {channel.name || channel.id.slice(0, 8)}
          </h3>
          {(channel.bot_name || channel.bot_id) && (
            <p className="text-xs text-gray-500 mt-0.5 truncate">
              {channel.bot_name || channel.bot_id}
            </p>
          )}
        </div>
        {channel.workspace_enabled && (
          <span className="flex-shrink-0 w-2 h-2 rounded-full bg-status-green mt-1.5" />
        )}
      </div>
      {/* Badges row */}
      {(channel.task_count > 0 || channel.template_name) && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {channel.task_count > 0 && (
            <span className="text-[10px] text-gray-400 bg-surface-3 rounded-full px-2 py-px">
              {channel.task_count} task{channel.task_count !== 1 ? "s" : ""}
            </span>
          )}
          {channel.template_name && (
            <span className="text-[10px] text-gray-400 bg-surface-3 rounded-full px-2 py-px truncate max-w-[120px]">
              {channel.template_name}
            </span>
          )}
        </div>
      )}
      {channel.updated_at && (
        <p className="text-xs text-gray-600 mt-1.5">
          {timeAgo(channel.updated_at)}
        </p>
      )}
    </Link>
  );
}
