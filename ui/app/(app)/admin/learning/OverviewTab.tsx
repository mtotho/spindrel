import { useMemo } from "react";
import { useRouter } from "expo-router";
import { useWindowDimensions } from "react-native";
import {
  Moon, Activity, BookOpen, TrendingUp, Clock, FileText, PenLine,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview, type MemoryFileActivity } from "@/src/api/hooks/useLearningOverview";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
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
  // "memory/MEMORY.md" → "MEMORY.md", "memory/logs/2026-04-08.md" → "logs/2026-04-08.md"
  return path.replace(/^memory\//, "");
}

const OP_LABELS: Record<string, string> = { write: "wrote", append: "appended", edit: "edited" };

export function OverviewTab() {
  const t = useThemeTokens();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { data, isLoading } = useLearningOverview();

  const recentPreview = useMemo(() => (data?.recent_runs ?? []).slice(0, 5), [data]);
  const successRate = useMemo(() => {
    if (!data?.recent_runs.length) return null;
    const complete = data.recent_runs.filter((r) => r.status === "complete").length;
    return Math.round((complete / data.recent_runs.length) * 100);
  }, [data]);

  // Group memory activity by day for the timeline
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

      {/* Two-column layout: bot table + memory activity (desktop) */}
      <div style={{ display: "flex", gap: 20, flexDirection: isMobile ? "column" : "row" }}>
        {/* Left: Dreaming status table */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <Moon size={14} color="#8b5cf6" />
            Dreaming by Bot
          </div>

          {data.bots.length === 0 ? (
            <div style={{
              padding: 24, textAlign: "center", borderRadius: 8,
              background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
            }}>
              <Moon size={20} color={t.textDim} style={{ marginBottom: 8 }} />
              <div style={{ fontSize: 12, color: t.textDim }}>
                No bots with workspace-files memory. Enable memory on a bot to start dreaming.
              </div>
            </div>
          ) : (
            <div style={{ borderRadius: 8, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden" }}>
              {/* Header — hidden on mobile */}
              {!isMobile && (
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 70px 110px 80px 110px",
                  gap: 8, padding: "8px 14px",
                  background: t.surfaceOverlay,
                  borderBottom: `1px solid ${t.surfaceBorder}`,
                }}>
                  {["Bot", "Status", "Last Run", "Result", "Next Run"].map((h) => (
                    <span key={h} style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                      {h}
                    </span>
                  ))}
                </div>
              )}
              {data.bots.map((bot) => (
                <button
                  key={bot.bot_id}
                  onClick={() => router.push(`/admin/bots/${bot.bot_id}#memory` as any)}
                  style={{
                    display: isMobile ? "flex" : "grid",
                    flexDirection: isMobile ? "column" : undefined,
                    gridTemplateColumns: isMobile ? undefined : "1fr 70px 110px 80px 110px",
                    gap: isMobile ? 4 : 8,
                    padding: isMobile ? "10px 14px" : "10px 14px",
                    background: "transparent",
                    border: "none",
                    borderBottom: `1px solid ${t.surfaceBorder}`,
                    cursor: "pointer",
                    textAlign: "left",
                    width: "100%",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = t.inputBg; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                >
                  {isMobile ? (
                    <>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontSize: 13, fontWeight: 500, color: t.text }}>{bot.bot_name}</span>
                        {bot.enabled ? (
                          <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4, background: "rgba(16,185,129,0.12)", color: "#059669" }}>on</span>
                        ) : (
                          <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4, background: t.surfaceOverlay, color: t.textDim }}>off</span>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 12, fontSize: 10, color: t.textDim }}>
                        <span>Last: {fmtRelativeFuture(bot.last_run_at)}</span>
                        {bot.last_task_status && (
                          <StatusBadge
                            label={bot.last_task_status}
                            variant={bot.last_task_status === "complete" ? "success" : bot.last_task_status === "failed" ? "danger" : "neutral"}
                          />
                        )}
                        <span>Next: {fmtRelativeFuture(bot.next_run_at)}</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <span style={{ fontSize: 12, fontWeight: 500, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {bot.bot_name}
                      </span>
                      <span>
                        {bot.enabled ? (
                          <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4, background: "rgba(16,185,129,0.12)", color: "#059669" }}>on</span>
                        ) : (
                          <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 4, background: t.surfaceOverlay, color: t.textDim }}>off</span>
                        )}
                      </span>
                      <span style={{ fontSize: 11, color: t.textMuted }}>{fmtRelativeFuture(bot.last_run_at)}</span>
                      <span>
                        {bot.last_task_status && (
                          <StatusBadge
                            label={bot.last_task_status}
                            variant={bot.last_task_status === "complete" ? "success" : bot.last_task_status === "failed" ? "danger" : "neutral"}
                          />
                        )}
                      </span>
                      <span style={{ fontSize: 11, color: t.textDim }}>{fmtRelativeFuture(bot.next_run_at)}</span>
                    </>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right: Memory Activity Feed */}
        {activityByDay.length > 0 && (
          <div style={{ flex: 1, minWidth: 0, maxWidth: isMobile ? undefined : 420 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
              <PenLine size={14} color={t.textMuted} />
              Memory Activity
              <span style={{ fontSize: 10, color: t.textDim, fontWeight: 400 }}>(7d)</span>
            </div>
            <div style={{
              borderRadius: 8, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden",
              maxHeight: 400, overflowY: "auto",
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
                              hygiene
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
          </div>
        )}
      </div>

      {/* Recent runs */}
      {recentPreview.length > 0 && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
            <Clock size={14} color={t.textMuted} />
            <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>
              Recent Dreaming Runs
            </span>
            {successRate !== null && (
              <span style={{
                fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
                background: successRate >= 80 ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                color: successRate >= 80 ? "#059669" : "#ef4444",
              }}>
                {successRate}% pass
              </span>
            )}
          </div>
          <HygieneHistoryList runs={recentPreview} showBotName />
        </div>
      )}
    </div>
  );
}
