import { useMemo, useState } from "react";
import { Eye, EyeOff, Filter, X } from "lucide-react";

import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useUsageSummary, type UsageParams } from "@/src/api/hooks/useUsage";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { ActionButton, SettingsSegmentedControl } from "@/src/components/shared/SettingsControls";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { SelectDropdown, type SelectDropdownOption } from "@/src/components/shared/SelectDropdown";
import { useHashTab } from "@/src/hooks/useHashTab";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { openTraceInspector } from "@/src/stores/traceInspector";
import { useUsageHudStore } from "@/src/stores/usageHud";
import { AlertsTab } from "./AlertsTab";
import { ForecastTab } from "./ForecastSection";
import { LimitsTab } from "./LimitsTab";
import { ProviderHealthTab } from "./ProviderHealthTab";
import { ChartsTab } from "./UsageCharts";
import { LogsTab } from "./UsageLogs";
import { OverviewTab } from "./UsageOverview";
import { TABS, TIME_PRESETS, type Tab } from "./usageUtils";

const SOURCE_OPTIONS: SelectDropdownOption[] = [
  { value: "", label: "All sources" },
  { value: "agent", label: "Agent" },
  { value: "task", label: "Task" },
  { value: "heartbeat", label: "Heartbeat" },
  { value: "maintenance", label: "Maintenance" },
];

function HudToggle() {
  const enabled = useUsageHudStore((state) => state.enabled);
  const setEnabled = useUsageHudStore((state) => state.setEnabled);
  return (
    <ActionButton
      label="Sidebar HUD"
      variant="ghost"
      size="small"
      icon={enabled ? <Eye size={13} /> : <EyeOff size={13} />}
      onPress={() => setEnabled(!enabled)}
    />
  );
}

function compactOptions(values: string[], allLabel: string): SelectDropdownOption[] {
  return [
    { value: "", label: allLabel },
    ...values.map((value) => ({ value, label: value, searchText: value })),
  ];
}

function FilterBar({
  timePreset,
  setTimePreset,
  botFilter,
  setBotFilter,
  modelFilter,
  setModelFilter,
  providerFilter,
  setProviderFilter,
  channelFilter,
  setChannelFilter,
  sourceFilter,
  setSourceFilter,
  modelNames,
  providerIds,
}: {
  timePreset: string;
  setTimePreset: (value: string) => void;
  botFilter: string;
  setBotFilter: (value: string) => void;
  modelFilter: string;
  setModelFilter: (value: string) => void;
  providerFilter: string;
  setProviderFilter: (value: string) => void;
  channelFilter: string;
  setChannelFilter: (value: string) => void;
  sourceFilter: string;
  setSourceFilter: (value: string) => void;
  modelNames: string[];
  providerIds: string[];
}) {
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const botOptions = useMemo<SelectDropdownOption[]>(
    () => [
      { value: "", label: "All bots" },
      ...(bots ?? []).map((bot: any) => ({
        value: bot.id,
        label: bot.name || bot.id,
        description: bot.id,
        searchText: `${bot.name || ""} ${bot.id}`,
      })),
    ],
    [bots],
  );
  const channelOptions = useMemo<SelectDropdownOption[]>(
    () => [
      { value: "", label: "All channels" },
      ...(channels ?? []).map((channel: any) => ({
        value: channel.id,
        label: channel.name || channel.id,
        description: channel.category || channel.id,
        searchText: `${channel.name || ""} ${channel.category || ""} ${channel.id}`,
      })),
    ],
    [channels],
  );
  const hasFilters = botFilter || modelFilter || providerFilter || channelFilter || sourceFilter;

  return (
    <div className="border-b border-surface-overlay/45 px-4 py-3 lg:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <SettingsSegmentedControl
          value={timePreset}
          onChange={setTimePreset}
          options={TIME_PRESETS.map((preset) => ({ value: preset.value, label: preset.label }))}
        />
        <div className="min-w-[150px]">
          <SelectDropdown value={botFilter} options={botOptions} onChange={setBotFilter} searchable size="sm" />
        </div>
        <div className="min-w-[170px]">
          <SelectDropdown value={channelFilter} options={channelOptions} onChange={setChannelFilter} searchable size="sm" />
        </div>
        <div className="min-w-[170px]">
          <SelectDropdown value={modelFilter} options={compactOptions(modelNames, "All models")} onChange={setModelFilter} searchable size="sm" />
        </div>
        <div className="min-w-[150px]">
          <SelectDropdown value={providerFilter} options={compactOptions(providerIds, "All providers")} onChange={setProviderFilter} searchable size="sm" />
        </div>
        <div className="min-w-[150px]">
          <SelectDropdown value={sourceFilter} options={SOURCE_OPTIONS} onChange={setSourceFilter} size="sm" leadingIcon={<Filter size={13} />} />
        </div>
        {hasFilters && (
          <ActionButton
            label="Clear"
            variant="ghost"
            size="small"
            icon={<X size={13} />}
            onPress={() => {
              setBotFilter("");
              setModelFilter("");
              setProviderFilter("");
              setChannelFilter("");
              setSourceFilter("");
            }}
          />
        )}
        <div className="ml-auto">
          <HudToggle />
        </div>
      </div>
    </div>
  );
}

