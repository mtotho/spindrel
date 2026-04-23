import { useMemo } from "react";
import { useUsageTimeSeries } from "@/src/api/hooks/useUsage";
import { useUsageForecast } from "@/src/api/hooks/useUsageForecast";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { PreviewCard, parsePayload } from "./shared";

function fmtCost(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  if (value >= 100) return `$${Math.round(value)}`;
  if (value >= 1) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(3)}`;
}

function startOfDay(date: Date): Date {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
}

function dayKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

interface ActivityBar {
  label: string;
  value: number;
  isToday: boolean;
}

function buildActivityBars(points: { bucket: string; calls: number }[] | undefined): ActivityBar[] {
  const today = startOfDay(new Date());
  const pointMap = new Map<string, number>();
  for (const point of points ?? []) {
    const bucket = new Date(point.bucket);
    if (Number.isNaN(bucket.getTime())) continue;
    pointMap.set(dayKey(startOfDay(bucket)), point.calls ?? 0);
  }

  const bars: ActivityBar[] = [];
  for (let offset = 6; offset >= 0; offset -= 1) {
    const day = new Date(today);
    day.setDate(today.getDate() - offset);
    const key = dayKey(day);
    bars.push({
      label: day.toLocaleDateString([], { weekday: "short" }),
      value: pointMap.get(key) ?? 0,
      isToday: offset === 0,
    });
  }
  return bars;
}

function StatBlock({
  label,
  value,
  sublabel,
  t,
}: {
  label: string;
  value: string;
  sublabel: string;
  t: ThemeTokens;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 2,
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: t.textDim,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 24,
          lineHeight: 1,
          fontWeight: 650,
          color: t.text,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11, color: t.textMuted }}>{sublabel}</div>
    </div>
  );
}

function ActivityChart({
  bars,
  t,
}: {
  bars: ActivityBar[];
  t: ThemeTokens;
}) {
  const maxValue = Math.max(...bars.map((bar) => bar.value), 1);
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))`,
        gap: 8,
        alignItems: "end",
        minHeight: 112,
        paddingTop: 10,
      }}
    >
      {bars.map((bar) => {
        const height = Math.max((bar.value / maxValue) * 78, bar.value > 0 ? 8 : 2);
        return (
          <div
            key={bar.label}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "stretch",
              gap: 8,
              minWidth: 0,
            }}
          >
            <div
              title={`${bar.label}: ${bar.value} calls`}
              style={{
                height: 82,
                display: "flex",
                alignItems: "flex-end",
              }}
            >
              <div
                style={{
                  width: "100%",
                  height,
                  background: bar.isToday ? t.accent : t.accentMuted,
                  opacity: bar.value > 0 ? 0.92 : 0.2,
                  transition: "height 180ms ease",
                }}
              />
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 2,
                alignItems: "center",
                color: bar.isToday ? t.text : t.textMuted,
                fontSize: 10,
              }}
            >
              <span>{bar.label}</span>
              <span style={{ fontVariantNumeric: "tabular-nums", color: t.textDim }}>
                {bar.value}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function UsageForecastWidget({
  envelope,
  t,
}: {
  envelope: ToolResultEnvelope;
  sessionId?: string;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
  const payload = parsePayload(envelope);
  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Usage Forecast"
        description="Global usage forecast with a compact weekly activity chart."
        t={t}
      />
    );
  }

  const range = useMemo(() => {
    const today = startOfDay(new Date());
    const after = new Date(today);
    after.setDate(today.getDate() - 6);
    return {
      after: after.toISOString(),
      before: new Date().toISOString(),
    };
  }, []);
  const { data: forecast, isLoading, isError } = useUsageForecast();
  const { data: timeseries } = useUsageTimeSeries({
    after: range.after,
    before: range.before,
    bucket: "day",
  });

  if (isLoading) {
    return <div style={{ color: t.textDim, fontSize: 12 }}>Loading usage forecast…</div>;
  }
  if (isError || !forecast) {
    return (
      <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.6 }}>
        Usage forecast is only available where admin usage data can be read.
      </div>
    );
  }

  const bars = buildActivityBars(timeseries?.points);
  const worstLimit = forecast.limits.reduce((max, limit) => (
    Math.max(max, limit.projected_percentage, limit.percentage)
  ), 0);
  const activityTotal = bars.reduce((sum, bar) => sum + bar.value, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: "100%" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 12,
          paddingBottom: 10,
          borderBottom: `1px solid ${t.surfaceBorder}`,
        }}
      >
        <StatBlock
          label="Today"
          value={fmtCost(forecast.projected_daily)}
          sublabel={`${fmtCost(forecast.daily_spend)} spent so far`}
          t={t}
        />
        <StatBlock
          label="Month"
          value={fmtCost(forecast.projected_monthly)}
          sublabel={`${fmtCost(forecast.monthly_spend)} booked`}
          t={t}
        />
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: t.textDim,
          }}
        >
          Last 7 Days
        </div>
        <div style={{ fontSize: 11, color: t.textMuted, fontVariantNumeric: "tabular-nums" }}>
          {activityTotal} calls
        </div>
      </div>

      <ActivityChart bars={bars} t={t} />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          paddingTop: 8,
          borderTop: `1px solid ${t.surfaceBorder}`,
          fontSize: 11,
          color: t.textDim,
        }}
      >
        <span>{forecast.components.length} forecast inputs</span>
        <span>
          limit risk {worstLimit > 0 ? `${Math.round(worstLimit)}%` : "clear"}
        </span>
      </div>
    </div>
  );
}
