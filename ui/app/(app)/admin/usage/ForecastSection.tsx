import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";

import { useUsageForecast } from "@/src/api/hooks/useUsageForecast";
import type { ForecastComponent, LimitForecast, UsageForecast } from "@/src/api/hooks/useUsageForecast";
import { BarChart } from "@/src/components/shared/SimpleCharts";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  ActionButton,
  InfoBanner,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsMeter,
  SettingsSegmentedControl,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

const SOURCE_LABELS: Record<string, string> = {
  heartbeats: "Heartbeats",
  recurring_tasks: "Recurring Tasks",
  maintenance_tasks: "Maintenance",
  trajectory: "Trajectory",
  fixed_plans: "Fixed Plans",
};

const SOURCE_DOT_CLASSES = ["bg-accent", "bg-success", "bg-warning", "bg-purple", "bg-danger"] as const;
const SOURCE_BAR_CLASSES = ["bg-accent/70", "bg-success/70", "bg-warning/70", "bg-purple/70", "bg-danger/70"] as const;

type ForecastPeriod = "daily" | "monthly";

function getCost(component: ForecastComponent, period: ForecastPeriod): number {
  return period === "daily" ? component.daily_cost : component.monthly_cost;
}

function limitTone(value: number): "success" | "warning" | "danger" | "accent" {
  if (value >= 90) return "danger";
  if (value >= 70) return "warning";
  return "success";
}

function alertLevel(limit: LimitForecast): "danger" | "warning" | null {
  if (limit.percentage > 90 || limit.projected_percentage > 100) return "danger";
  if (limit.percentage > 70 || limit.projected_percentage > 90) return "warning";
  return null;
}

