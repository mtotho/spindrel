import { View, ActivityIndicator } from "react-native";
import { AlertTriangle, RefreshCw, Server, Container } from "lucide-react";
import { useCronJobs } from "@/src/api/hooks/useTasks";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import type { CronEntry } from "@/src/types/api";

export function CronJobsView() {
  const t = useThemeTokens();
  const qc = useQueryClient();
  const { data, isLoading, isFetching } = useCronJobs();

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: 40 }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const jobs = data?.cron_jobs ?? [];
  const errors = data?.errors ?? [];

  const containerJobs = jobs.filter((j) => j.source_type === "container");
  const hostJobs = jobs.filter((j) => j.source_type === "host");

  // Group container jobs by source_name
  const containerGroups: Record<string, CronEntry[]> = {};
  for (const j of containerJobs) {
    const key = j.source_name;
    if (!containerGroups[key]) containerGroups[key] = [];
    containerGroups[key].push(j);
  }

  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 13, color: t.textMuted }}>
          {jobs.length} cron job{jobs.length !== 1 ? "s" : ""} discovered
        </span>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ["admin-cron-jobs"] })}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 10px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
            background: "transparent", color: t.textMuted, cursor: "pointer",
            opacity: isFetching ? 0.5 : 1,
          }}
        >
          <RefreshCw size={11} style={isFetching ? { animation: "spin 1s linear infinite" } : undefined} />
          Refresh
        </button>
      </div>

      {/* Errors banner */}
      {errors.length > 0 && (
        <div style={{
          padding: "8px 12px", borderRadius: 6,
          background: "rgba(234,179,8,0.1)", border: "1px solid rgba(234,179,8,0.3)",
          display: "flex", alignItems: "flex-start", gap: 8,
        }}>
          <AlertTriangle size={14} color="#ca8a04" style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 11, color: "#ca8a04" }}>
            {errors.map((e, i) => (
              <div key={i}>{e}</div>
            ))}
          </div>
        </div>
      )}

      {jobs.length === 0 && !isLoading && (
        <div style={{ textAlign: "center", padding: 40, color: t.textDim, fontSize: 13 }}>
          No cron jobs found in any running containers or on the host.
        </div>
      )}

      {/* Container groups */}
      {Object.entries(containerGroups).map(([name, entries]) => (
        <SourceGroup
          key={name}
          icon={<Container size={13} color={t.accent} />}
          title={name}
          subtitle={entries[0].workspace_name ?? undefined}
          entries={entries}
        />
      ))}

      {/* Host group */}
      {hostJobs.length > 0 && (
        <SourceGroup
          icon={<Server size={13} color={t.textMuted} />}
          title={hostJobs[0].source_name}
          subtitle="Host OS"
          entries={hostJobs}
        />
      )}
    </div>
  );
}

function SourceGroup({
  icon,
  title,
  subtitle,
  entries,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  entries: CronEntry[];
}) {
  const t = useThemeTokens();

  return (
    <div style={{
      border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
      overflow: "hidden",
    }}>
      {/* Group header */}
      <div style={{
        padding: "8px 12px", background: t.surfaceRaised,
        display: "flex", alignItems: "center", gap: 8,
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        {icon}
        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{title}</span>
        {subtitle && (
          <span style={{ fontSize: 11, color: t.textDim }}>({subtitle})</span>
        )}
        <span style={{ fontSize: 10, color: t.textDim, marginLeft: "auto" }}>
          {entries.length} job{entries.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {["Schedule", "Command", "User"].map((h) => (
              <th
                key={h}
                style={{
                  textAlign: "left", padding: "6px 12px", fontSize: 10,
                  fontWeight: 600, color: t.textDim, borderBottom: `1px solid ${t.surfaceBorder}`,
                  textTransform: "uppercase", letterSpacing: 0.5,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i}>
              <td style={{
                padding: "6px 12px", fontSize: 12, fontFamily: "monospace",
                color: t.accent, whiteSpace: "nowrap",
                borderBottom: i < entries.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
              }}>
                {e.expression}
              </td>
              <td style={{
                padding: "6px 12px", fontSize: 12, fontFamily: "monospace",
                color: t.text, wordBreak: "break-all",
                borderBottom: i < entries.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
              }}>
                {e.command}
              </td>
              <td style={{
                padding: "6px 12px", fontSize: 11, color: t.textMuted,
                borderBottom: i < entries.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
              }}>
                {e.user}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
