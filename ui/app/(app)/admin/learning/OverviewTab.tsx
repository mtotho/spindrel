import { useMemo } from "react";
import { useRouter } from "expo-router";
import { useWindowDimensions } from "react-native";
import {
  Moon, Activity, BookOpen, TrendingUp, AlertTriangle, FileText, PenLine,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview, type MemoryFileActivity } from "@/src/api/hooks/useLearningOverview";
import { DreamingBotTable } from "@/src/components/learning/DreamingBotTable";
import { StatCard, fmtRelative } from "@/app/(app)/admin/bots/[botId]/LearningSection";

function fmtRelativeFuture(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) {
    const mins = Math.floor(-diffMs / 60_000);
    if (mins < 60) return `in ${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `in ${hrs}h`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return fmtRelative(iso);
}

function shortPath(path: string): string {
  return path.replace(/^memory\//, "");
}

const OP_LABELS: Record<string, string> = { write: "wrote", append: "appended", edit: "edited" };

export function OverviewTab() {
  const t = useThemeTokens();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { data, isLoading } = useLearningOverview();

  const botsWithFailures = useMemo(() => {
    if (!data) return [];
    return data.bots.filter((b) => b.last_task_status === "failed");
  }, [data]);

  const failedRuns = useMemo(() => (data?.recent_runs ?? []).filter((r) => r.status === "failed"), [data]);

  // Group memory activity by day
  const activityByDay = useMemo(() => {
    if (!data?.memory_activity?.length) return [];
    const groups: { date: string; items: MemoryFileActivity[] }[] = [];
    let currentDate = "";
    for (const item of data.memory_activity) {
      const d = new Date(item.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      if (d !== currentDate) {
        currentDate = d;
        groups.push({ date: d, items: [] });
      }
      groups[groups.length - 1].items.push(item);
    }
    return groups;
  }, [data]);

  if (isLoading) {
    return <div style={{ color: t.textDim, fontSize: 12, padding: 20 }}>Loading...</div>;
  }

  if (!data) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Stats row */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <StatCard
          label="Bots Dreaming"
          value={`${data.dreaming_enabled_count} / ${data.total_bots}`}
          icon={<Moon size={14} color="#8b5cf6" />}
          color="#8b5cf6"
        />
        <StatCard
          label="Runs (7d)"
          value={data.total_hygiene_runs_7d}
          icon={<Activity size={14} color="#3b82f6" />}
        />
        <StatCard
          label="Bot Skills"
          value={data.total_bot_skills}
          icon={<BookOpen size={14} color="#059669" />}
        />
        <StatCard
          label="Surfacings"
          value={data.total_surfacings}
          icon={<TrendingUp size={14} color="#f59e0b" />}
        />
      </div>

      {/* Failures callout */}
      {botsWithFailures.length > 0 && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 8,
          padding: "12px 16px", borderRadius: 8,
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <AlertTriangle size={14} color={t.danger} />
            <span style={{ fontSize: 13, fontWeight: 600, color: t.danger }}>
              {botsWithFailures.length} bot{botsWithFailures.length !== 1 ? "s" : ""} failed last dreaming run
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {botsWithFailures.map((bot) => {
              const failedRun = failedRuns.find((r) => r.bot_id === bot.bot_id);
              return (
                <button
                  key={bot.bot_id}
                  onClick={() => router.push(`/admin/bots/${bot.bot_id}#memory` as any)}
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "6px 10px", borderRadius: 6,
                    background: "rgba(239,68,68,0.06)", border: `1px solid ${t.dangerBorder}`,
                    cursor: "pointer", textAlign: "left", width: "100%",
                  }}
                >
                  <span style={{ fontSize: 12, fontWeight: 500, color: t.text, flexShrink: 0 }}>
                    {bot.bot_name}
                  </span>
                  <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>
                    {fmtRelativeFuture(bot.last_run_at)}
                  </span>
                  {failedRun?.error && (
                    <span style={{
                      fontSize: 10, color: t.danger, flex: 1,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {failedRun.error}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Two-column: Bot table + Memory Activity */}
      <div style={{ display: "flex", gap: 20, flexDirection: isMobile ? "column" : "row" }}>
        {/* Left: Dreaming status table (read-only — manage in Dreaming tab) */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <Moon size={14} color="#8b5cf6" />
            Dreaming by Bot
            <span style={{ fontSize: 10, color: t.textDim, fontWeight: 400, marginLeft: 4 }}>
              (manage in Dreaming tab)
            </span>
          </div>

          <DreamingBotTable bots={data.bots} mode="view" />
        </div>

        {/* Right: Memory Activity Feed */}
        <div style={{ flex: 1, minWidth: 0, maxWidth: isMobile ? undefined : 420 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <PenLine size={14} color={t.textMuted} />
            Memory Activity
            <span style={{ fontSize: 10, color: t.textDim, fontWeight: 400 }}>(7d)</span>
          </div>
          {activityByDay.length === 0 ? (
            <div style={{
              padding: 24, textAlign: "center", borderRadius: 8,
              background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
            }}>
              <FileText size={20} color={t.textDim} style={{ marginBottom: 8 }} />
              <div style={{ fontSize: 12, color: t.textDim }}>No memory file activity in the last 7 days.</div>
            </div>
          ) : (
            <div style={{
              borderRadius: 8, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden",
              maxHeight: 500, overflowY: "auto",
            }}>
              {activityByDay.map((group) => (
                <div key={group.date}>
                  <div style={{
                    padding: "4px 12px", fontSize: 9, fontWeight: 600, color: t.textDim,
                    textTransform: "uppercase", letterSpacing: 0.5,
                    background: t.surfaceOverlay, borderBottom: `1px solid ${t.surfaceBorder}`,
                    position: "sticky", top: 0,
                  }}>
                    {group.date}
                  </div>
                  {group.items.map((item, i) => (
                    <div
                      key={`${item.created_at}-${i}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "6px 12px",
                        borderBottom: `1px solid ${t.surfaceBorder}`,
                      }}
                    >
                      <FileText size={12} color={item.is_hygiene ? "#8b5cf6" : t.textDim} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <span style={{
                            fontSize: 11, fontWeight: 500, color: t.text,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>
                            {shortPath(item.file_path)}
                          </span>
                          {item.is_hygiene && (
                            <span style={{
                              fontSize: 8, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
                              background: "rgba(139,92,246,0.12)", color: "#8b5cf6",
                            }}>
                              dreaming
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 9, color: t.textDim }}>
                          {item.bot_name} {OP_LABELS[item.operation] ?? item.operation} &middot; {new Date(item.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
