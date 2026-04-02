import { useState } from "react";
import { useRouter } from "expo-router";
import { ExternalLink, ChevronDown, ChevronRight, Clock, Zap, AlertTriangle } from "lucide-react";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { useThemeTokens } from "@/src/theme/tokens";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
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
  const t = useThemeTokens();
  const router = useRouter();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>
        Recent Runs
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {history.map((hb) => {
          const isExpanded = expandedId === hb.id;
          const hasContent = hb.result || hb.error || hb.correlation_id;
          return (
            <div key={hb.id}>
              <div
                onClick={() => hasContent && setExpandedId(isExpanded ? null : hb.id)}
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
                  <span style={{ fontSize: 12, color: t.textMuted }}>
                    {new Date(hb.run_at).toLocaleString()}
                  </span>
                  {hb.completed_at && (
                    <span style={{ fontSize: 10, color: t.textDim }}>
                      ({Math.round((new Date(hb.completed_at).getTime() - new Date(hb.run_at).getTime()) / 1000)}s)
                    </span>
                  )}
                </div>
                <StatusBadge
                  label={hb.status}
                  variant={hb.status === "complete" ? "success" : hb.status === "failed" ? "danger" : "neutral"}
                />
                {hb.repetition_detected && (
                  <span style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                    background: t.warningSubtle, color: t.warningMuted,
                    display: "inline-flex", alignItems: "center", gap: 3,
                  }}>
                    <AlertTriangle size={10} /> repetitive
                  </span>
                )}
              </div>
              {isExpanded && (
                <div style={{
                  padding: "10px 12px", background: t.codeBg,
                  borderRadius: "0 0 6px 6px",
                  border: `1px solid ${t.accent}`, borderTop: "none",
                }}>
                  {hb.error && (
                    <div style={{
                      fontSize: 12, color: t.danger, marginBottom: 8,
                      padding: "6px 8px", background: t.dangerSubtle, borderRadius: 4, border: `1px solid ${t.dangerBorder}`,
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {hb.error}
                    </div>
                  )}
                  {hb.result && (
                    <div style={{
                      fontSize: 12, color: t.text, lineHeight: 1.5,
                      maxHeight: 200, overflowY: "auto",
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {hb.result}
                    </div>
                  )}
                  {(hb.iterations > 0 || hb.total_tokens > 0 || hb.duration_ms != null) && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 12,
                      marginTop: 8, fontSize: 10, color: t.textDim,
                    }}>
                      {hb.duration_ms != null && (
                        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                          <Clock size={10} /> {fmtDuration(hb.duration_ms)}
                        </span>
                      )}
                      {hb.total_tokens > 0 && (
                        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
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
                    <div
                      onClick={() => router.push(`/admin/logs/${hb.correlation_id}`)}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        marginTop: 8, fontSize: 11, color: t.accent, cursor: "pointer",
                      }}
                    >
                      <ExternalLink size={11} color={t.accent} />
                      View trace
                    </div>
                  )}
                  {!hb.result && !hb.error && (
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
