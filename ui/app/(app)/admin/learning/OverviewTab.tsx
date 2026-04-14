import { useMemo } from "react";
import { useRouter } from "expo-router";
import { useWindowDimensions } from "react-native";
import {
  Moon, Activity, BookOpen, TrendingUp, AlertTriangle, FileText, PenLine, Zap,
  ArrowRight,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useLearningOverview, useLearningActivity,
  type MemoryFileActivity, type DailyActivityPoint,
} from "@/src/api/hooks/useLearningOverview";
import { DreamingBotTable } from "@/src/components/learning/DreamingBotTable";
import { fmtRelative } from "@/app/(app)/admin/bots/[botId]/LearningSection";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Metric Card — richer than StatCard with optional subtitle + accent bar
// ---------------------------------------------------------------------------

function MetricCard({ label, value, subtitle, icon, accent, onClick }: {
  label: string;
  value: number | string;
  subtitle?: string;
  icon: React.ReactNode;
  accent: string;
  onClick?: () => void;
}) {
  const t = useThemeTokens();
  return (
    <div
      onClick={onClick}
      style={{
        flex: 1,
        minWidth: 130,
        padding: "14px 16px 12px",
        borderRadius: 10,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        position: "relative",
        overflow: "hidden",
        cursor: onClick ? "pointer" : undefined,
        transition: "border-color 0.15s",
      }}
      onMouseEnter={(e) => { if (onClick) e.currentTarget.style.borderColor = accent; }}
      onMouseLeave={(e) => { if (onClick) e.currentTarget.style.borderColor = t.surfaceBorder; }}
    >
      {/* Accent top bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 2,
        background: `linear-gradient(90deg, ${accent}, transparent)`,
        opacity: 0.7,
      }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        {icon}
        <span style={{
          fontSize: 9, color: t.textDim, textTransform: "uppercase",
          fontWeight: 700, letterSpacing: 0.8,
        }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: t.text, lineHeight: 1 }}>
        {value}
      </div>
      {subtitle && (
        <div style={{ fontSize: 9, color: t.textDim, marginTop: 4 }}>
          {subtitle}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Activity heatmap — 7 days × intensity
// ---------------------------------------------------------------------------

function ActivityHeatmap({ activity }: { activity: MemoryFileActivity[] }) {
  const t = useThemeTokens();

  const dayBuckets = useMemo(() => {
    const buckets: number[] = new Array(7).fill(0);
    const now = Date.now();
    for (const item of activity) {
      const daysAgo = Math.floor((now - new Date(item.created_at).getTime()) / 86_400_000);
      if (daysAgo >= 0 && daysAgo < 7) buckets[6 - daysAgo]++;
    }
    return buckets;
  }, [activity]);

  const max = Math.max(...dayBuckets, 1);
  const dayLabels = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (6 - i));
      return d.toLocaleDateString(undefined, { weekday: "short" }).slice(0, 2);
    });
  }, []);

  return (
    <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 32 }}>
      {dayBuckets.map((count, i) => {
        const intensity = count / max;
        return (
          <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, flex: 1 }}>
            <div
              title={`${dayLabels[i]}: ${count} write${count !== 1 ? "s" : ""}`}
              style={{
                width: "100%",
                maxWidth: 20,
                height: Math.max(4, intensity * 24),
                borderRadius: 2,
                background: count > 0
                  ? `rgba(139, 92, 246, ${0.25 + intensity * 0.65})`
                  : `${t.surfaceBorder}`,
                transition: "height 0.3s ease",
              }}
            />
            <span style={{ fontSize: 7, color: t.textDim, lineHeight: 1 }}>{dayLabels[i]}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stacked area chart — 14-day skill activity
// ---------------------------------------------------------------------------

function SkillActivityChart({ data }: { data: DailyActivityPoint[] }) {
  const t = useThemeTokens();

  if (!data.length) return null;

  const W = 480;
  const H = 120;
  const PX = 32; // left padding for y-axis labels
  const PB = 18; // bottom padding for x-axis labels
  const chartW = W - PX;
  const chartH = H - PB;

  const maxVal = Math.max(...data.map((d) => d.surfacings + d.auto_injects), 1);
  const yTicks = [0, Math.round(maxVal / 2), maxVal];

  const xStep = data.length > 1 ? chartW / (data.length - 1) : chartW;

  function toY(v: number) {
    return chartH - (v / maxVal) * chartH;
  }

  // Build stacked paths: surfacings on bottom, auto_injects on top
  const surfPoints = data.map((d, i) => ({ x: PX + i * xStep, y: toY(d.surfacings) }));
  const totalPoints = data.map((d, i) => ({ x: PX + i * xStep, y: toY(d.surfacings + d.auto_injects) }));

  function pathLine(pts: { x: number; y: number }[]) {
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  }
  function pathArea(pts: { x: number; y: number }[], baseline: { x: number; y: number }[]) {
    const top = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
    const bot = [...baseline].reverse().map((p) => `L${p.x},${p.y}`).join(" ");
    return `${top} ${bot} Z`;
  }

  // Surfacings area: from baseline (chartH) to surfPoints
  const surfBaseline = data.map((_, i) => ({ x: PX + i * xStep, y: chartH }));
  const surfArea = pathArea(surfPoints, surfBaseline);
  // Auto-inject area: from surfPoints to totalPoints
  const aiArea = pathArea(totalPoints, surfPoints);

  // x-axis labels: show every 2-3 days
  const labelInterval = data.length > 10 ? 3 : 2;

  return (
    <div style={{
      padding: "14px 16px 10px", borderRadius: 10,
      background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 10,
      }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
          Skill Activity
        </span>
        <div style={{ display: "flex", gap: 12 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 9, color: t.textDim }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: "#f59e0b", opacity: 0.7 }} />
            Surfacings
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 9, color: t.textDim }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: "#a855f7", opacity: 0.7 }} />
            Auto-Injects
          </span>
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: "block" }}>
        {/* Grid lines */}
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={PX} y1={toY(v)} x2={W} y2={toY(v)}
              stroke={t.surfaceBorder} strokeWidth={0.5}
              strokeDasharray={v > 0 ? "2,3" : undefined}
            />
            <text x={PX - 4} y={toY(v) + 3} fill={t.textDim} fontSize={8} textAnchor="end">
              {v}
            </text>
          </g>
        ))}

        {/* Surfacings area */}
        <path d={surfArea} fill="#f59e0b" opacity={0.2} />
        <path d={pathLine(surfPoints)} fill="none" stroke="#f59e0b" strokeWidth={1.5} opacity={0.8} />

        {/* Auto-inject area (stacked on top) */}
        <path d={aiArea} fill="#a855f7" opacity={0.2} />
        <path d={pathLine(totalPoints)} fill="none" stroke="#a855f7" strokeWidth={1.5} opacity={0.8} />

        {/* x-axis labels */}
        {data.map((d, i) => {
          if (i % labelInterval !== 0 && i !== data.length - 1) return null;
          const label = new Date(d.date + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
          return (
            <text
              key={d.date}
              x={PX + i * xStep}
              y={H - 2}
              fill={t.textDim}
              fontSize={7}
              textAnchor="middle"
            >
              {label}
            </text>
          );
        })}

        {/* Dots on non-zero days */}
        {data.map((d, i) => {
          const total = d.surfacings + d.auto_injects;
          if (total === 0) return null;
          return (
            <circle
              key={d.date}
              cx={PX + i * xStep}
              cy={toY(total)}
              r={2}
              fill="#a855f7"
              opacity={0.9}
            />
          );
        })}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill activity sparkline — surfacings + injects
// ---------------------------------------------------------------------------

function SkillActivityRing({ surfacings, autoInjects, total }: {
  surfacings: number; autoInjects: number; total: number;
}) {
  if (total === 0) return null;
  const surfPct = surfacings / total;
  const injectPct = autoInjects / total;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <svg width={28} height={28} viewBox="0 0 28 28">
        <circle cx={14} cy={14} r={11} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={3} />
        <circle
          cx={14} cy={14} r={11}
          fill="none"
          stroke="#f59e0b"
          strokeWidth={3}
          strokeDasharray={`${surfPct * 69.1} ${69.1}`}
          strokeDashoffset={0}
          transform="rotate(-90 14 14)"
          strokeLinecap="round"
        />
        <circle
          cx={14} cy={14} r={11}
          fill="none"
          stroke="#a855f7"
          strokeWidth={3}
          strokeDasharray={`${injectPct * 69.1} ${69.1}`}
          strokeDashoffset={-(surfPct * 69.1)}
          transform="rotate(-90 14 14)"
          strokeLinecap="round"
        />
      </svg>
      <div style={{ fontSize: 9, lineHeight: "14px" }}>
        <div style={{ color: "#f59e0b" }}>{surfacings} surf</div>
        <div style={{ color: "#a855f7" }}>{autoInjects} inject</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OverviewTab
// ---------------------------------------------------------------------------

export function OverviewTab() {
  const t = useThemeTokens();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { data, isLoading } = useLearningOverview();
  const { data: activityData } = useLearningActivity(14);

  const botsWithFailures = useMemo(() => {
    if (!data) return [];
    return data.bots.filter((b) => b.last_task_status === "failed");
  }, [data]);

  const failedRuns = useMemo(
    () => (data?.recent_runs ?? []).filter((r) => r.status === "failed"),
    [data],
  );

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

  // Dreaming stats
  const nextRunBot = useMemo(() => {
    if (!data?.bots.length) return null;
    const upcoming = data.bots
      .filter((b) => b.next_run_at && b.enabled)
      .sort((a, b) => new Date(a.next_run_at!).getTime() - new Date(b.next_run_at!).getTime());
    return upcoming[0] ?? null;
  }, [data]);

  if (isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
        <div style={{ color: t.textDim, fontSize: 12 }}>Loading learning data...</div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* --- Metrics row --- */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(5, 1fr)", gap: 10 }}>
        <MetricCard
          label="Bots Dreaming"
          value={`${data.dreaming_enabled_count}/${data.total_bots}`}
          subtitle={nextRunBot ? `Next: ${nextRunBot.bot_name} ${fmtRelativeFuture(nextRunBot.next_run_at)}` : undefined}
          icon={<Moon size={13} color="#8b5cf6" />}
          accent="#8b5cf6"
        />
        <MetricCard
          label="Runs (7d)"
          value={data.total_hygiene_runs_7d}
          subtitle={botsWithFailures.length > 0 ? `${botsWithFailures.length} failed` : "all healthy"}
          icon={<Activity size={13} color="#3b82f6" />}
          accent="#3b82f6"
        />
        <MetricCard
          label="Bot Skills"
          value={data.total_bot_skills}
          icon={<BookOpen size={13} color="#059669" />}
          accent="#059669"
          onClick={() => router.push("/admin/learning#Skills" as any)}
        />
        <MetricCard
          label="Surfacings"
          value={data.total_surfacings}
          subtitle={`${data.surfacings_7d ?? 0} in last 7d`}
          icon={<TrendingUp size={13} color="#f59e0b" />}
          accent="#f59e0b"
        />
        <MetricCard
          label="Auto-Injects"
          value={data.total_auto_injects ?? 0}
          subtitle={`${data.auto_injects_7d ?? 0} in last 7d`}
          icon={<Zap size={13} color="#a855f7" />}
          accent="#a855f7"
        />
      </div>

      {/* --- Skill usage breakdown --- */}
      {(data.total_surfacings > 0 || (data.total_auto_injects ?? 0) > 0) && (
        <div style={{
          display: "flex", alignItems: "center", gap: 16,
          padding: "12px 16px", borderRadius: 10,
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <SkillActivityRing
            surfacings={data.total_surfacings}
            autoInjects={data.total_auto_injects ?? 0}
            total={data.total_surfacings + (data.total_auto_injects ?? 0)}
          />
          <div style={{ flex: 1, fontSize: 11, color: t.textMuted, lineHeight: "18px" }}>
            <strong style={{ color: t.text }}>{data.total_surfacings + (data.total_auto_injects ?? 0)}</strong> total skill loads (all time), <strong style={{ color: t.text }}>{(data.surfacings_7d ?? 0) + (data.auto_injects_7d ?? 0)}</strong> in the last 7 days.{" "}
            <span style={{ color: "#f59e0b" }}>Surfacings</span> = bot-initiated <code style={{ fontSize: 10 }}>get_skill()</code> calls.{" "}
            <span style={{ color: "#a855f7" }}>Auto-injects</span> = system-initiated loads when a skill matches the conversation.
          </div>
        </div>
      )}

      {/* --- Skill activity chart (14 days) --- */}
      {activityData && activityData.some((d) => d.surfacings + d.auto_injects > 0) && (
        <SkillActivityChart data={activityData} />
      )}

      {/* --- Failures callout --- */}
      {botsWithFailures.length > 0 && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 8,
          padding: "12px 16px", borderRadius: 10,
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
                  <ArrowRight size={10} color={t.danger} style={{ flexShrink: 0 }} />
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* --- Two-column: Bot table + Memory Activity --- */}
      <div style={{ display: "flex", gap: 20, flexDirection: isMobile ? "column" : "row" }}>
        {/* Left: Dreaming status table */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginBottom: 10,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Moon size={14} color="#8b5cf6" />
              <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Dreaming by Bot</span>
            </div>
            <button
              onClick={() => router.push("/admin/learning#Dreaming" as any)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                fontSize: 10, color: t.textMuted, background: "none", border: "none",
                cursor: "pointer", padding: "2px 0",
              }}
            >
              Manage <ArrowRight size={9} />
            </button>
          </div>
          <DreamingBotTable bots={data.bots} mode="view" />
        </div>

        {/* Right: Memory Activity Feed */}
        <div style={{ flex: 1, minWidth: 0, maxWidth: isMobile ? undefined : 420 }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 6, marginBottom: 10,
          }}>
            <PenLine size={14} color={t.textMuted} />
            <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Memory Activity</span>
            <span style={{ fontSize: 10, color: t.textDim, fontWeight: 400 }}>(7d)</span>
          </div>

          {/* Activity heatmap */}
          {(data.memory_activity?.length ?? 0) > 0 && (
            <div style={{
              marginBottom: 10, padding: "10px 12px", borderRadius: 8,
              background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
            }}>
              <ActivityHeatmap activity={data.memory_activity} />
            </div>
          )}

          {activityByDay.length === 0 ? (
            <div style={{
              padding: 24, textAlign: "center", borderRadius: 10,
              background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
            }}>
              <FileText size={20} color={t.textDim} style={{ marginBottom: 8 }} />
              <div style={{ fontSize: 12, color: t.textDim }}>No memory file activity in the last 7 days.</div>
            </div>
          ) : (
            <div style={{
              borderRadius: 10, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden",
              maxHeight: 460, overflowY: "auto",
            }}>
              {activityByDay.map((group) => (
                <div key={group.date}>
                  <div style={{
                    padding: "4px 12px", fontSize: 9, fontWeight: 700, color: t.textDim,
                    textTransform: "uppercase", letterSpacing: 0.8,
                    background: t.surfaceOverlay, borderBottom: `1px solid ${t.surfaceBorder}`,
                    position: "sticky", top: 0, zIndex: 1,
                  }}>
                    {group.date}
                  </div>
                  {group.items.map((item, i) => (
                    <div
                      key={`${item.created_at}-${i}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "7px 12px",
                        borderBottom: `1px solid ${t.surfaceBorder}`,
                      }}
                    >
                      <div style={{
                        width: 3, height: 20, borderRadius: 2, flexShrink: 0,
                        background: item.is_hygiene ? "#8b5cf6" : t.surfaceBorder,
                      }} />
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
                              fontSize: 7, fontWeight: 700, padding: "1px 5px", borderRadius: 3,
                              background: "rgba(139,92,246,0.15)", color: "#8b5cf6",
                              textTransform: "uppercase", letterSpacing: 0.5,
                            }}>
                              dreaming
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 9, color: t.textDim, marginTop: 1 }}>
                          {item.bot_name} {OP_LABELS[item.operation] ?? item.operation} &middot;{" "}
                          {new Date(item.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
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
