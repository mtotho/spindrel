import { Text, Pressable, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { ExternalLink } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import { useLogs, type LogRow } from "@/src/api/hooks/useLogs";

// ---------------------------------------------------------------------------
// Log type colors (only used by this tab)
// ---------------------------------------------------------------------------
// Moved inside component — needs theme tokens for some values
// (non-token colors like teal and indigo are domain-specific and kept as-is)

// ---------------------------------------------------------------------------
// Logs Tab
// ---------------------------------------------------------------------------
export function LogsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const router = useRouter();
  const { data, isLoading } = useLogs({ channel_id: channelId, page_size: 20 });

  const LOG_TYPE_COLORS: Record<string, { bg: string; fg: string }> = {
    tool_call:            { bg: "#312e81", fg: "#4f46e5" },
    memory_injection:     { bg: t.purpleSubtle, fg: t.purple },
    skill_context:        { bg: "#134e4a", fg: "#0d9488" },
    knowledge_context:    { bg: t.accentMuted, fg: t.accent },
    tool_retrieval:       { bg: t.warningSubtle, fg: t.warningMuted },
    context_compressed:   { bg: "#365314", fg: "#65a30d" },
    context_breakdown:    { bg: "#164e63", fg: "#0891b2" },
    token_usage:          { bg: t.surfaceBorder, fg: t.textMuted },
    error:                { bg: t.dangerSubtle, fg: t.danger },
    harness:              { bg: t.warningSubtle, fg: t.warningMuted },
    response:             { bg: t.successSubtle, fg: t.success },
    model_fallback:       { bg: t.warningSubtle, fg: t.warningMuted },
  };

  if (isLoading) return <ActivityIndicator color={t.accent} />;
  if (!data?.rows?.length) return <EmptyState message="No log entries yet." />;

  return (
    <>
      <Section title={`Recent Logs (${data.rows.length} of ${data.total})`}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.rows.map((row: LogRow) => {
            const evType = row.kind === "tool_call" ? "tool_call" : row.event_type || "trace_event";
            const name = row.kind === "tool_call" ? row.tool_name : row.event_name || row.event_type;
            const c = LOG_TYPE_COLORS[evType] ?? { bg: t.surfaceBorder, fg: t.textMuted };
            return (
              <div
                key={row.id}
                onClick={() => row.correlation_id && router.push(`/admin/logs/${row.correlation_id}` as any)}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", background: t.surfaceRaised, borderRadius: 6, border: `1px solid ${t.surfaceOverlay}`,
                  cursor: row.correlation_id ? "pointer" : "default",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <StatusBadge label={evType} customColors={{ bg: c.bg, fg: c.fg }} />
                  <span style={{ fontSize: 12, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {name || "\u2014"}
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                  <span style={{ fontSize: 10, color: t.textDim }}>
                    {row.created_at ? new Date(row.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "\u2014"}
                  </span>
                  {row.correlation_id && (
                    <span style={{ fontSize: 10, color: t.surfaceBorder, fontFamily: "monospace" }}>
                      {row.correlation_id.substring(0, 8)}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      <Pressable
        onPress={() => router.push(`/admin/logs?channel_id=${channelId}` as any)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          alignSelf: "flex-start",
        }}
      >
        <Text style={{ fontSize: 13, color: t.accent }}>View all in Logs</Text>
        <ExternalLink size={12} color={t.accent} />
      </Pressable>
    </>
  );
}
