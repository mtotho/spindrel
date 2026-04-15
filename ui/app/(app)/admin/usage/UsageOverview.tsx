
import { Spinner } from "@/src/components/shared/Spinner";
import { AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useUsageSummary,
  type UsageParams,
  type CostByDimension,
} from "@/src/api/hooks/useUsage";
import { useUsageForecast } from "@/src/api/hooks/useUsageForecast";
import { LimitAlerts, ForecastCards } from "./ForecastSection";
import { fmtCost, fmtTokens } from "./usageUtils";

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------
function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        flex: 1,
        minWidth: 140,
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: "14px 16px",
        border: `1px solid ${t.surfaceOverlay}`,
      }}
    >
      <div style={{ fontSize: 11, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "monospace" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: t.textDim, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cost dimension table (clickable rows)
// ---------------------------------------------------------------------------
function CostTable({
  title,
  items,
  onClickItem,
}: {
  title: string;
  items: CostByDimension[];
  onClickItem?: (label: string) => void;
}) {
  const t = useThemeTokens();
  if (items.length === 0) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>{title}</div>
      <div style={{ border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8, overflow: "hidden" }}>
        {/* Header */}
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
          <span style={{ flex: 1, minWidth: 0 }}>Name</span>
          <span style={{ width: 60, textAlign: "right" }}>Calls</span>
          <span style={{ width: 90, textAlign: "right" }}>Input Tok</span>
          <span style={{ width: 90, textAlign: "right" }}>Output Tok</span>
          <span style={{ width: 80, textAlign: "right" }}>Cost</span>
        </div>
        {items.map((item, i) => (
          <div
            key={i}
            onClick={() => onClickItem?.(item.label)}
            style={{
              display: "flex", flexDirection: "row",
              gap: 12,
              padding: "7px 12px",
              fontSize: 12,
              borderBottom: i < items.length - 1 ? `1px solid ${t.surfaceRaised}` : "none",
              alignItems: "center",
              cursor: onClickItem ? "pointer" : "default",
            }}
            onMouseEnter={(e) => {
              if (onClickItem) (e.currentTarget as HTMLElement).style.background = t.surfaceRaised;
            }}
            onMouseLeave={(e) => {
              if (onClickItem) (e.currentTarget as HTMLElement).style.background = "";
            }}
          >
            <span
              style={{
                flex: 1,
                minWidth: 0,
                color: onClickItem ? t.accent : t.text,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {item.label}
              {!item.has_cost_data && (
                <span style={{ color: t.warning, fontSize: 10, marginLeft: 6 }}>no pricing</span>
              )}
            </span>
            <span style={{ width: 60, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
              {item.calls}
            </span>
            <span style={{ width: 90, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
              {fmtTokens(item.prompt_tokens)}
            </span>
            <span style={{ width: 90, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}>
              {fmtTokens(item.completion_tokens)}
            </span>
            <span style={{ width: 80, textAlign: "right", color: t.text, fontFamily: "monospace" }}>
              {fmtCost(item.cost)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------
export function OverviewTab({
  params,
  onDrillDown,
}: {
  params: UsageParams;
  onDrillDown: (filter: { model?: string; bot_id?: string; provider_id?: string }) => void;
}) {
  const t = useThemeTokens();
  const { data, isLoading } = useUsageSummary(params);
  const { data: forecast } = useUsageForecast();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center" style={{ padding: 40 }}>
        <Spinner />
      </div>
    );
  }
  if (!data) return null;

  const avgCost =
    data.total_cost != null && data.total_calls > 0
      ? data.total_cost / data.total_calls
      : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Forecast: limit warnings + spend summary */}
      {forecast && <LimitAlerts limits={forecast.limits} />}
      {forecast && <ForecastCards forecast={forecast} />}

      {/* Stat cards */}
      <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
        <StatCard label="Total Calls" value={fmtTokens(data.total_calls)} />
        <StatCard
          label="Total Tokens"
          value={fmtTokens(data.total_tokens)}
          sub={`${fmtTokens(data.total_prompt_tokens)} in / ${fmtTokens(data.total_completion_tokens)} out`}
        />
        <StatCard label="Total Cost" value={fmtCost(data.total_cost)} />
        <StatCard label="Avg Cost/Call" value={fmtCost(avgCost)} />
      </div>

      {/* Missing cost warning */}
      {data.models_without_cost_data.length > 0 && (
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "flex-start",
            gap: 8,
            padding: "10px 14px",
            background: t.warningSubtle,
            border: `1px solid ${t.warning}`,
            borderRadius: 8,
            fontSize: 12,
            color: t.warning,
          }}
        >
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <div>
            <strong>{data.calls_without_cost_data}</strong> call(s) across{" "}
            <strong>{data.models_without_cost_data.length}</strong> model(s) have no pricing
            data: {data.models_without_cost_data.join(", ")}.{" "}
            <a href="/admin/providers" style={{ color: t.warning, textDecoration: "underline" }}>
              Configure pricing
            </a>
          </div>
        </div>
      )}

      {/* Cost tables -- click to drill down into Logs */}
      <CostTable
        title="Cost by Model"
        items={data.cost_by_model}
        onClickItem={(label) => onDrillDown({ model: label })}
      />
      <CostTable
        title="Cost by Bot"
        items={data.cost_by_bot}
        onClickItem={(label) => onDrillDown({ bot_id: label })}
      />
      <CostTable
        title="Cost by Provider"
        items={data.cost_by_provider}
        onClickItem={(label) => onDrillDown({ provider_id: label === "default" ? undefined : label })}
      />
    </div>
  );
}
