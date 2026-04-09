import { useState } from "react";
import { useRouter } from "expo-router";
import { ExternalLink, ChevronDown, ChevronRight, Clock, Zap } from "lucide-react";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { useThemeTokens } from "@/src/theme/tokens";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import type { MemoryHygieneRun } from "@/src/api/hooks/useMemoryHygiene";

type RunWithBotName = MemoryHygieneRun & { bot_name?: string };

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function HygieneHistoryList({ runs, showBotName }: { runs: RunWithBotName[]; showBotName?: boolean }) {
  const t = useThemeTokens();
  const router = useRouter();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>
        Recent Runs
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {runs.map((run) => {
          const isExpanded = expandedId === run.id;
          const hasContent = run.result || run.error || run.correlation_id;
          return (
            <div key={run.id}>
              <div
                onClick={() => hasContent && setExpandedId(isExpanded ? null : run.id)}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", background: isExpanded ? t.surfaceOverlay : t.surfaceRaised,
                  borderRadius: isExpanded ? "6px 6px 0 0" : 6,
                  border: `1px solid ${isExpanded ? t.accent : t.surfaceOverlay}`,
                  cursor: hasContent ? "pointer" : "default",
                  transition: "background 0.1s, border-color 0.1s",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {hasContent && (
                    isExpanded
                      ? <ChevronDown size={12} color={t.textDim} />
                      : <ChevronRight size={12} color={t.textDim} />
                  )}
                  {showBotName && run.bot_name && (
                    <span style={{ fontSize: 11, fontWeight: 600, color: t.text }}>
                      {run.bot_name}
                    </span>
                  )}
                  <span style={{ fontSize: 12, color: t.textMuted }}>
                    {new Date(run.created_at).toLocaleString()}
                  </span>
                  {run.completed_at && (
                    <span style={{ fontSize: 10, color: t.textDim }}>
                      ({Math.round((new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()) / 1000)}s)
                    </span>
                  )}
                </div>
                <StatusBadge
                  label={run.status}
                  variant={run.status === "complete" ? "success" : run.status === "failed" ? "danger" : "neutral"}
                />
              </div>
              {isExpanded && (
                <div style={{
                  padding: "10px 12px", background: t.codeBg,
                  borderRadius: "0 0 6px 6px",
                  border: `1px solid ${t.accent}`, borderTop: "none",
                }}>
                  {run.error && (
                    <div style={{
                      fontSize: 12, color: t.danger, marginBottom: 8,
                      padding: "6px 8px", background: t.dangerSubtle, borderRadius: 4, border: `1px solid ${t.dangerBorder}`,
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {run.error}
                    </div>
                  )}
                  {run.result && (
                    <div style={{
                      fontSize: 12, color: t.text, lineHeight: 1.5,
                      maxHeight: 200, overflowY: "auto",
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {run.result}
                    </div>
                  )}
                  {(run.iterations > 0 || run.total_tokens > 0 || run.duration_ms != null) && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 12,
                      marginTop: 8, fontSize: 10, color: t.textDim,
                    }}>
                      {run.duration_ms != null && (
                        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                          <Clock size={10} /> {fmtDuration(run.duration_ms)}
                        </span>
                      )}
                      {run.total_tokens > 0 && (
                        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                          <Zap size={10} /> {fmtTokens(run.total_tokens)} tokens
                        </span>
                      )}
                      {run.iterations > 0 && (
                        <span>{run.iterations} iter</span>
                      )}
                    </div>
                  )}
                  {run.tool_calls.length > 0 && (
                    <ToolCallsList toolCalls={run.tool_calls as any} />
                  )}
                  {run.correlation_id && (
                    <div
                      onClick={() => router.push(`/admin/logs/${run.correlation_id}`)}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        marginTop: 8, fontSize: 11, color: t.accent, cursor: "pointer",
                      }}
                    >
                      <ExternalLink size={11} color={t.accent} />
                      View trace
                    </div>
                  )}
                  {!run.result && !run.error && (
                    <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>No output recorded</div>
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
