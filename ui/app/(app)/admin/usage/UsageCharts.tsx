
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useUsageBreakdown,
  useUsageTimeSeries,
  type UsageParams,
} from "@/src/api/hooks/useUsage";
import { BarChart, LineChart } from "@/src/components/shared/SimpleCharts";
import { fmtCost, fmtBucketLabel } from "./usageUtils";

// ---------------------------------------------------------------------------
// Charts tab
// ---------------------------------------------------------------------------
export function ChartsTab({ params }: { params: UsageParams }) {
  const t = useThemeTokens();
  const { data: breakdown, isLoading: breakdownLoading } = useUsageBreakdown({
    ...params,
    group_by: "model",
  });
  const { data: timeseries, isLoading: tsLoading } = useUsageTimeSeries(params);

  if (breakdownLoading || tsLoading) {
    return (
      <div className="items-center justify-center" style={{ padding: 40 }}>
        <Spinner />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Cost by Model bar chart */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
          Cost by Model
        </div>
        <BarChart
          items={(breakdown?.groups || [])
            .filter((g) => g.cost != null && g.cost > 0)
            .map((g) => ({ label: g.label, value: g.cost! }))}
          formatValue={fmtCost}
        />
      </div>

      {/* Cost over Time line chart */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
          Cost over Time
        </div>
        <LineChart
          points={(timeseries?.points || []).map((p) => ({
            label: fmtBucketLabel(p.bucket),
            value: p.cost || 0,
          }))}
          formatValue={fmtCost}
        />
      </div>

      {/* Calls over Time line chart */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 12 }}>
          Calls over Time
        </div>
        <LineChart
          points={(timeseries?.points || []).map((p) => ({
            label: fmtBucketLabel(p.bucket),
            value: p.calls,
          }))}
          formatValue={(v) => String(Math.round(v))}
          lineColor={t.success}
          fillColor={t.successSubtle}
        />
      </div>
    </div>
  );
}
