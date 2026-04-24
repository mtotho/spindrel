import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ExternalLink, ChevronDown, ChevronRight, Clock, Zap, AlertTriangle } from "lucide-react";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { ActionButton, SettingsGroupLabel, StatusBadge } from "@/src/components/shared/SettingsControls";
import type { HeartbeatHistoryRun } from "@/src/types/api";

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function HeartbeatHistoryList({ history, isWide }: { history: HeartbeatHistoryRun[]; isWide?: boolean }) {
  const navigate = useNavigate();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <>
      <SettingsGroupLabel label="Recent Runs" />
      <div className="flex flex-col gap-1">
        {history.map((hb) => {
          const isExpanded = expandedId === hb.id;
          const hasContent = hb.result || hb.error || hb.correlation_id;
          return (
            <div key={hb.id}>
              <button
                type="button"
                onClick={() => hasContent && setExpandedId(isExpanded ? null : hb.id)}
                className={
                  `flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left transition-colors ` +
                  `${isExpanded ? "bg-surface-overlay/60" : "bg-surface-raised/40 hover:bg-surface-overlay/45"} ` +
                  `${hasContent ? "cursor-pointer" : "cursor-default"}`
                }
              >
                <div className="flex min-w-0 items-center gap-2">
                  {hasContent && (
                    isExpanded
                      ? <ChevronDown size={12} className="shrink-0 text-text-dim" />
                      : <ChevronRight size={12} className="shrink-0 text-text-dim" />
                  )}
                  <span className="truncate text-xs text-text-muted">
                    {new Date(hb.run_at).toLocaleString()}
                  </span>
                  {hb.completed_at && (
                    <span className="shrink-0 text-[10px] text-text-dim">
                      ({Math.round((new Date(hb.completed_at).getTime() - new Date(hb.run_at).getTime()) / 1000)}s)
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge
                    label={hb.status}
                    variant={hb.status === "complete" ? "success" : hb.status === "failed" ? "danger" : "neutral"}
                  />
                  {hb.repetition_detected && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-warning-muted">
                      <AlertTriangle size={10} /> repetitive
                    </span>
                  )}
                </div>
              </button>
              {isExpanded && (
                <div className="rounded-md bg-surface/80 px-3 py-2.5">
                  {hb.error && (
                    <div className="mb-2 whitespace-pre-wrap break-words rounded-md bg-danger/10 px-2 py-1.5 text-xs text-danger">
                      {hb.error}
                    </div>
                  )}
                  {hb.result && (
                    <div className="max-h-[200px] overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-text">
                      {hb.result}
                    </div>
                  )}
                  {(hb.iterations > 0 || hb.total_tokens > 0 || hb.duration_ms != null) && (
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-text-dim">
                      {hb.duration_ms != null && (
                        <span className="inline-flex items-center gap-1">
                          <Clock size={10} /> {fmtDuration(hb.duration_ms)}
                        </span>
                      )}
                      {hb.total_tokens > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <Zap size={10} /> {fmtTokens(hb.total_tokens)} tokens
                        </span>
                      )}
                      {hb.iterations > 0 && (
                        <span>{hb.iterations} iter</span>
                      )}
                    </div>
                  )}
                  {hb.tool_calls.length > 0 && (
                    <ToolCallsList toolCalls={hb.tool_calls as any} isWide={isWide} />
                  )}
                  {hb.correlation_id && (
                    <div className="mt-2">
                      <ActionButton
                        label="View trace"
                        onPress={() => navigate(`/admin/logs/${hb.correlation_id}`)}
                        icon={<ExternalLink size={11} />}
                        variant="primary"
                        size="small"
                      />
                    </div>
                  )}
                  {!hb.result && !hb.error && (
                    <div className="text-[11px] italic text-text-dim">No output recorded</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
