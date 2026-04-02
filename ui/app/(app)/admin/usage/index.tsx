import { useState, useMemo } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { ChevronLeft, ChevronRight, AlertTriangle, X, ExternalLink, Eye, EyeOff } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useBots } from "@/src/api/hooks/useBots";
import {
  useUsageSummary,
  useUsageLogs,
  useUsageBreakdown,
  useUsageTimeSeries,
  type UsageParams,
  type CostByDimension,
  type UsageLogEntry,
} from "@/src/api/hooks/useUsage";
import { BarChart, LineChart } from "@/src/components/shared/SimpleCharts";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUsageForecast } from "@/src/api/hooks/useUsageForecast";
import { ForecastTab, LimitAlerts, ForecastCards } from "./ForecastSection";
import { LimitsTab } from "./LimitsTab";
import { useUsageHudStore } from "@/src/stores/usageHud";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const TIME_PRESETS: { label: string; value: string }[] = [
  { label: "1h", value: "1h" },
  { label: "12h", value: "12h" },
  { label: "24h", value: "24h" },
  { label: "48h", value: "48h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

const TABS = ["Overview", "Forecast", "Logs", "Charts", "Limits"] as const;
type Tab = (typeof TABS)[number];

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtBucketLabel(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

// ---------------------------------------------------------------------------
// Shared filter bar styles
// ---------------------------------------------------------------------------
function useSelectStyle(): React.CSSProperties {
  const t = useThemeTokens();
  return {
    background: t.surfaceRaised,
    color: t.textMuted,
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 6,
    padding: "5px 10px",
    fontSize: 12,
    outline: "none",
  };
}

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
              display: "flex",
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
function OverviewTab({
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
      <View className="items-center justify-center" style={{ padding: 40 }}>
        <ActivityIndicator color={t.accent} />
      </View>
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
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
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
            display: "flex",
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

      {/* Cost tables — click to drill down into Logs */}
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

// ---------------------------------------------------------------------------
// Logs tab — trace grouping + raw call view
// ---------------------------------------------------------------------------
interface TraceGroup {
  correlation_id: string;
  created_at: string;
  bot_id: string | null;
  bot_name: string | null;
  channel_name: string | null;
  entries: UsageLogEntry[];
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost: number | null;
  total_duration_ms: number | null;
  iterations: number;
  has_cost_data: boolean;
}

function groupByCorrelation(
  entries: UsageLogEntry[],
  bots: any[] | undefined,
): TraceGroup[] {
  const map = new Map<string, TraceGroup>();
  for (const entry of entries) {
    const key = entry.correlation_id || entry.id; // fallback if no correlation_id
    let group = map.get(key);
    if (!group) {
      const bot = bots?.find((b: any) => b.id === entry.bot_id);
      group = {
        correlation_id: key,
        created_at: entry.created_at,
        bot_id: entry.bot_id,
        bot_name: bot?.name || entry.bot_id || null,
        channel_name: entry.channel_name,
        entries: [],
        total_prompt_tokens: 0,
        total_completion_tokens: 0,
        total_cost: null,
        total_duration_ms: null,
        iterations: 0,
        has_cost_data: true,
      };
      map.set(key, group);
    }
    group.entries.push(entry);
    group.total_prompt_tokens += entry.prompt_tokens;
    group.total_completion_tokens += entry.completion_tokens;
    group.iterations += 1;
    if (entry.cost != null) {
      group.total_cost = (group.total_cost || 0) + entry.cost;
    } else {
      group.has_cost_data = false;
    }
    if (entry.duration_ms != null) {
      group.total_duration_ms = (group.total_duration_ms || 0) + entry.duration_ms;
    }
  }
  return Array.from(map.values());
}

function LogsTab({ params }: { params: UsageParams }) {
  const router = useRouter();
  const t = useThemeTokens();
  const [page, setPage] = useState(1);
  const [viewMode, setViewMode] = useState<"traces" | "raw">("traces");
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const { data, isLoading } = useUsageLogs({ ...params, page, page_size: 100 });
  const { data: bots } = useBots();

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;
  const traceGroups = useMemo(
    () => (data ? groupByCorrelation(data.entries, bots) : []),
    [data, bots],
  );

  if (isLoading) {
    return (
      <View className="items-center justify-center" style={{ padding: 40 }}>
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* View mode toggle */}
      <div
        style={{
          display: "flex",
          gap: 4,
          padding: "6px 12px",
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 11, color: t.textDim, marginRight: 8 }}>View:</span>
        {(["traces", "raw"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => setViewMode(mode)}
            style={{
              padding: "3px 10px",
              fontSize: 11,
              fontWeight: viewMode === mode ? 600 : 400,
              background: viewMode === mode ? t.accent : "transparent",
              color: viewMode === mode ? "#fff" : t.textMuted,
              border: `1px solid ${viewMode === mode ? t.accent : t.surfaceBorder}`,
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            {mode === "traces" ? "By Trace" : "Raw Calls"}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: t.textDim }}>
          {data?.total ?? 0} calls{viewMode === "traces" ? `, ${traceGroups.length} traces` : ""}
        </span>
      </div>

      {viewMode === "traces" ? (
        <>
          {/* Trace view — grouped by correlation_id */}
          <div
            style={{
              display: "flex",
              gap: 8,
              padding: "6px 12px",
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              textTransform: "uppercase",
              borderBottom: `1px solid ${t.surfaceOverlay}`,
            }}
          >
            <span style={{ width: 120 }}>Time</span>
            <span style={{ width: 100 }}>Bot</span>
            <span style={{ width: 100 }}>Channel</span>
            <span style={{ width: 50, textAlign: "right" }}>Iters</span>
            <span style={{ flex: 1, minWidth: 0, textAlign: "right" }}>Input Tok</span>
            <span style={{ width: 90, textAlign: "right" }}>Output Tok</span>
            <span style={{ width: 80, textAlign: "right" }}>Cost</span>
            <span style={{ width: 70, textAlign: "right" }}>LLM Time</span>
          </div>
          {traceGroups.map((group) => (
            <div key={group.correlation_id}>
              <div
                onClick={() =>
                  setExpandedTrace(
                    expandedTrace === group.correlation_id ? null : group.correlation_id,
                  )
                }
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "7px 12px",
                  fontSize: 12,
                  borderBottom: `1px solid ${t.surfaceRaised}`,
                  alignItems: "center",
                  cursor: "pointer",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLElement).style.background = t.surfaceRaised)
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLElement).style.background = "")
                }
              >
                <span style={{ width: 120, color: t.textDim, fontSize: 11 }}>
                  {fmtDate(group.created_at)} {fmtTime(group.created_at)}
                </span>
                <span
                  style={{
                    width: 100,
                    color: t.textMuted,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {group.bot_name || "--"}
                </span>
                <span
                  style={{
                    width: 100,
                    color: t.textMuted,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {group.channel_name || "--"}
                </span>
                <span
                  style={{ width: 50, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}
                >
                  {group.iterations}
                </span>
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    textAlign: "right",
                    color: t.textMuted,
                    fontFamily: "monospace",
                  }}
                >
                  {fmtTokens(group.total_prompt_tokens)}
                </span>
                <span
                  style={{ width: 90, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}
                >
                  {fmtTokens(group.total_completion_tokens)}
                </span>
                <span
                  style={{
                    width: 80,
                    textAlign: "right",
                    fontFamily: "monospace",
                    fontWeight: 600,
                    color: group.has_cost_data ? t.text : t.warning,
                  }}
                >
                  {group.has_cost_data ? fmtCost(group.total_cost) : "--"}
                </span>
                <span
                  style={{ width: 70, textAlign: "right", color: t.textDim, fontFamily: "monospace" }}
                >
                  {fmtDuration(group.total_duration_ms)}
                </span>
              </div>

              {/* Expanded: show individual LLM calls */}
              {expandedTrace === group.correlation_id && (
                <div style={{ background: t.surfaceRaised, borderBottom: `1px solid ${t.surfaceOverlay}` }}>
                  {group.entries.map((entry, idx) => (
                    <div
                      key={entry.id}
                      style={{
                        display: "flex",
                        gap: 8,
                        padding: "5px 12px 5px 28px",
                        fontSize: 11,
                        alignItems: "center",
                        borderBottom:
                          idx < group.entries.length - 1
                            ? `1px solid ${t.surfaceOverlay}`
                            : "none",
                      }}
                    >
                      <span style={{ width: 106, color: t.textDim, fontSize: 10 }}>
                        iter {idx + 1}
                      </span>
                      <span
                        style={{
                          flex: 1,
                          minWidth: 0,
                          color: t.textMuted,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {entry.model || "--"}
                        {entry.provider_name && (
                          <span style={{ color: t.textDim, fontSize: 9, marginLeft: 4 }}>
                            ({entry.provider_name})
                          </span>
                        )}
                      </span>
                      <span
                        style={{
                          width: 80,
                          textAlign: "right",
                          color: t.textDim,
                          fontFamily: "monospace",
                        }}
                      >
                        {fmtTokens(entry.prompt_tokens)}
                      </span>
                      <span
                        style={{
                          width: 80,
                          textAlign: "right",
                          color: t.textDim,
                          fontFamily: "monospace",
                        }}
                      >
                        {fmtTokens(entry.completion_tokens)}
                      </span>
                      <span
                        style={{
                          width: 70,
                          textAlign: "right",
                          fontFamily: "monospace",
                          color: entry.has_cost_data ? t.textMuted : t.warning,
                          fontSize: 10,
                        }}
                      >
                        {entry.has_cost_data ? fmtCost(entry.cost) : "--"}
                      </span>
                      <span
                        style={{
                          width: 60,
                          textAlign: "right",
                          color: t.textDim,
                          fontFamily: "monospace",
                          fontSize: 10,
                        }}
                      >
                        {fmtDuration(entry.duration_ms)}
                      </span>
                    </div>
                  ))}
                  {/* View full trace link */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      router.push(`/admin/logs/${group.correlation_id}` as any);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 12px 6px 28px",
                      fontSize: 11,
                      color: t.accent,
                      cursor: "pointer",
                      borderTop: `1px solid ${t.surfaceOverlay}`,
                    }}
                    onMouseEnter={(e) =>
                      ((e.currentTarget as HTMLElement).style.textDecoration = "underline")
                    }
                    onMouseLeave={(e) =>
                      ((e.currentTarget as HTMLElement).style.textDecoration = "none")
                    }
                  >
                    <ExternalLink size={12} /> View full trace
                  </div>
                </div>
              )}
            </div>
          ))}
        </>
      ) : (
        <>
          {/* Raw call view */}
          <div
            style={{
              display: "flex",
              gap: 8,
              padding: "6px 12px",
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              textTransform: "uppercase",
              borderBottom: `1px solid ${t.surfaceOverlay}`,
            }}
          >
            <span style={{ width: 120 }}>Time</span>
            <span style={{ flex: 1, minWidth: 0 }}>Model</span>
            <span style={{ width: 80 }}>Bot</span>
            <span style={{ width: 100 }}>Channel</span>
            <span style={{ width: 80, textAlign: "right" }}>Input</span>
            <span style={{ width: 80, textAlign: "right" }}>Output</span>
            <span style={{ width: 80, textAlign: "right" }}>Cost</span>
            <span style={{ width: 70, textAlign: "right" }}>Duration</span>
          </div>

          {data?.entries.map((entry) => {
            const bot = bots?.find((b: any) => b.id === entry.bot_id);
            return (
              <div
                key={entry.id}
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "6px 12px",
                  fontSize: 12,
                  borderBottom: `1px solid ${t.surfaceRaised}`,
                  alignItems: "center",
                }}
              >
                <span style={{ width: 120, color: t.textDim, fontSize: 11 }}>
                  {fmtDate(entry.created_at)} {fmtTime(entry.created_at)}
                </span>
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    color: t.text,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {entry.model || "--"}
                  {entry.provider_name && (
                    <span style={{ color: t.textDim, fontSize: 10, marginLeft: 6 }}>
                      ({entry.provider_name})
                    </span>
                  )}
                </span>
                <span
                  style={{
                    width: 80,
                    color: t.textMuted,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {bot?.name || entry.bot_id || "--"}
                </span>
                <span
                  style={{
                    width: 100,
                    color: t.textMuted,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {entry.channel_name || "--"}
                </span>
                <span
                  style={{ width: 80, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}
                >
                  {fmtTokens(entry.prompt_tokens)}
                </span>
                <span
                  style={{ width: 80, textAlign: "right", color: t.textMuted, fontFamily: "monospace" }}
                >
                  {fmtTokens(entry.completion_tokens)}
                </span>
                <span
                  style={{
                    width: 80,
                    textAlign: "right",
                    fontFamily: "monospace",
                    color: entry.has_cost_data ? t.text : t.warning,
                  }}
                >
                  {entry.has_cost_data ? fmtCost(entry.cost) : "--"}
                </span>
                <span
                  style={{ width: 70, textAlign: "right", color: t.textDim, fontFamily: "monospace" }}
                >
                  {fmtDuration(entry.duration_ms)}
                </span>
              </div>
            );
          })}
        </>
      )}

      {data?.entries.length === 0 && (
        <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
          No usage data found.
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 12,
            padding: "10px 20px",
            borderTop: `1px solid ${t.surfaceOverlay}`,
          }}
        >
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            style={{
              background: "none",
              border: "none",
              cursor: page <= 1 ? "default" : "pointer",
              color: page <= 1 ? t.surfaceBorder : t.textMuted,
              padding: 4,
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontSize: 12, color: t.textDim }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            style={{
              background: "none",
              border: "none",
              cursor: page >= totalPages ? "default" : "pointer",
              color: page >= totalPages ? t.surfaceBorder : t.textMuted,
              padding: 4,
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Charts tab
// ---------------------------------------------------------------------------
function ChartsTab({ params }: { params: UsageParams }) {
  const t = useThemeTokens();
  const { data: breakdown, isLoading: breakdownLoading } = useUsageBreakdown({
    ...params,
    group_by: "model",
  });
  const { data: timeseries, isLoading: tsLoading } = useUsageTimeSeries(params);

  if (breakdownLoading || tsLoading) {
    return (
      <View className="items-center justify-center" style={{ padding: 40 }}>
        <ActivityIndicator color={t.accent} />
      </View>
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

// ---------------------------------------------------------------------------
// Sidebar HUD toggle
// ---------------------------------------------------------------------------
function HudToggle() {
  const t = useThemeTokens();
  const enabled = useUsageHudStore((s) => s.enabled);
  const setEnabled = useUsageHudStore((s) => s.setEnabled);
  return (
    <button
      onClick={() => setEnabled(!enabled)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 5,
        padding: "4px 10px",
        fontSize: 11,
        background: "transparent",
        color: t.textDim,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 4,
        cursor: "pointer",
      }}
      title={enabled ? "Hide usage badge in sidebar" : "Show usage badge in sidebar"}
    >
      {enabled ? <Eye size={12} /> : <EyeOff size={12} />}
      Sidebar HUD
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function UsageScreen() {
  const t = useThemeTokens();
  const selectStyle = useSelectStyle();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  const [tab, setTab] = useHashTab<Tab>("Overview", TABS);
  const [timePreset, setTimePreset] = useState("24h");
  const [botFilter, setBotFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");

  // Drill-down from Overview cost tables → Logs tab
  const handleDrillDown = (filter: { model?: string; bot_id?: string; provider_id?: string }) => {
    if (filter.model) setModelFilter(filter.model);
    if (filter.bot_id) setBotFilter(filter.bot_id);
    if (filter.provider_id) setProviderFilter(filter.provider_id);
    setTab("Logs");
  };

  const { data: bots } = useBots();

  // Fetch unfiltered summary for the time range to populate filter dropdowns
  const { data: summaryForFilters } = useUsageSummary({ after: timePreset });

  // Derive dropdown options from the unfiltered summary
  const modelNames = useMemo(
    () => (summaryForFilters?.cost_by_model || []).map((m) => m.label).sort(),
    [summaryForFilters],
  );
  const providerIds = useMemo(
    () => (summaryForFilters?.cost_by_provider || []).map((p) => p.label).filter((p) => p !== "default").sort(),
    [summaryForFilters],
  );

  const params: UsageParams = useMemo(() => ({
    after: timePreset,
    ...(botFilter ? { bot_id: botFilter } : {}),
    ...(modelFilter ? { model: modelFilter } : {}),
    ...(providerFilter ? { provider_id: providerFilter } : {}),
  }), [timePreset, botFilter, modelFilter, providerFilter]);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Usage & Costs" subtitle="LLM cost analytics" />

      {/* Filter bar — only shown on tabs that use time/filter params */}
      {tab !== "Forecast" && tab !== "Limits" && (
        <div
          style={{
            display: "flex",
            gap: 8,
            padding: isMobile ? "8px 12px" : "10px 20px",
            borderBottom: `1px solid ${t.surfaceRaised}`,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          {/* Time presets */}
          <div style={{ display: "flex", gap: 2 }}>
            {TIME_PRESETS.map((p) => (
              <button
                key={p.value}
                onClick={() => setTimePreset(p.value)}
                style={{
                  padding: "4px 10px",
                  fontSize: 12,
                  fontWeight: timePreset === p.value ? 600 : 400,
                  background: timePreset === p.value ? t.accent : t.surfaceRaised,
                  color: timePreset === p.value ? "#fff" : t.textMuted,
                  border: `1px solid ${timePreset === p.value ? t.accent : t.surfaceBorder}`,
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Bot filter */}
          <select
            value={botFilter}
            onChange={(e) => setBotFilter(e.target.value)}
            style={selectStyle}
          >
            <option value="">All Bots</option>
            {bots?.map((b: any) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>

          {/* Model filter */}
          <select
            value={modelFilter}
            onChange={(e) => setModelFilter(e.target.value)}
            style={selectStyle}
          >
            <option value="">All Models</option>
            {modelNames.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>

          {/* Provider filter */}
          <select
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            style={selectStyle}
          >
            <option value="">All Providers</option>
            {providerIds.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>

          {/* Clear filters button */}
          {(botFilter || modelFilter || providerFilter) && (
            <button
              onClick={() => {
                setBotFilter("");
                setModelFilter("");
                setProviderFilter("");
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                padding: "4px 10px",
                fontSize: 11,
                background: t.accentSubtle,
                color: t.accent,
                border: `1px solid ${t.accent}`,
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              <X size={12} /> Clear filters
            </button>
          )}

          {/* Spacer + HUD toggle */}
          <div style={{ flex: 1 }} />
          <HudToggle />
        </div>
      )}

      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          padding: isMobile ? "0 12px" : "0 20px",
        }}
      >
        {TABS.map((tabName) => (
          <button
            key={tabName}
            onClick={() => setTab(tabName)}
            style={{
              padding: "10px 16px",
              fontSize: 13,
              fontWeight: tab === tabName ? 600 : 400,
              color: tab === tabName ? t.accent : t.textMuted,
              background: "none",
              border: "none",
              borderBottom: tab === tabName ? `2px solid ${t.accent}` : "2px solid transparent",
              cursor: "pointer",
            }}
          >
            {tabName}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        <div style={{ padding: isMobile ? 12 : 20 }}>
          {tab === "Overview" && <OverviewTab params={params} onDrillDown={handleDrillDown} />}
          {tab === "Forecast" && <ForecastTab />}
          {tab === "Logs" && <LogsTab params={params} />}
          {tab === "Charts" && <ChartsTab params={params} />}
          {tab === "Limits" && <LimitsTab knownModels={modelNames} />}
        </div>
      </RefreshableScrollView>
    </View>
  );
}
