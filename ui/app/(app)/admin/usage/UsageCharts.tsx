import { BarChart3, Bot, CircuitBoard, Clock3, Cpu, Hash } from "lucide-react";

import { useUsageBreakdown, useUsageTimeSeries, type UsageParams } from "@/src/api/hooks/useUsage";
import { BarChart, LineChart } from "@/src/components/shared/SimpleCharts";
import { SettingsGroupLabel } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { fmtBucketLabel, fmtCost, fmtTokens } from "./usageUtils";

function BreakdownChart({
  title,
  groupBy,
  icon,
  params,
  metric,
}: {
  title: string;
  groupBy: "model" | "bot" | "provider" | "channel";
  icon: React.ReactNode;
  params: UsageParams;
  metric: "cost" | "tokens" | "calls";
}) {
  const { data, isLoading } = useUsageBreakdown({ ...params, group_by: groupBy });
  if (isLoading) {
    return (
      <div className="flex min-h-[160px] items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <SettingsGroupLabel label={title} count={data?.groups.length ?? 0} icon={icon} />
      <BarChart
        items={(data?.groups ?? [])
          .map((group) => ({
            label: group.label,
            value: metric === "cost" ? group.cost ?? 0 : metric === "tokens" ? group.tokens : group.calls,
          }))
          .filter((item) => item.value > 0)}
        formatValue={metric === "cost" ? fmtCost : (value) => fmtTokens(Math.round(value))}
      />
    </div>
  );
}

export function ChartsTab({ params }: { params: UsageParams }) {
  const { data: timeseries, isLoading } = useUsageTimeSeries(params);
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }
  const points = timeseries?.points ?? [];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="space-y-2">
          <SettingsGroupLabel label="Tokens Over Time" count={points.length} icon={<Clock3 size={13} />} />
          <LineChart
            points={points.map((point) => ({ label: fmtBucketLabel(point.bucket), value: point.tokens }))}
            formatValue={(value) => fmtTokens(Math.round(value))}
            tone="accent"
          />
        </div>
        <div className="space-y-2">
          <SettingsGroupLabel label="Calls Over Time" count={points.length} icon={<BarChart3 size={13} />} />
          <LineChart
            points={points.map((point) => ({ label: fmtBucketLabel(point.bucket), value: point.calls }))}
            formatValue={(value) => String(Math.round(value))}
            tone="success"
          />
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <BreakdownChart title="Cost by Model" groupBy="model" icon={<Cpu size={13} />} params={params} metric="cost" />
        <BreakdownChart title="Tokens by Bot" groupBy="bot" icon={<Bot size={13} />} params={params} metric="tokens" />
        <BreakdownChart title="Calls by Channel" groupBy="channel" icon={<Hash size={13} />} params={params} metric="calls" />
        <BreakdownChart title="Cost by Provider" groupBy="provider" icon={<CircuitBoard size={13} />} params={params} metric="cost" />
      </div>
    </div>
  );
}
