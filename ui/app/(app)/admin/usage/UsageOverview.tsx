import { AlertTriangle, Bot, Clock3, Gauge, ReceiptText, Sparkles, Zap } from "lucide-react";

import {
  useUsageAnomalies,
  useUsageSummary,
  useUsageTimeSeries,
  type UsageAnomalySignal,
  type UsageParams,
} from "@/src/api/hooks/useUsage";
import { useUsageForecast } from "@/src/api/hooks/useUsageForecast";
import {
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { TimelineChart, type TimelineChartPoint } from "@/src/components/shared/SimpleCharts";
import { Spinner } from "@/src/components/shared/Spinner";
import { fmtBucketLabel, fmtCost, fmtRatio, fmtTokens } from "./usageUtils";

function severityVariant(severity: UsageAnomalySignal["severity"]) {
  if (severity === "danger") return "danger";
  if (severity === "warning") return "warning";
  return "info";
}

function signalTitle(signal: UsageAnomalySignal) {
  if (signal.kind === "time_spike" && signal.bucket) {
    return `Spike at ${fmtBucketLabel(signal.bucket)}`;
  }
  return signal.label;
}

function signalTime(signal: UsageAnomalySignal) {
  const value = signal.bucket || signal.created_at;
  return value ? fmtBucketLabel(value) : null;
}

function SignalList({
  title,
  icon,
  items,
  onSelectTrace,
}: {
  title: string;
  icon: React.ReactNode;
  items: UsageAnomalySignal[];
  onSelectTrace: (correlationId: string) => void;
}) {
  return (
    <div className="space-y-2">
      <SettingsGroupLabel label={title} count={items.length} icon={icon} />
      {items.length === 0 ? (
        <EmptyState message="No high-signal anomalies for this window." />
      ) : (
        <div className="space-y-1.5">
          {items.map((signal) => (
            <SettingsControlRow
              key={signal.id}
              title={signalTitle(signal)}
              description={[
                signalTime(signal),
                signal.reason,
                `${fmtTokens(signal.metric.tokens)} tokens`,
                `${signal.metric.calls} calls`,
                signal.metric.cost != null ? fmtCost(signal.metric.cost) : "cost unknown",
                signal.source.title,
                signal.source.channel_name,
                signal.source.model,
              ].filter(Boolean).join(" · ")}
              meta={
                <div className="flex flex-wrap items-center gap-1.5">
                  <StatusBadge label={signal.severity} variant={severityVariant(signal.severity)} />
                  <QuietPill label={signal.cost_confidence.replaceAll("_", " ")} />
                  {signal.ratio != null && <QuietPill label={`${fmtRatio(signal.ratio)} baseline`} />}
                  {signal.correlation_id && <QuietPill label="trace" />}
                </div>
              }
              onClick={signal.correlation_id ? () => onSelectTrace(signal.correlation_id!) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function OverviewTab({
  params,
  onDrillDown,
  onSelectTrace,
}: {
  params: UsageParams;
  onDrillDown: (filter: { model?: string; bot_id?: string; provider_id?: string }) => void;
  onSelectTrace: (correlationId: string) => void;
}) {
  const { data: summary, isLoading: summaryLoading } = useUsageSummary(params);
  const { data: forecast } = useUsageForecast();
  const { data: timeseries, isLoading: timeseriesLoading } = useUsageTimeSeries(params);
  const { data: anomalies, isLoading: anomaliesLoading } = useUsageAnomalies(params);

  if (summaryLoading || timeseriesLoading || anomaliesLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }
  if (!summary) return null;

  const anomalyCount =
    (anomalies?.time_spikes.length ?? 0) +
    (anomalies?.trace_bursts.length ?? 0) +
    (anomalies?.contributors.length ?? 0);
  const markerByBucket = new Map(
    (anomalies?.time_spikes ?? []).map((signal) => [signal.bucket, signal.severity] as const),
  );
  const spikeByBucket = new Map(
    (anomalies?.time_spikes ?? []).map((signal) => [signal.bucket, signal] as const),
  );
  const points: TimelineChartPoint[] = (timeseries?.points ?? []).map((point) => {
    const marker = markerByBucket.get(point.bucket);
    const spike = spikeByBucket.get(point.bucket);
    return {
      bucket: point.bucket,
      label: fmtBucketLabel(point.bucket),
      value: point.tokens,
      secondaryValue: point.cost,
      calls: point.calls,
      marker: marker === "danger" ? "danger" : marker === "warning" ? "warning" : marker ? "info" : undefined,
      selectable: Boolean(spike?.correlation_id),
    };
  });
  const avgCost =
    summary.total_cost != null && summary.total_calls > 0
      ? summary.total_cost / summary.total_calls
      : null;

  return (
    <div className="space-y-5">
      <InfoBanner
        variant={anomalyCount > 0 || summary.calls_without_cost_data > 0 ? "warning" : "success"}
        icon={anomalyCount > 0 ? <AlertTriangle size={15} /> : <Gauge size={15} />}
      >
        {anomalyCount > 0
          ? `${anomalyCount} usage signal${anomalyCount === 1 ? "" : "s"} need review in this window.`
          : "No high-signal usage anomalies found for this window."}
        {summary.calls_without_cost_data > 0
          ? ` ${summary.calls_without_cost_data} call${summary.calls_without_cost_data === 1 ? "" : "s"} are missing pricing data.`
          : ""}
      </InfoBanner>

      <SettingsStatGrid
        items={[
          { label: "Calls", value: fmtTokens(summary.total_calls) },
          { label: "Tokens", value: fmtTokens(summary.total_tokens), tone: "accent" },
          { label: "Cost", value: fmtCost(summary.total_cost), tone: summary.total_cost == null ? "warning" : "default" },
          { label: "Avg / call", value: fmtCost(avgCost) },
          { label: "Projected", value: fmtCost(forecast?.projected_monthly), tone: forecast?.projected_monthly != null ? "success" : "default" },
          { label: "No pricing", value: summary.calls_without_cost_data, tone: summary.calls_without_cost_data > 0 ? "warning" : "default" },
          { label: "Models", value: summary.cost_by_model.length },
          { label: "Providers", value: summary.cost_by_provider.length },
        ]}
      />

      <div className="space-y-2">
        <SettingsGroupLabel label="Token Timeline" count={points.length} icon={<Clock3 size={13} />} />
        <TimelineChart
          points={points}
          formatValue={fmtTokens}
          onSelect={(point) => {
            const spike = spikeByBucket.get(point.bucket);
            if (spike?.correlation_id) onSelectTrace(spike.correlation_id);
          }}
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <SignalList title="Time Spikes" icon={<Zap size={13} />} items={anomalies?.time_spikes ?? []} onSelectTrace={onSelectTrace} />
        <SignalList title="Trace Bursts" icon={<Sparkles size={13} />} items={anomalies?.trace_bursts ?? []} onSelectTrace={onSelectTrace} />
        <SignalList title="Top Contributors" icon={<Bot size={13} />} items={anomalies?.contributors ?? []} onSelectTrace={onSelectTrace} />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {[
          ["Cost by Model", summary.cost_by_model, (label: string) => onDrillDown({ model: label })],
          ["Cost by Bot", summary.cost_by_bot, (label: string) => onDrillDown({ bot_id: label })],
          ["Cost by Provider", summary.cost_by_provider, (label: string) => onDrillDown({ provider_id: label === "default" ? undefined : label })],
        ].map(([title, items, onClick]) => (
          <div key={title as string} className="space-y-2">
            <SettingsGroupLabel label={title as string} count={(items as any[]).length} icon={<ReceiptText size={13} />} />
            <div className="space-y-1.5">
              {(items as any[]).slice(0, 6).map((item) => (
                <SettingsControlRow
                  key={item.label}
                  title={item.label}
                  description={`${fmtTokens(item.total_tokens)} tokens · ${item.calls} calls`}
                  meta={<span className="font-mono text-[11px] text-text">{fmtCost(item.cost)}</span>}
                  onClick={() => (onClick as (label: string) => void)(item.label)}
                />
              ))}
              {(items as any[]).length === 0 && <EmptyState message="No cost data for this dimension." />}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
