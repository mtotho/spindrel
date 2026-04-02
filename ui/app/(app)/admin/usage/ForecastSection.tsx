import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { BarChart } from "@/src/components/shared/SimpleCharts";
import type { UsageForecast, ForecastComponent, LimitForecast } from "@/src/api/hooks/useUsageForecast";

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

// ---------------------------------------------------------------------------
// LimitAlerts — warning banners when limits are at risk
// ---------------------------------------------------------------------------

function alertLevel(lf: LimitForecast): "red" | "orange" | null {
  if (lf.percentage > 90 || lf.projected_percentage > 100) return "red";
  if (lf.percentage > 70 || lf.projected_percentage > 90) return "orange";
  return null;
}

export function LimitAlerts({ limits }: { limits: LimitForecast[] }) {
  const t = useThemeTokens();
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const atRisk = limits.filter((lf) => alertLevel(lf) !== null);
  if (atRisk.length === 0) return null;

  const hasRed = atRisk.some((lf) => alertLevel(lf) === "red");
  const bg = hasRed ? t.dangerSubtle : t.warningSubtle;
  const border = hasRed ? t.danger : t.warning;
  const color = hasRed ? t.danger : t.warning;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        padding: "10px 14px",
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 8,
        fontSize: 12,
        color,
      }}
    >
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ flex: 1 }}>
        <strong>{hasRed ? "Limit exceeded" : "Approaching limit"}</strong>
        {atRisk.map((lf, i) => (
          <div key={i} style={{ marginTop: 4, color: t.textMuted }}>
            <span style={{ color }}>{lf.scope_value}</span>{" "}
            ({lf.scope_type}, {lf.period}): {lf.percentage.toFixed(0)}% used
            {lf.projected_percentage > lf.percentage && (
              <span style={{ color: t.textDim }}>
                {" "}— projected {lf.projected_percentage.toFixed(0)}%
              </span>
            )}
          </div>
        ))}
      </div>
      <button
        onClick={() => setDismissed(true)}
        style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 2 }}
      >
        <X size={14} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ForecastCards — Today + This Month stat cards with progress
// ---------------------------------------------------------------------------

function MiniProgress({ pct, color }: { pct: number; color: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ height: 3, borderRadius: 2, background: t.surfaceBorder, marginTop: 6 }}>
      <div
        style={{
          height: "100%",
          width: `${Math.min(pct, 100)}%`,
          background: color,
          borderRadius: 2,
          transition: "width 0.3s ease",
        }}
      />
    </div>
  );
}

function progressColor(pct: number, t: ReturnType<typeof useThemeTokens>): string {
  if (pct >= 90) return t.danger;
  if (pct >= 70) return t.warning;
  return t.success;
}

function ForecastCard({
  label,
  actual,
  projected,
  sub,
  limitPct,
}: {
  label: string;
  actual: number;
  projected: number;
  sub?: string;
  limitPct?: number;
}) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        flex: 1,
        minWidth: 160,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: "14px 16px",
        border: `1px solid ${t.surfaceOverlay}`,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "monospace" }}>
          {fmtCost(actual)}
        </span>
        <span style={{ fontSize: 12, color: t.textDim }}>
          → {fmtCost(projected)}
        </span>
      </div>
      {sub && <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>{sub}</div>}
      {limitPct != null && (
        <MiniProgress pct={limitPct} color={progressColor(limitPct, t)} />
      )}
    </div>
  );
}

