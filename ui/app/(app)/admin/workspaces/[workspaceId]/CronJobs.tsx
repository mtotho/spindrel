import { Spinner } from "@/src/components/shared/Spinner";
import { useState } from "react";

import { ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { useWorkspaceCronJobs } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

interface CronJobsProps {
  workspaceId: string;
  status: string;
}

export function CronJobs({ workspaceId, status }: CronJobsProps) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const isRunning = status === "running";

  // Only fetch when expanded and running
  const { data, isLoading } = useWorkspaceCronJobs(
    expanded && isRunning ? workspaceId : undefined,
  );

  if (!isRunning) {
    return (
      <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0" }}>
        Container must be running to query cron jobs.
      </div>
    );
  }

  const jobs = data?.cron_jobs ?? [];
  const error = data?.error;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer",
          padding: 0, color: t.textMuted, fontSize: 12,
        }}
      >
        {expanded
          ? <ChevronDown size={14} color={t.textDim} />
          : <ChevronRight size={14} color={t.textDim} />}
        <span style={{ fontWeight: 500 }}>
          {expanded && !isLoading
            ? `${jobs.length} cron job${jobs.length !== 1 ? "s" : ""}`
            : "Show cron jobs"}
        </span>
      </button>

      {expanded && (
        <>
          {isLoading ? (
            <div style={{ padding: 12, alignItems: "center" }}>
              <Spinner />
            </div>
          ) : (
            <>
              {error && (
                <div style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                  padding: "6px 10px", borderRadius: 5,
                  background: "rgba(234,179,8,0.1)", fontSize: 11, color: "#ca8a04",
                }}>
                  <AlertTriangle size={12} />
                  {error}
                </div>
              )}

              {jobs.length === 0 ? (
                <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0" }}>
                  No cron jobs found in this container.
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Schedule", "Command", "User"].map((h) => (
                        <th
                          key={h}
                          style={{
                            textAlign: "left", padding: "4px 8px", fontSize: 10,
                            fontWeight: 600, color: t.textDim,
                            borderBottom: `1px solid ${t.surfaceBorder}`,
                            textTransform: "uppercase", letterSpacing: 0.5,
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((e, i) => (
                      <tr key={i}>
                        <td style={{
                          padding: "4px 8px", fontSize: 11, fontFamily: "monospace",
                          color: t.accent, whiteSpace: "nowrap",
                          borderBottom: i < jobs.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
                        }}>
                          {e.expression}
                        </td>
                        <td style={{
                          padding: "4px 8px", fontSize: 11, fontFamily: "monospace",
                          color: t.text, wordBreak: "break-all",
                          borderBottom: i < jobs.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
                        }}>
                          {e.command}
                        </td>
                        <td style={{
                          padding: "4px 8px", fontSize: 11, color: t.textMuted,
                          borderBottom: i < jobs.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
                        }}>
                          {e.user}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
