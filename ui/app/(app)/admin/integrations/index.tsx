import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Circle,
  LayoutDashboard,
  Mail,
  MessageCircle,
  MessageSquare,
  Mic,
  PenTool,
  Play,
  Plug,
  Plus,
  RefreshCw,
  Rss,
  Search,
  Square,
  Terminal,
  Tv,
  X,
  Camera,
  Cloud,
  Code2,
  Globe,
} from "lucide-react";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  ActionButton,
  EmptyState,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsSegmentedControl,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { useHashTab } from "@/src/hooks/useHashTab";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import {
  useIntegrations,
  useRestartProcess,
  useSetIntegrationStatus,
  useStartProcess,
  useStopProcess,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { CapBadge, formatUptime } from "./components";
import { IntegrationGuideModal } from "./IntegrationGuideModal";

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Tv,
  MessageCircle,
  Terminal,
  MessageSquare,
  PenTool,
  Globe,
  Camera,
  Code2,
  Cloud,
  Rss,
  LayoutDashboard,
  Mail,
  Mic,
  Search,
  Plug,
  BookOpen,
};

function IntegrationIcon({ name, size = 18 }: { name?: string; size?: number }) {
  const Icon = (name && ICON_MAP[name]) || Plug;
  return <Icon size={size} className="text-text-muted" />;
}

function StatusDot({ item }: { item: IntegrationItem }) {
  const enabled = item.lifecycle_status === "enabled";
  const missingRequired = item.env_vars.some((v) => v.required && !v.is_set);
  const label = !enabled ? "Available" : missingRequired ? "Needs setup" : "Enabled";
  const dotClass = !enabled ? "bg-text-dim" : missingRequired ? "bg-warning" : "bg-success";
  const textClass = !enabled ? "text-text-dim" : missingRequired ? "text-warning-muted" : "text-success";
  return (
    <span className={`inline-flex items-center gap-1.5 text-[10px] font-semibold ${textClass}`}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
      {label}
    </span>
  );
}

function ProcessControls({ item }: { item: IntegrationItem }) {
  const startMut = useStartProcess(item.id);
  const stopMut = useStopProcess(item.id);
  const restartMut = useRestartProcess(item.id);
  const ps = item.process_status;
  const running = ps?.status === "running";
  const pending = startMut.isPending || stopMut.isPending || restartMut.isPending;

  const stop = (event: React.MouseEvent) => {
    event.stopPropagation();
    stopMut.mutate();
  };
  const restart = (event: React.MouseEvent) => {
    event.stopPropagation();
    restartMut.mutate();
  };
  const start = (event: React.MouseEvent) => {
    event.stopPropagation();
    startMut.mutate();
  };

  return (
    <div className="mt-2 flex min-h-[28px] items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${running ? "bg-success" : "bg-text-dim"}`} />
      <span className={`text-[10px] font-semibold ${running ? "text-success" : "text-text-dim"}`}>
        {running ? "Running" : "Stopped"}
      </span>
      {running && ps?.uptime_seconds != null && (
        <span className="text-[9px] text-text-dim">{formatUptime(ps.uptime_seconds)}</span>
      )}
      <div className="flex-1" />
      {running ? (
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={stop}
            disabled={pending}
            title="Stop"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-danger transition-colors hover:bg-danger/10 disabled:opacity-50"
          >
            <Square size={11} />
          </button>
          <button
            type="button"
            onClick={restart}
            disabled={pending}
            title="Restart"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-accent transition-colors hover:bg-accent/[0.08] disabled:opacity-50"
          >
            <RefreshCw size={11} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={start}
          disabled={pending}
          title="Start"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-success transition-colors hover:bg-success/10 disabled:opacity-50"
        >
          <Play size={11} />
        </button>
      )}
    </div>
  );
}

function IntegrationCard({ item }: { item: IntegrationItem }) {
  const navigate = useNavigate();
  const statusMut = useSetIntegrationStatus(item.id);
  const envSetCount = item.env_vars.filter((v) => v.is_set).length;
  const envTotal = item.env_vars.length;
  const allEnvSet = envTotal > 0 && envSetCount === envTotal;
  const missingRequired = item.env_vars.some((v) => v.required && !v.is_set);
  const activeCaps = [
    item.has_router && "router",
    item.has_hooks && "hooks",
    item.has_tools && "tools",
    item.has_skills && "skills",
    item.has_tool_widgets && "widgets",
    item.has_process && "process",
    item.machine_control && "machines",
  ].filter(Boolean) as string[];
  const available = item.lifecycle_status === "available";
  const runnable = item.lifecycle_status === "enabled";

  const onAdd = (event: React.MouseEvent) => {
    event.stopPropagation();
    statusMut.mutate("enabled");
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => navigate(`/admin/integrations/${item.id}`)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          navigate(`/admin/integrations/${item.id}`);
        }
      }}
      className={
        `flex w-full flex-col rounded-md bg-surface-raised/40 px-3 py-3 text-left transition-colors ` +
        `hover:bg-surface-overlay/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 ` +
        (available ? "opacity-75" : "")
      }
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-overlay/45">
          <IntegrationIcon name={item.icon} size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-text">{item.name}</div>
          <StatusDot item={item} />
          {item.description && (
            <div className="mt-1 line-clamp-2 text-[11px] leading-snug text-text-dim">{item.description}</div>
          )}
        </div>
        {!available && envTotal > 0 && (
          <span
            className={
              `inline-flex shrink-0 items-center gap-1 text-[10px] font-semibold tabular-nums ` +
              (allEnvSet ? "text-success" : missingRequired ? "text-warning-muted" : "text-text-dim")
            }
          >
            {allEnvSet ? <CheckCircle2 size={10} /> : missingRequired ? <AlertTriangle size={10} /> : null}
            {envSetCount}/{envTotal}
          </span>
        )}
        {available && (
          <button
            type="button"
            onClick={onAdd}
            className="inline-flex min-h-[30px] shrink-0 items-center gap-1 rounded-md px-2 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
          >
            <Plus size={11} />
            Add
          </button>
        )}
      </div>

      {activeCaps.length > 0 && !available && (
        <div className="mt-2 flex flex-wrap gap-1">
          {activeCaps.map((cap) => <CapBadge key={cap} label={cap} active />)}
        </div>
      )}

      {item.has_process && runnable && <ProcessControls item={item} />}
    </div>
  );
}

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "card"; key: string; item: IntegrationItem };