export function ForecastCards({ forecast }: { forecast: UsageForecast }) {
  // Find worst limit % for daily and monthly
  const dailyLimits = forecast.limits.filter((l) => l.period === "daily");
  const monthlyLimits = forecast.limits.filter((l) => l.period === "monthly");
  const worstDaily = dailyLimits.length > 0
    ? Math.max(...dailyLimits.map((l) => Math.max(l.percentage, l.projected_percentage)))
    : undefined;
  const worstMonthly = monthlyLimits.length > 0
    ? Math.max(...monthlyLimits.map((l) => Math.max(l.percentage, l.projected_percentage)))
    : undefined;

  const hoursElapsed = forecast.hours_elapsed_today;
  const hourLabel = hoursElapsed < 1
    ? `${Math.round(hoursElapsed * 60)}m elapsed`
    : `${hoursElapsed.toFixed(1)}h elapsed`;

  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      <ForecastCard
        label="Today"
        actual={forecast.daily_spend}
        projected={forecast.projected_daily}
        sub={hourLabel}
        limitPct={worstDaily}
      />
      <ForecastCard
        label="This Month"
        actual={forecast.monthly_spend}
        projected={forecast.projected_monthly}
        limitPct={worstMonthly}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ForecastBreakdown — component breakdown table
// ---------------------------------------------------------------------------

const SOURCE_LABELS: Record<string, string> = {
  heartbeats: "Heartbeats",
  recurring_tasks: "Recurring Tasks",
  trajectory: "Trajectory",
  fixed_plans: "Fixed Plans",
};

export function ForecastBreakdown({ components }: { components: ForecastComponent[] }) {
  const t = useThemeTokens();
  if (components.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>
        Forecast Breakdown
      </div>
      <div style={{ border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8, overflow: "hidden" }}>
        <div
          style={{
            display: "flex",
            gap: 12,
            padding: "8px 12px",
            fontSize: 10,
            fontWeight: 600,
            color: t.textDim,
            textTransform: "uppercase",
            borderBottom: `1px solid ${t.surfaceOverlay}`,
            background: t.surfaceOverlay,
          }}
        >
          <span style={{ flex: 1, minWidth: 0 }}>Source</span>
          <span style={{ width: 80, textAlign: "right" }}>Daily</span>
          <span style={{ width: 80, textAlign: "right" }}>Monthly</span>
          <span style={{ width: 160, textAlign: "right" }}>Details</span>
        </div>
        {components.map((c, i) => (
          <div
            key={c.source}
            style={{
              display: "flex",
              gap: 12,
              padding: "7px 12px",
              fontSize: 12,
              borderBottom: i < components.length - 1 ? `1px solid ${t.surfaceRaised}` : "none",
              alignItems: "center",
            }}
          >
            <span style={{ flex: 1, minWidth: 0, color: t.text }}>
              {SOURCE_LABELS[c.source] || c.label}
            </span>
            <span style={{ width: 80, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
              {fmtCost(c.daily_cost)}
            </span>
            <span style={{ width: 80, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
              {fmtCost(c.monthly_cost)}
            </span>
            <span style={{ width: 160, textAlign: "right", color: t.textDim, fontSize: 11 }}>
              {c.count != null && `${c.count} runs`}
              {c.count != null && c.avg_cost_per_run != null && " · "}
              {c.avg_cost_per_run != null && `${fmtCost(c.avg_cost_per_run)}/run`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ForecastBarChart — horizontal bar chart by component
// ---------------------------------------------------------------------------

const SOURCE_COLORS: Record<string, (t: ReturnType<typeof useThemeTokens>) => string> = {
  trajectory: (t) => t.accent,
  heartbeats: (t) => t.success,
  recurring_tasks: (t) => t.warning,
  fixed_plans: (t) => t.purple,
};

export function ForecastBarChart({ components }: { components: ForecastComponent[] }) {
  const t = useThemeTokens();
  if (components.length === 0) return null;

  const items = components
    .filter((c) => c.daily_cost > 0)
    .map((c) => ({
      label: SOURCE_LABELS[c.source] || c.label,
      value: c.daily_cost,
      color: (SOURCE_COLORS[c.source] ?? (() => t.accent))(t),
    }));

  if (items.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
        Daily Forecast by Component
      </div>
      <BarChart items={items} formatValue={(v) => `$${v.toFixed(4)}`} />
    </div>
  );
}
