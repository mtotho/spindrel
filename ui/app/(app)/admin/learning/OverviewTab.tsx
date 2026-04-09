import { useMemo } from "react";
import { useRouter } from "expo-router";
import {
  Moon, Activity, BookOpen, TrendingUp, CheckCircle, XCircle, Clock,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview } from "@/src/api/hooks/useLearningOverview";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import { StatusBadge } from "@/src/components/shared/SettingsControls";

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) {
    // future
    const mins = Math.floor(-diffMs / 60_000);
    if (mins < 60) return `in ${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `in ${hrs}h`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function StatCard({ label, value, icon, color }: {
  label: string; value: number | string; icon: React.ReactNode; color?: string;
}) {
  const t = useThemeTokens();
  return (
    <div style={{
      flex: 1, minWidth: 140, padding: "14px 16px", borderRadius: 10,
      background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        {icon}
        <span style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", fontWeight: 600, letterSpacing: 0.5 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || t.text }}>{value}</div>
    </div>
  );
}

export function OverviewTab() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data, isLoading } = useLearningOverview();

  const recentPreview = useMemo(() => (data?.recent_runs ?? []).slice(0, 5), [data]);
  const successRate = useMemo(() => {
    if (!data?.recent_runs.length) return null;
    const complete = data.recent_runs.filter((r) => r.status === "complete").length;
    return Math.round((complete / data.recent_runs.length) * 100);
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

      {/* Dreaming status table */}
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
          <Moon size={14} color="#8b5cf6" />
          Dreaming by Bot
        </div>
        <div style={{ borderRadius: 8, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden" }}>
          {/* Header */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 80px 120px 80px 120px",
            gap: 8,
            padding: "8px 14px",
            background: t.surfaceOverlay,
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}>
            {["Bot", "Status", "Last Run", "Result", "Next Run"].map((h) => (
              <span key={h} style={{ fontSize: 9, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
                {h}
              </span>
            ))}
          </div>
          {/* Rows */}
          {data.bots.map((bot) => (
            <button
              key={bot.bot_id}
              onClick={() => router.push(`/admin/bots/${bot.bot_id}#memory` as any)}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 80px 120px 80px 120px",
                gap: 8,
                padding: "10px 14px",
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
              <span style={{ fontSize: 11, color: t.textMuted }}>{fmtRelative(bot.last_run_at)}</span>
              <span>
                {bot.last_task_status && (
                  <StatusBadge
                    label={bot.last_task_status}
                    variant={bot.last_task_status === "complete" ? "success" : bot.last_task_status === "failed" ? "danger" : "neutral"}
                  />
                )}
              </span>
              <span style={{ fontSize: 11, color: t.textDim }}>{fmtRelative(bot.next_run_at)}</span>
            </button>
          ))}
          {data.bots.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: t.textDim, fontSize: 12 }}>
              No bots with workspace-files memory found.
            </div>
          )}
        </div>
      </div>

      {/* Recent runs */}
      {recentPreview.length > 0 && (
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: t.text, display: "flex", alignItems: "center", gap: 6 }}>
              <Clock size={14} color={t.textMuted} />
              Recent Dreaming Runs
              {successRate !== null && (
                <span style={{
                  fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4, marginLeft: 4,
                  background: successRate >= 80 ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                  color: successRate >= 80 ? "#059669" : "#ef4444",
                }}>
                  {successRate}% pass
                </span>
              )}
            </div>
          </div>
          <HygieneHistoryList runs={recentPreview} showBotName />
        </div>
      )}
    </div>
  );
}
