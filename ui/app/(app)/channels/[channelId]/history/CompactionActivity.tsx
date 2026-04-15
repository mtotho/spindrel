import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
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

export const TIER_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  normal: { bg: "rgba(34,197,94,0.10)", text: "#16a34a", border: "rgba(34,197,94,0.3)" },
  aggressive: { bg: "rgba(234,179,8,0.10)", text: "#ca8a04", border: "rgba(234,179,8,0.3)" },
  deterministic: { bg: "rgba(239,68,68,0.10)", text: "#dc2626", border: "rgba(239,68,68,0.3)" },
};

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

function _detailRow(label: string, value: string | number | null | undefined, t: ReturnType<typeof useThemeTokens>) {
  if (value == null || value === "") return null;
  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 8, fontSize: 10, lineHeight: "1.5" }}>
      <span style={{ color: t.textDim, minWidth: 80, flexShrink: 0 }}>{label}</span>
      <span style={{ color: t.textMuted, fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

export function CompactionActivity({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery<{ logs: CompactionLogEntry[]; total: number }>({
    queryKey: ["compaction-logs", channelId],
    queryFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/compaction-logs?limit=20`),
  });

  if (isLoading) return <Spinner size={16} />;
  if (isError) return <div style={{ fontSize: 12, color: "#ef4444", padding: "8px 0" }}>Failed to load compaction logs.</div>;
  const logs: CompactionLogEntry[] = data?.logs ?? [];
  if (logs.length === 0) {
    return <div style={{ fontSize: 12, color: t.textDim, padding: "8px 0" }}>No compaction events yet.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {logs.map((log) => {
        const tierColor = TIER_COLORS[log.tier] ?? TIER_COLORS.normal;
        const isOpen = expandedId === log.id;
        return (
          <div key={log.id} style={{
            borderRadius: 6, background: t.inputBg, overflow: "hidden",
          }}>
            {/* Summary row */}
            <button
              onClick={() => setExpandedId(isOpen ? null : log.id)}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 8, padding: "6px 10px",
                fontSize: 11, width: "100%", background: "none", border: "none",
                cursor: "pointer", textAlign: "left",
              }}
            >
              <span style={{ color: t.textDim, minWidth: 52, flexShrink: 0 }}>
                {log.created_at ? _relativeTime(log.created_at) : "\u2014"}
              </span>
              <StatusBadge label={log.tier} customColors={{ bg: tierColor.bg, fg: tierColor.text }} />
              <span style={{ color: t.textMuted, flexShrink: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {log.model}
              </span>
              {log.total_tokens != null && (
                <span style={{ color: t.textDim, flexShrink: 0 }}>
                  {log.total_tokens.toLocaleString()} tok
                </span>
              )}
              {log.duration_ms != null && (
                <span style={{ color: t.textDim, flexShrink: 0 }}>
                  {(log.duration_ms / 1000).toFixed(1)}s
                </span>
              )}
              {log.messages_archived != null && (
                <span style={{ color: t.textDim, flexShrink: 0 }}>
                  {log.messages_archived} msgs
                </span>
              )}
              {log.memory_flush && (
                <StatusBadge label="flush" customColors={{ bg: "rgba(139,92,246,0.10)", fg: "#7c3aed" }} />
              )}
              {log.forced && (
                <StatusBadge label="forced" customColors={{ bg: "rgba(59,130,246,0.10)", fg: "#2563eb" }} />
              )}
              {log.error && (
                <span style={{ color: "#dc2626" }}>
                  <AlertTriangle size={12} />
                </span>
              )}
              <span style={{
                fontSize: 10, color: t.textDim, marginLeft: "auto", flexShrink: 0,
                transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
                transition: "transform 0.15s",
              }}>&#9660;</span>
            </button>

            {/* Expanded details */}
            {isOpen && (
              <div style={{
                padding: "8px 12px 10px", borderTop: `1px solid ${t.surfaceOverlay}`,
                display: "flex", flexDirection: "column", gap: 4,
              }}>
                {_detailRow("Model", log.model, t)}
                {_detailRow("History mode", log.history_mode, t)}
                {_detailRow("Tier", log.tier, t)}
                {_detailRow("Prompt tokens", log.prompt_tokens?.toLocaleString(), t)}
                {_detailRow("Completion tokens", log.completion_tokens?.toLocaleString(), t)}
                {_detailRow("Total tokens", log.total_tokens?.toLocaleString(), t)}
                {_detailRow("Duration", log.duration_ms != null ? `${(log.duration_ms / 1000).toFixed(2)}s` : null, t)}
                {_detailRow("Messages archived", log.messages_archived, t)}
                {_detailRow("Memory flush", log.memory_flush ? "yes" : "no", t)}
                {_detailRow("Forced", log.forced ? "yes" : "no", t)}
                {log.flush_tokens != null && _detailRow("Flush tokens", log.flush_tokens.toLocaleString(), t)}
                {log.flush_iterations != null && _detailRow("Flush iterations", String(log.flush_iterations), t)}
                {_detailRow("Section ID", log.section_id, t)}
                {_detailRow("Timestamp", log.created_at ? new Date(log.created_at).toLocaleString() : null, t)}
                {log.correlation_id && (
                  <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
                    <a
                      href={`/admin/logs/${log.correlation_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 10, color: t.accent, display: "flex", flexDirection: "row", alignItems: "center", gap: 3, textDecoration: "none" }}
                    >
                      <ExternalLink size={10} /> View trace
                    </a>
                  </div>
                )}
                {log.flush_result && (
                  <div style={{
                    marginTop: 4, padding: "6px 8px", background: t.codeBg,
                    borderRadius: 4, border: `1px solid ${t.surfaceBorder}`,
                  }}>
                    <div style={{ fontSize: 10, fontWeight: 600, color: t.purple, marginBottom: 2 }}>Flush result</div>
                    <div style={{
                      fontSize: 11, color: t.text, lineHeight: 1.5,
                      maxHeight: 200, overflowY: "auto",
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>{log.flush_result}</div>
                  </div>
                )}
                {log.tool_calls && log.tool_calls.length > 0 && (
                  <ToolCallsList toolCalls={log.tool_calls} isWide />
                )}
                {log.error && (
                  <div style={{ marginTop: 4, padding: "6px 8px", background: "rgba(239,68,68,0.08)", borderRadius: 4, border: "1px solid rgba(239,68,68,0.2)" }}>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "#dc2626", marginBottom: 2 }}>Error</div>
                    <div style={{ fontSize: 10, color: t.textMuted, whiteSpace: "pre-wrap", fontFamily: "monospace" }}>{log.error}</div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
      {(data?.total ?? 0) > logs.length && (
        <div style={{ fontSize: 10, color: t.textDim, padding: "4px 10px" }}>
          Showing {logs.length} of {data?.total ?? 0} events
        </div>
      )}
    </div>
  );
}