const TAB_KEYS = ["active", "library"] as const;
type TabKey = (typeof TAB_KEYS)[number];

export default function IntegrationsScreen() {
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const [search, setSearch] = useState("");
  const [showGuide, setShowGuide] = useState(false);
  const [activeTab, setActiveTab] = useHashTab<TabKey>("active", TAB_KEYS);

  const all = useMemo(() => {
    if (!data?.integrations) return undefined;
    return [...new Map(data.integrations.map((integration) => [integration.id, integration])).values()];
  }, [data]);

  const activeCount = all?.filter((integration) => integration.lifecycle_status !== "available").length ?? 0;
  const libraryCount = all?.filter((integration) => integration.lifecycle_status === "available").length ?? 0;

  const filtered = useMemo(() => {
    if (!all) return [];
    const q = search.toLowerCase().trim();
    const scoped = all.filter((integration) =>
      activeTab === "active"
        ? integration.lifecycle_status !== "available"
        : integration.lifecycle_status === "available",
    );
    if (!q) return scoped;
    return scoped.filter((integration) =>
      `${integration.name} ${integration.id}`.toLowerCase().includes(q),
    );
  }, [all, search, activeTab]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];
    if (activeTab === "library") {
      return filtered.map((integration) => ({ type: "card", key: integration.id, item: integration }));
    }

    const needsSetup: IntegrationItem[] = [];
    const ready: IntegrationItem[] = [];
    for (const integration of filtered) {
      if (integration.lifecycle_status !== "enabled") continue;
      const missingRequired = integration.env_vars.some((envVar) => envVar.required && !envVar.is_set);
      if (missingRequired) needsSetup.push(integration);
      else ready.push(integration);
    }

    const items: RenderItem[] = [];
    const add = (key: string, label: string, list: IntegrationItem[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const integration of list) items.push({ type: "card", key: integration.id, item: integration });
    };

    add("needs-setup", "Needs Setup", needsSetup);
    add("ready", "Ready", ready);
    return items;
  }, [filtered, activeTab]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader variant="list" title="Integrations" subtitle="Adopt, configure, and inspect integration surfaces." />

      <div className="flex flex-col gap-3 px-4 pb-3 pt-2 md:px-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <SettingsSegmentedControl
            value={activeTab}
            onChange={setActiveTab}
            options={[
              { value: "active", label: "Active", count: activeCount },
              { value: "library", label: "Library", count: libraryCount },
            ]}
          />
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            {all && all.length > 0 && (
              <SettingsSearchBox
                value={search}
                onChange={setSearch}
                placeholder="Filter integrations..."
                className="sm:w-72"
              />
            )}
            <ActionButton
              label="Dev Guide"
              onPress={() => setShowGuide(true)}
              variant="secondary"
              size="small"
              icon={<BookOpen size={13} />}
            />
          </div>
        </div>
      </div>

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="min-h-0 flex-1">
        <div className="flex flex-col gap-4 px-4 pb-8 md:px-6">
          {(!all || all.length === 0) && <EmptyState message="No integrations discovered." />}
          {all && all.length > 0 && filtered.length === 0 && (
            <EmptyState
              message={
                search
                  ? `No integrations match "${search}".`
                  : activeTab === "active"
                    ? "No integrations adopted yet. Browse the Library tab to add one."
                    : "No available integrations. Everything has been adopted."
              }
            />
          )}

          <div className="grid gap-2 md:grid-cols-[repeat(auto-fill,minmax(250px,1fr))]">
            {renderItems.map((item) =>
              item.type === "header" ? (
                <div key={item.key} className="col-span-full pt-2">
                  <SettingsGroupLabel label={item.label} count={item.count} icon={<Circle size={9} className="text-text-dim" />} />
                </div>
              ) : (
                <IntegrationCard key={item.key} item={item.item} />
              ),
            )}
          </div>
        </div>
      </RefreshableScrollView>

      {showGuide && <IntegrationGuideModal onClose={() => setShowGuide(false)} />}
    </div>
  );
}
