import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, MessageSquare, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useFeedbackReview, type FeedbackVote } from "@/src/api/hooks/useFeedbackReview";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { Spinner } from "@/src/components/shared/Spinner";
import { openTraceInspector } from "@/src/stores/traceInspector";

const VOTE_FILTERS: Array<{ label: string; value: FeedbackVote | "" }> = [
  { label: "All", value: "" },
  { label: "Down", value: "down" },
  { label: "Up", value: "up" },
];

function formatWhen(value?: string | null) {
  if (!value) return "Unknown";
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(ts));
}

function voteClasses(vote: FeedbackVote) {
  return vote === "down"
    ? "bg-danger/10 text-danger border-danger/30"
    : "bg-success/10 text-success border-success/30";
}

export default function AdminFeedbackPage() {
  const [vote, setVote] = useState<FeedbackVote | "">("");
  const [sinceHours, setSinceHours] = useState(168);
  const params = useMemo(() => ({ vote, since_hours: sinceHours, limit: 200 }), [vote, sinceHours]);
  const { data, isLoading, isFetching, refetch, error } = useFeedbackReview(params);
  const rows = data?.rows ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <PageHeader
        variant="list"
        title="User Feedback"
        subtitle="Explicit thumbs-up and thumbs-down votes on assistant turns."
        right={
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-surface-border bg-surface-raised px-3 text-xs font-semibold text-text-muted hover:text-text"
          >
            <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />
      <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-4 py-3">
        <div className="flex rounded-md border border-surface-border bg-surface-raised p-0.5">
          {VOTE_FILTERS.map((filter) => (
            <button
              key={filter.label}
              type="button"
              onClick={() => setVote(filter.value)}
              className={`h-8 rounded px-3 text-xs font-semibold ${vote === filter.value ? "bg-accent text-white" : "text-text-muted hover:text-text"}`}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <select
          value={sinceHours}
          onChange={(event) => setSinceHours(Number(event.target.value))}
          className="h-9 rounded-md border border-surface-border bg-surface-raised px-3 text-xs font-semibold text-text"
        >
          <option value={24}>Last 24h</option>
          <option value={168}>Last 7d</option>
          <option value={720}>Last 30d</option>
        </select>
        <span className="ml-auto text-xs text-text-muted">{data?.row_count ?? 0} rows</span>
      </div>
      <RefreshableScrollView
        refreshing={isFetching}
        onRefresh={() => refetch()}
        className="min-h-0 flex-1"
        contentContainerStyle={{ padding: 16 }}
      >
        {isLoading ? (
          <div className="flex h-48 items-center justify-center"><Spinner /></div>
        ) : error ? (
          <div className="rounded-md border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
            Failed to load feedback.
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-md border border-surface-border bg-surface-raised p-6 text-sm text-text-muted">
            No feedback found for this filter.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {rows.map((row, index) => {
              const VoteIcon = row.vote === "down" ? ThumbsDown : ThumbsUp;
              return (
                <div key={`${row.correlation_id}-${row.source_integration}-${row.source_user_ref ?? index}`} className="rounded-md border border-surface-border bg-surface-raised p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-bold ${voteClasses(row.vote)}`}>
                      <VoteIcon size={13} />
                      {row.vote}
                    </span>
                    <span className="text-sm font-semibold text-text">{row.channel_name ?? "Unknown channel"}</span>
                    {row.bot_id && <span className="rounded bg-surface-overlay px-2 py-1 text-xs text-text-muted">{row.bot_id}</span>}
                    <span className="text-xs text-text-dim">{row.source_integration}</span>
                    <span className="ml-auto text-xs text-text-dim">{formatWhen(row.updated_at ?? row.created_at)}</span>
                  </div>
                  {row.comment && (
                    <div className="mt-3 rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text">
                      {row.comment}
                    </div>
                  )}
                  <div className="mt-3 flex items-start gap-2 text-sm text-text-muted">
                    <MessageSquare size={14} className="mt-0.5 shrink-0 text-text-dim" />
                    <span>{row.anchor_excerpt || "No assistant text excerpt found."}</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() => openTraceInspector(row.correlation_id)}
                      className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-semibold text-text-muted hover:text-text"
                    >
                      Trace <ExternalLink size={12} />
                    </button>
                    <Link to={`/channels/${row.channel_id}`} className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 font-semibold text-text-muted hover:text-text">
                      Channel <ExternalLink size={12} />
                    </Link>
                    <span className="font-mono text-text-dim">{row.correlation_id}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </RefreshableScrollView>
    </div>
  );
}
