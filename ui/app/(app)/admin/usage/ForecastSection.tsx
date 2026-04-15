
import { Spinner } from "@/src/components/shared/Spinner";
import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { BarChart } from "@/src/components/shared/SimpleCharts";
import { useUsageForecast } from "@/src/api/hooks/useUsageForecast";
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
        display: "flex", flexDirection: "row",
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
                {" "}&mdash; projected {lf.projected_percentage.toFixed(0)}%
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
      <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "monospace" }}>
          {fmtCost(actual)}
        </span>
        <span style={{ fontSize: 12, color: t.textDim }}>
          &rarr; {fmtCost(projected)}
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
    <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
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
// DonutChart — SVG donut showing proportional daily cost by component
// ---------------------------------------------------------------------------

const SOURCE_LABELS: Record<string, string> = {
  heartbeats: "Heartbeats",
  recurring_tasks: "Recurring Tasks",
  trajectory: "Trajectory",
  fixed_plans: "Fixed Plans",
};

const SOURCE_COLORS: Record<string, (t: ReturnType<typeof useThemeTokens>) => string> = {
  trajectory: (t) => t.accent,
  heartbeats: (t) => t.success,
  recurring_tasks: (t) => t.warning,
  fixed_plans: (t) => t.purple,
};

type ForecastPeriod = "daily" | "monthly";

function getCost(c: ForecastComponent, period: ForecastPeriod): number {
  return period === "daily" ? c.daily_cost : c.monthly_cost;
}

const PERIOD_LABEL: Record<ForecastPeriod, string> = { daily: "Daily", monthly: "Monthly" };
const PERIOD_SUFFIX: Record<ForecastPeriod, string> = { daily: "/ day", monthly: "/ month" };

function PeriodToggle({ period, onChange }: { period: ForecastPeriod; onChange: (p: ForecastPeriod) => void }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 2 }}>
      {(["daily", "monthly"] as const).map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          style={{
            padding: "3px 10px",
            fontSize: 11,
            fontWeight: period === p ? 600 : 400,
            background: period === p ? t.accent : "transparent",
            color: period === p ? "#fff" : t.textMuted,
            border: `1px solid ${period === p ? t.accent : t.surfaceBorder}`,
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          {PERIOD_LABEL[p]}
        </button>
      ))}
    </div>
  );
}

