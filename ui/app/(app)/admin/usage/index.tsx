import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useMemo } from "react";
import { useHashTab } from "@/src/hooks/useHashTab";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { X, Eye, EyeOff } from "lucide-react";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useBots } from "@/src/api/hooks/useBots";
import { useUsageSummary, type UsageParams } from "@/src/api/hooks/useUsage";
import { useThemeTokens } from "@/src/theme/tokens";
import { ForecastTab } from "./ForecastSection";
import { LimitsTab } from "./LimitsTab";
import { AlertsTab } from "./AlertsTab";
import { useUsageHudStore } from "@/src/stores/usageHud";
import { TIME_PRESETS, TABS, type Tab, useSelectStyle } from "./usageUtils";
import { OverviewTab } from "./UsageOverview";
import { LogsTab } from "./UsageLogs";
import { ChartsTab } from "./UsageCharts";

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
        display: "flex", flexDirection: "row",
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
// Filter bar
// ---------------------------------------------------------------------------
function FilterBar({
  isMobile,
  timePreset,
  setTimePreset,
  botFilter,
  setBotFilter,
  modelFilter,
  setModelFilter,
  providerFilter,
  setProviderFilter,
  modelNames,
  providerIds,
}: {
  isMobile: boolean;
  timePreset: string;
  setTimePreset: (v: string) => void;
  botFilter: string;
  setBotFilter: (v: string) => void;
  modelFilter: string;
  setModelFilter: (v: string) => void;
  providerFilter: string;
  setProviderFilter: (v: string) => void;
  modelNames: string[];
  providerIds: string[];
}) {
  const t = useThemeTokens();
  const selectStyle = useSelectStyle();
  const { data: bots } = useBots();

  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        gap: 8,
        padding: isMobile ? "8px 12px" : "10px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      {/* Time presets */}
      <div style={{ display: "flex", flexDirection: "row", gap: 2 }}>
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
            display: "flex", flexDirection: "row",
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
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function UsageScreen() {
  const t = useThemeTokens();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isMobile = width < 768;

  const [tab, setTab] = useHashTab<Tab>("Overview", TABS);
  const [timePreset, setTimePreset] = useState("24h");
  const [botFilter, setBotFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");

  // Drill-down from Overview cost tables -> Logs tab
  const handleDrillDown = (filter: { model?: string; bot_id?: string; provider_id?: string }) => {
    if (filter.model) setModelFilter(filter.model);
    if (filter.bot_id) setBotFilter(filter.bot_id);
    if (filter.provider_id) setProviderFilter(filter.provider_id);
    setTab("Logs");
  };

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
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Usage & Costs" subtitle="LLM cost analytics" />

      {/* Filter bar -- only shown on tabs that use time/filter params */}
      {tab !== "Forecast" && tab !== "Limits" && tab !== "Alerts" && (
        <FilterBar
          isMobile={isMobile}
          timePreset={timePreset}
          setTimePreset={setTimePreset}
          botFilter={botFilter}
          setBotFilter={setBotFilter}
          modelFilter={modelFilter}
          setModelFilter={setModelFilter}
          providerFilter={providerFilter}
          setProviderFilter={setProviderFilter}
          modelNames={modelNames}
          providerIds={providerIds}
        />
      )}

      {/* Tab bar */}
      <div
        style={{
          display: "flex", flexDirection: "row",
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
          {tab === "Alerts" && <AlertsTab />}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