function LimitAlerts({ limits }: { limits: LimitForecast[] }) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const atRisk = limits.filter((limit) => alertLevel(limit));
  if (atRisk.length === 0) return null;

  const hasDanger = atRisk.some((limit) => alertLevel(limit) === "danger");
  return (
    <InfoBanner
      variant={hasDanger ? "danger" : "warning"}
      icon={<AlertTriangle size={15} />}
    >
      <div className="flex min-w-0 items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{hasDanger ? "Limit exceeded" : "Approaching limit"}</div>
          <div className="mt-1 flex flex-col gap-1 text-text-muted">
            {atRisk.map((limit) => (
              <div key={`${limit.scope_type}-${limit.scope_value}-${limit.period}`}>
                <span className="font-semibold text-text">{limit.scope_value}</span>{" "}
                ({limit.scope_type}, {limit.period}): {limit.percentage.toFixed(0)}% used
                {limit.projected_percentage > limit.percentage && (
                  <span className="text-text-dim">
                    {" -> projected "}{limit.projected_percentage.toFixed(0)}%
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
        <button
          type="button"
          aria-label="Dismiss limit warning"
          onClick={() => setDismissed(true)}
          className="shrink-0 rounded p-1 text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text"
        >
          <X size={13} />
        </button>
      </div>
    </InfoBanner>
  );
}

function ForecastSummary({ forecast }: { forecast: UsageForecast }) {
  const dailyMax = Math.max(forecast.projected_daily, forecast.daily_spend, 0.01);
  const monthlyMax = Math.max(forecast.projected_monthly, forecast.monthly_spend, 0.01);
  const dailyRisk = forecast.limits
    .filter((limit) => limit.period === "daily")
    .reduce((max, limit) => Math.max(max, limit.projected_percentage, limit.percentage), 0);
  const monthlyRisk = forecast.limits
    .filter((limit) => limit.period === "monthly")
    .reduce((max, limit) => Math.max(max, limit.projected_percentage, limit.percentage), 0);
  const hoursElapsed = forecast.hours_elapsed_today;
  const hourLabel = hoursElapsed < 1
    ? `${Math.round(hoursElapsed * 60)}m elapsed`
    : `${hoursElapsed.toFixed(1)}h elapsed`;

  return (
    <div className="grid gap-2 md:grid-cols-2">
      <div className="rounded-md bg-surface-raised/40 px-4 py-3">
        <SettingsMeter
          value={forecast.daily_spend}
          projected={forecast.projected_daily}
          max={dailyMax}
          tone={limitTone(dailyRisk)}
          label="Today"
          valueLabel={fmtCost(forecast.daily_spend)}
          projectedLabel={`projected ${fmtCost(forecast.projected_daily)}`}
        />
        <div className="mt-2 text-[11px] text-text-dim">{hourLabel}</div>
      </div>
      <div className="rounded-md bg-surface-raised/40 px-4 py-3">
        <SettingsMeter
          value={forecast.monthly_spend}
          projected={forecast.projected_monthly}
          max={monthlyMax}
          tone={limitTone(monthlyRisk)}
          label="This month"
          valueLabel={fmtCost(forecast.monthly_spend)}
          projectedLabel={`projected ${fmtCost(forecast.projected_monthly)}`}
        />
        <div className="mt-2 text-[11px] text-text-dim">Current spend vs projected period close</div>
      </div>
    </div>
  );
}

function ForecastBreakdown({ components }: { components: ForecastComponent[] }) {
  if (components.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <SettingsGroupLabel label="Forecast breakdown" count={components.length} />
      <div className="flex flex-col gap-1">
        {components.map((component, index) => (
          <SettingsControlRow
            key={component.source}
            compact
            leading={
              <span
                className={`block h-2.5 w-2.5 rounded-sm ${SOURCE_DOT_CLASSES[index % SOURCE_DOT_CLASSES.length]}`}
              />
            }
            title={SOURCE_LABELS[component.source] || component.label}
            description={[
              component.count != null ? `${component.count} runs` : null,
              component.avg_cost_per_run != null ? `${fmtCost(component.avg_cost_per_run)}/run` : null,
            ].filter(Boolean).join(" · ")}
            meta={
              <div className="flex items-center gap-2 font-mono">
                <span>{fmtCost(component.daily_cost)}/day</span>
                <span>{fmtCost(component.monthly_cost)}/mo</span>
              </div>
            }
          />
        ))}
      </div>
    </div>
  );
}

function ForecastBarChart({ components, period }: { components: ForecastComponent[]; period: ForecastPeriod }) {
  const items = components
    .filter((component) => getCost(component, period) > 0)
    .map((component, index) => ({
      label: SOURCE_LABELS[component.source] || component.label,
      value: getCost(component, period),
      colorClass: SOURCE_BAR_CLASSES[index % SOURCE_BAR_CLASSES.length],
    }));

  if (items.length === 0) return null;

  return (
    <div className="rounded-md bg-surface-raised/40 px-4 py-3">
      <SettingsGroupLabel label={`${period} forecast by component`} />
      <div className="mt-3">
        <BarChart items={items} formatValue={fmtCost} />
      </div>
    </div>
  );
}

function LimitForecastRows({ limits }: { limits: LimitForecast[] }) {
  if (limits.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <SettingsGroupLabel label="Limit projections" count={limits.length} />
      <div className="grid gap-2 md:grid-cols-2">
        {limits.map((limit) => {
          const tone = limitTone(Math.max(limit.percentage, limit.projected_percentage));
          return (
            <div
              key={`${limit.scope_type}-${limit.scope_value}-${limit.period}`}
              className="rounded-md bg-surface-raised/40 px-3 py-2.5"
            >
              <div className="mb-2 flex min-w-0 items-center gap-2">
                <StatusBadge label={limit.period} variant={tone === "danger" ? "danger" : tone === "warning" ? "warning" : "success"} />
                <div className="min-w-0 truncate text-[12px] font-semibold text-text">{limit.scope_value}</div>
                <div className="ml-auto text-[10px] uppercase tracking-[0.06em] text-text-dim">{limit.scope_type}</div>
              </div>
              <SettingsMeter
                value={limit.percentage}
                projected={limit.projected_percentage}
                tone={tone}
                label={fmtCost(limit.current_spend)}
                valueLabel={`${limit.percentage.toFixed(0)}%`}
                projectedLabel={`projected ${limit.projected_percentage.toFixed(0)}%`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ForecastTab() {
  const { data: forecast, isLoading, refetch } = useUsageForecast();
  const [period, setPeriod] = useState<ForecastPeriod>("daily");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }

  if (!forecast) {
    return <div className="py-10 text-center text-[13px] text-text-dim">No forecast data available.</div>;
  }

  return (
    <div className="flex flex-col gap-5">
      <LimitAlerts limits={forecast.limits} />
      <ForecastSummary forecast={forecast} />
      <SettingsStatGrid
        items={[
          { label: "Daily projected", value: fmtCost(forecast.projected_daily), tone: "accent" },
          { label: "Monthly projected", value: fmtCost(forecast.projected_monthly), tone: "accent" },
          { label: "Today actual", value: fmtCost(forecast.daily_spend) },
          { label: "Month actual", value: fmtCost(forecast.monthly_spend) },
        ]}
      />
      <div className="flex items-center justify-between gap-3">
        <SettingsGroupLabel label="Projection period" />
        <SettingsSegmentedControl
          value={period}
          onChange={setPeriod}
          options={[
            { value: "daily", label: "Daily" },
            { value: "monthly", label: "Monthly" },
          ]}
        />
      </div>
      <ForecastBarChart components={forecast.components} period={period} />
      <ForecastBreakdown components={forecast.components} />
      <LimitForecastRows limits={forecast.limits} />
      <div className="flex justify-end">
        <ActionButton label="Refresh forecast" variant="secondary" size="small" onPress={() => void refetch()} />
      </div>
    </div>
  );
}