function DonutChart({ components, period }: { components: ForecastComponent[]; period: ForecastPeriod }) {
  const t = useThemeTokens();
  const items = components.filter((c) => getCost(c, period) > 0);
  const total = items.reduce((s, c) => s + getCost(c, period), 0);

  if (items.length === 0 || total === 0) return null;

  const size = 180;
  const cx = size / 2;
  const cy = size / 2;
  const outerR = 70;
  const innerR = 48;

  // Build arc segments
  let startAngle = -Math.PI / 2; // start at top
  const segments = items.map((c) => {
    const cost = getCost(c, period);
    const fraction = cost / total;
    const sweep = fraction * Math.PI * 2;
    const endAngle = startAngle + sweep;
    const color = (SOURCE_COLORS[c.source] ?? (() => t.accent))(t);

    // Arc path
    const largeArc = sweep > Math.PI ? 1 : 0;
    const x1o = cx + outerR * Math.cos(startAngle);
    const y1o = cy + outerR * Math.sin(startAngle);
    const x2o = cx + outerR * Math.cos(endAngle);
    const y2o = cy + outerR * Math.sin(endAngle);
    const x1i = cx + innerR * Math.cos(endAngle);
    const y1i = cy + innerR * Math.sin(endAngle);
    const x2i = cx + innerR * Math.cos(startAngle);
    const y2i = cy + innerR * Math.sin(startAngle);

    const path = [
      `M ${x1o} ${y1o}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2o} ${y2o}`,
      `L ${x1i} ${y1i}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 0 ${x2i} ${y2i}`,
      "Z",
    ].join(" ");

    startAngle = endAngle;

    return { source: c.source, label: SOURCE_LABELS[c.source] || c.label, color, path, cost };
  });

  return (
    <div
      style={{
        flex: 1,
        minWidth: 220,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: 16,
        border: `1px solid ${t.surfaceOverlay}`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12, alignSelf: "flex-start" }}>
        {PERIOD_LABEL[period]} Cost Breakdown
      </div>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {segments.map((seg, i) => (
          <path key={i} d={seg.path} fill={seg.color} opacity={0.85} />
        ))}
        {/* Center text */}
        <text x={cx} y={cy - 6} textAnchor="middle" fill={t.textDim} fontSize={10}>
          Projected
        </text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill={t.text} fontSize={16} fontWeight={700} fontFamily="monospace">
          {fmtCost(total)}
        </text>
        <text x={cx} y={cy + 26} textAnchor="middle" fill={t.textDim} fontSize={9}>
          {PERIOD_SUFFIX[period]}
        </text>
      </svg>
      {/* Legend */}
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 12, justifyContent: "center" }}>
        {segments.map((seg) => (
          <div key={seg.source} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 5 }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: seg.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: t.textMuted }}>
              {seg.label} {fmtCost(seg.cost)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SpendComparisonChart — Actual vs Projected grouped horizontal bars
// ---------------------------------------------------------------------------

function SpendComparisonChart({ forecast }: { forecast: UsageForecast }) {
  const t = useThemeTokens();
  const maxVal = Math.max(forecast.projected_daily, forecast.projected_monthly, 0.01);

  const groups: { label: string; actual: number; projected: number }[] = [
    { label: "Today", actual: forecast.daily_spend, projected: forecast.projected_daily },
    { label: "This Month", actual: forecast.monthly_spend, projected: forecast.projected_monthly },
  ];

  return (
    <div
      style={{
        flex: 1,
        minWidth: 280,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: 16,
        border: `1px solid ${t.surfaceOverlay}`,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 16 }}>
        Actual vs Projected
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {groups.map((g) => {
          const gMax = Math.max(g.projected, 0.01);
          return (
            <div key={g.label}>
              <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 6 }}>{g.label}</div>
              {/* Actual bar */}
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ width: 60, fontSize: 10, color: t.textDim, textAlign: "right" }}>Actual</span>
                <div style={{ flex: 1, height: 18, background: t.surfaceOverlay, borderRadius: 4, position: "relative" }}>
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      bottom: 0,
                      width: `${Math.min((g.actual / gMax) * 100, 100)}%`,
                      background: t.accent,
                      borderRadius: 4,
                      minWidth: g.actual > 0 ? 2 : 0,
                    }}
                  />
                </div>
                <span style={{ width: 70, fontSize: 11, fontFamily: "monospace", color: t.text, textAlign: "right" }}>
                  {fmtCost(g.actual)}
                </span>
              </div>
              {/* Projected bar */}
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                <span style={{ width: 60, fontSize: 10, color: t.textDim, textAlign: "right" }}>Projected</span>
                <div style={{ flex: 1, height: 18, background: t.surfaceOverlay, borderRadius: 4, position: "relative" }}>
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      bottom: 0,
                      width: `${Math.min((g.projected / gMax) * 100, 100)}%`,
                      background: t.accent,
                      borderRadius: 4,
                      opacity: 0.4,
                      minWidth: g.projected > 0 ? 2 : 0,
                    }}
                  />
                </div>
                <span style={{ width: 70, fontSize: 11, fontFamily: "monospace", color: t.textDim, textAlign: "right" }}>
                  {fmtCost(g.projected)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {/* Legend */}
      <div style={{ display: "flex", flexDirection: "row", gap: 16, marginTop: 14, justifyContent: "center" }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 5 }}>
          <div style={{ width: 12, height: 8, borderRadius: 2, background: t.accent }} />
          <span style={{ fontSize: 10, color: t.textMuted }}>Actual</span>
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 5 }}>
          <div style={{ width: 12, height: 8, borderRadius: 2, background: t.accent, opacity: 0.4 }} />
          <span style={{ fontSize: 10, color: t.textMuted }}>Projected</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ForecastBreakdown — component breakdown table
// ---------------------------------------------------------------------------

function ForecastBreakdown({ components }: { components: ForecastComponent[] }) {
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
            display: "flex", flexDirection: "row",
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
              display: "flex", flexDirection: "row",
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
              {c.count != null && c.avg_cost_per_run != null && " \u00b7 "}
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

function ForecastBarChart({ components, period }: { components: ForecastComponent[]; period: ForecastPeriod }) {
  const t = useThemeTokens();
  if (components.length === 0) return null;

  const items = components
    .filter((c) => getCost(c, period) > 0)
    .map((c) => ({
      label: SOURCE_LABELS[c.source] || c.label,
      value: getCost(c, period),
      color: (SOURCE_COLORS[c.source] ?? (() => t.accent))(t),
    }));

  if (items.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
        {PERIOD_LABEL[period]} Forecast by Component
      </div>
      <BarChart items={items} formatValue={fmtCost} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ForecastTab — top-level tab component
// ---------------------------------------------------------------------------

export function ForecastTab() {
  const t = useThemeTokens();
  const { data: forecast, isLoading } = useUsageForecast();
  const [period, setPeriod] = useState<ForecastPeriod>("daily");

  if (isLoading) {
    return (
      <div className="items-center justify-center" style={{ padding: 40 }}>
        <Spinner />
      </div>
    );
  }

  if (!forecast) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
        No forecast data available.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Limit warnings */}
      <LimitAlerts limits={forecast.limits} />

      {/* Today + This Month cards */}
      <ForecastCards forecast={forecast} />

      {/* Period toggle */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, color: t.textDim }}>Projection period:</span>
        <PeriodToggle period={period} onChange={setPeriod} />
      </div>

      {/* Donut + Comparison side by side */}
      <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
        <DonutChart components={forecast.components} period={period} />
        <SpendComparisonChart forecast={forecast} />
      </div>

      {/* Breakdown table */}
      <ForecastBreakdown components={forecast.components} />

      {/* Bar chart */}
      <ForecastBarChart components={forecast.components} period={period} />
    </div>
  );
}