export default function UsageScreen() {
  const { refreshing, onRefresh } = usePageRefresh();
  const [tab, setTab] = useHashTab<Tab>("Overview", TABS);
  const [timePreset, setTimePreset] = useState("24h");
  const [botFilter, setBotFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");

  const { data: summaryForFilters } = useUsageSummary({ after: timePreset });
  const modelNames = useMemo(
    () => (summaryForFilters?.cost_by_model || []).map((model) => model.label).sort(),
    [summaryForFilters],
  );
  const providerIds = useMemo(
    () => (summaryForFilters?.cost_by_provider || []).map((provider) => provider.label).filter((provider) => provider !== "default").sort(),
    [summaryForFilters],
  );
  const params: UsageParams = useMemo(() => ({
    after: timePreset,
    ...(botFilter ? { bot_id: botFilter } : {}),
    ...(modelFilter ? { model: modelFilter } : {}),
    ...(providerFilter ? { provider_id: providerFilter } : {}),
    ...(channelFilter ? { channel_id: channelFilter } : {}),
    ...(sourceFilter ? { source_type: sourceFilter } : {}),
  }), [timePreset, botFilter, modelFilter, providerFilter, channelFilter, sourceFilter]);

  const handleDrillDown = (filter: { model?: string; bot_id?: string; provider_id?: string }) => {
    if (filter.model) setModelFilter(filter.model);
    if (filter.bot_id) setBotFilter(filter.bot_id);
    if (filter.provider_id) setProviderFilter(filter.provider_id);
    setTab("Logs");
  };
  const showFilters = tab === "Overview" || tab === "Logs" || tab === "Trends";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Usage"
        subtitle="Spot anomalies, attribute spend, and inspect the traces behind token movement."
      />

      <div className="border-b border-surface-overlay/45 px-4 py-2 lg:px-6">
        <SettingsSegmentedControl
          value={tab}
          onChange={setTab}
          options={TABS.map((name) => ({ value: name, label: name }))}
        />
      </div>

      {showFilters && (
        <FilterBar
          timePreset={timePreset}
          setTimePreset={setTimePreset}
          botFilter={botFilter}
          setBotFilter={setBotFilter}
          modelFilter={modelFilter}
          setModelFilter={setModelFilter}
          providerFilter={providerFilter}
          setProviderFilter={setProviderFilter}
          channelFilter={channelFilter}
          setChannelFilter={setChannelFilter}
          sourceFilter={sourceFilter}
          setSourceFilter={setSourceFilter}
          modelNames={modelNames}
          providerIds={providerIds}
        />
      )}

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="min-h-0 flex-1">
        <div className="p-4 lg:p-6">
          {tab === "Overview" && <OverviewTab params={params} onDrillDown={handleDrillDown} onSelectTrace={openTraceInspector} />}
          {tab === "Logs" && <LogsTab params={params} onSelectTrace={openTraceInspector} />}
          {tab === "Trends" && <ChartsTab params={params} />}
          {tab === "Forecast" && <ForecastTab />}
          {tab === "Limits" && <LimitsTab knownModels={modelNames} />}
          {tab === "Alerts" && <AlertsTab />}
          {tab === "Providers" && <ProviderHealthTab />}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
