import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { EmptyState } from "@/src/components/shared/FormControls";
import { InfoBanner, QuietPill, SettingsControlRow } from "@/src/components/shared/SettingsControls";
import { apiFetch } from "@/src/api/client";
import { useQuery } from "@tanstack/react-query";

interface CompactionToolCall {
  tool_name: string;
  tool_type: string;
  iteration?: number | null;
  duration_ms?: number | null;
  error?: string | null;
  arguments_preview?: string | null;
  result_preview?: string | null;
}

export interface CompactionLogEntry {
  id: string;
  model: string;
  history_mode: string;
  tier: string;
  forced: boolean;
  memory_flush: boolean;
  messages_archived: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  duration_ms: number | null;
  section_id: string | null;
  error: string | null;
  created_at: string | null;
  correlation_id?: string | null;
  flush_result?: string | null;
  tool_calls?: CompactionToolCall[];
  flush_tokens?: number | null;
  flush_iterations?: number | null;
}

function _relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function _detailRow(label: string, value: string | number | null | undefined) {
  if (value == null || value === "") return null;
  return (
    <div className="flex gap-2 text-[10px] leading-relaxed">
      <span className="min-w-20 shrink-0 text-text-dim">{label}</span>
      <span className="font-mono text-text-muted">{value}</span>
    </div>
  );
}

export function CompactionActivity({ channelId }: { channelId: string }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery<{ logs: CompactionLogEntry[]; total: number }>({
    queryKey: ["compaction-logs", channelId],
    queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/compaction-logs?limit=20`),
  });

  if (isLoading) return <Spinner size={16} />;
  if (isError) return <InfoBanner variant="danger">Failed to load compaction logs.</InfoBanner>;
  const logs: CompactionLogEntry[] = data?.logs ?? [];
  if (logs.length === 0) {
    return <EmptyState message="No compaction events yet." />;
  }

  return (
    <div className="flex flex-col gap-1.5">
      {logs.map((log) => {
        const isOpen = expandedId === log.id;
        return (
          <div key={log.id} className="overflow-hidden rounded-md bg-surface-raised/40">
            {/* Summary row */}
            <SettingsControlRow
              onClick={() => setExpandedId(isOpen ? null : log.id)}
              active={isOpen}
              compact
              leading={<span className="min-w-12 font-mono text-[10px] text-text-dim">{log.created_at ? _relativeTime(log.created_at) : "\u2014"}</span>}
              title={log.model}
              meta={
                <div className="flex flex-wrap items-center gap-1.5">
                  <QuietPill label={log.tier} />
                  {log.total_tokens != null && <span>{log.total_tokens.toLocaleString()} tok</span>}
                  {log.duration_ms != null && <span>{(log.duration_ms / 1000).toFixed(1)}s</span>}
                  {log.messages_archived != null && <span>{log.messages_archived} msgs</span>}
                  {log.memory_flush && <QuietPill label="flush" />}
                  {log.forced && <QuietPill label="forced" />}
                  {log.error && <AlertTriangle size={12} className="text-danger" />}
                  <span className={`text-[10px] text-text-dim transition-transform ${isOpen ? "rotate-180" : ""}`}>&#9660;</span>
                </div>
              }
            />

            {/* Expanded details */}
            {isOpen && (
              <div className="flex flex-col gap-1 border-t border-surface-border/50 px-3 pb-3 pt-2">
                {_detailRow("Model", log.model)}
                {_detailRow("History mode", log.history_mode)}
                {_detailRow("Tier", log.tier)}
                {_detailRow("Prompt tokens", log.prompt_tokens?.toLocaleString())}
                {_detailRow("Completion tokens", log.completion_tokens?.toLocaleString())}
                {_detailRow("Total tokens", log.total_tokens?.toLocaleString())}
                {_detailRow("Duration", log.duration_ms != null ? `${(log.duration_ms / 1000).toFixed(2)}s` : null)}
                {_detailRow("Messages archived", log.messages_archived)}
                {_detailRow("Memory flush", log.memory_flush ? "yes" : "no")}
                {_detailRow("Forced", log.forced ? "yes" : "no")}
                {log.flush_tokens != null && _detailRow("Flush tokens", log.flush_tokens.toLocaleString())}
                {log.flush_iterations != null && _detailRow("Flush iterations", String(log.flush_iterations))}
                {_detailRow("Section ID", log.section_id)}
                {_detailRow("Timestamp", log.created_at ? new Date(log.created_at).toLocaleString() : null)}
                {log.correlation_id && (
                  <div className="mt-1 flex items-center gap-1">
                    <a
                      href={`/admin/logs/${log.correlation_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[10px] text-accent no-underline hover:text-accent/80"
                    >
                      <ExternalLink size={10} /> View trace
                    </a>
                  </div>
                )}
                {log.flush_result && (
                  <div className="mt-1 rounded-md bg-surface-overlay/35 px-2.5 py-2">
                    <div className="mb-1 text-[10px] font-semibold text-purple">Flush result</div>
                    <div className="max-h-[200px] overflow-y-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-text">{log.flush_result}</div>
                  </div>
                )}
                {log.tool_calls && log.tool_calls.length > 0 && (
                  <ToolCallsList toolCalls={log.tool_calls} isWide />
                )}
                {log.error && (
                  <InfoBanner variant="danger">
                    <span className="whitespace-pre-wrap font-mono text-[10px]">{log.error}</span>
                  </InfoBanner>
                )}
              </div>
            )}
          </div>
        );
      })}
      {(data?.total ?? 0) > logs.length && (
        <div className="px-2.5 py-1 text-[10px] text-text-dim">
          Showing {logs.length} of {data?.total ?? 0} events
        </div>
      )}
    </div>
  );
}
