import { useState, useMemo } from "react";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useHashTab } from "@/src/hooks/useHashTab";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Search, Play, Square, RefreshCw, BookOpen, X, Plug, Plus,
  CheckCircle2, AlertTriangle,
  // Icon map for dynamic resolution
  Tv, MessageCircle, Terminal, MessageSquare, PenTool, Globe,
  Camera, Code2, Cloud, Rss, LayoutDashboard, Mail, Mic,
} from "lucide-react";
import { IntegrationGuideModal } from "./IntegrationGuideModal";
import {
  useIntegrations,
  useStartProcess,
  useStopProcess,
  useRestartProcess,
  useSetIntegrationStatus,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { CapBadge, formatUptime } from "./components";

/* ------------------------------------------------------------------ */
/*  Icon resolver                                                      */
/* ------------------------------------------------------------------ */

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; color?: string; className?: string }>> = {
  Tv, MessageCircle, Terminal, MessageSquare, PenTool, Globe,
  Camera, Code2, Cloud, Rss, LayoutDashboard, Mail, Mic,
  Search, Plug, BookOpen,
};

function IntegrationIcon({ name, size = 18, color }: { name?: string; size?: number; color?: string }) {
  const Icon = (name && ICON_MAP[name]) || Plug;
  return <Icon size={size} color={color} />;
}

/* ------------------------------------------------------------------ */
/*  Status dot — minimal, no badge chrome                              */
/* ------------------------------------------------------------------ */

function StatusDot({ item }: { item: IntegrationItem }) {
  const isEnabled = item.lifecycle_status === "enabled";
  const missingRequired = item.env_vars.some((v) => v.required && !v.is_set);
  const meta = !isEnabled
    ? { color: "#6b7280", label: "Available" }
    : missingRequired
      ? { color: "#eab308", label: "Needs Setup" }
      : { color: "#22c55e", label: "Enabled" };
  return (
    <span className="inline-flex flex-row items-center gap-1.5">
      <span
        className="w-[6px] h-[6px] rounded-full shrink-0"
        style={{ background: meta.color }}
      />
      <span className="text-[10px] font-medium" style={{ color: meta.color }}>
        {meta.label}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Section header                                                     */
/* ------------------------------------------------------------------ */

function SectionHeader({ label, count }: { label: string; count: number }) {
  const t = useThemeTokens();
  return (
    <div className="flex flex-row items-center gap-2 col-span-full pt-4 pb-1">
      <span className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: t.textMuted }}>
        {label}
      </span>
      <span className="text-[10px] font-medium tabular-nums" style={{ color: t.textDim }}>
        {count}
      </span>
      <div className="flex-1 h-px" style={{ background: t.surfaceBorder }} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Process controls — compact horizontal                              */
/* ------------------------------------------------------------------ */

function ProcessControls({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const startMut = useStartProcess(item.id);
  const stopMut = useStopProcess(item.id);
  const restartMut = useRestartProcess(item.id);

  const ps = item.process_status;
  const isRunning = ps?.status === "running";
  const anyPending = startMut.isPending || stopMut.isPending || restartMut.isPending;

  const stop = (e: React.MouseEvent) => { e.stopPropagation(); stopMut.mutate(); };
  const restart = (e: React.MouseEvent) => { e.stopPropagation(); restartMut.mutate(); };
  const start = (e: React.MouseEvent) => { e.stopPropagation(); startMut.mutate(); };

  const btnClass = "flex flex-row items-center justify-center w-5 h-5 rounded border-none";

  return (
    <div className="flex flex-row items-center gap-1.5 mt-1 pt-0">
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: isRunning ? "#22c55e" : "#6b7280" }} />
      <span className="text-[10px] font-medium" style={{ color: isRunning ? "#22c55e" : t.textDim }}>
        {isRunning ? "Running" : "Stopped"}
      </span>
      {isRunning && ps?.uptime_seconds != null && (
        <span className="text-[9px]" style={{ color: t.textDim }}>{formatUptime(ps.uptime_seconds)}</span>
      )}
      <div className="flex-1" />
      {isRunning ? (
        <div className="flex flex-row gap-0.5">
          <button onClick={stop} disabled={anyPending} title="Stop" className={btnClass}
            style={{ background: "rgba(239,68,68,0.12)", color: "#ef4444", opacity: anyPending ? 0.5 : 1, cursor: anyPending ? "wait" : "pointer" }}>
            <Square size={9} />
          </button>
          <button onClick={restart} disabled={anyPending} title="Restart" className={btnClass}
            style={{ background: "rgba(59,130,246,0.12)", color: "#3b82f6", opacity: anyPending ? 0.5 : 1, cursor: anyPending ? "wait" : "pointer" }}>
            <RefreshCw size={9} />
          </button>
        </div>
      ) : (
        <button onClick={start} disabled={anyPending} title="Start" className={btnClass}
          style={{ background: "rgba(34,197,94,0.12)", color: "#22c55e", opacity: anyPending ? 0.5 : 1, cursor: anyPending ? "wait" : "pointer" }}>
          <Play size={9} />
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Integration card                                                   */
/* ------------------------------------------------------------------ */

function IntegrationCard({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const [hovered, setHovered] = useState(false);
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
  ].filter(Boolean) as string[];

  const isAvailable = item.lifecycle_status === "available";
  const isRunnable = item.lifecycle_status === "enabled";

  const onAdd = (e: React.MouseEvent) => {
    e.stopPropagation();
    statusMut.mutate("enabled");
  };

  return (
    <button
      onClick={() => {
        // In the library, clicking the body also navigates to the setup page so
        // users can read descriptions / start filling env vars before Add.
        navigate(`/admin/integrations/${item.id}`);
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="flex flex-col text-left w-full rounded-lg overflow-hidden"
      style={{
        background: hovered ? t.surfaceOverlay : t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        opacity: isAvailable ? 0.7 : 1,
        cursor: "pointer",
        transition: "background 0.12s, box-shadow 0.12s, opacity 0.12s",
        boxShadow: hovered ? "0 2px 8px rgba(0,0,0,0.12)" : "none",
        padding: "10px 12px",
      }}
    >
      {/* Top row: icon + name + status */}
      <div className="flex flex-row items-center gap-2.5 w-full">
        <div
          className="flex flex-row items-center justify-center w-8 h-8 rounded-md shrink-0"
          style={{ background: t.surfaceOverlay }}
        >
          <IntegrationIcon name={item.icon} size={16} color={t.textMuted} />
        </div>
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-[13px] font-semibold truncate leading-tight" style={{ color: t.text }}>
            {item.name}
          </span>
          <StatusDot item={item} />
        </div>
        {/* Env var indicator — suppressed in Library (user hasn't adopted yet) */}
        {!isAvailable && envTotal > 0 && (
          <span
            className="inline-flex flex-row items-center gap-1 text-[10px] font-medium tabular-nums shrink-0"
            style={{ color: allEnvSet ? "#22c55e" : missingRequired ? "#eab308" : t.textDim }}
          >
            {allEnvSet ? <CheckCircle2 size={10} /> : missingRequired ? <AlertTriangle size={10} /> : null}
            {envSetCount}/{envTotal}
          </span>
        )}
        {/* Add button — Library cards only */}
        {isAvailable && (
          <button
            onClick={onAdd}
            disabled={statusMut.isPending}
            className="flex flex-row items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold shrink-0"
            style={{
              background: t.accent,
              color: "#fff",
              border: "none",
              cursor: statusMut.isPending ? "wait" : "pointer",
              opacity: statusMut.isPending ? 0.5 : 1,
            }}
          >
            <Plus size={11} /> Add
          </button>
        )}
      </div>

      {/* Capability pills — suppress in Library to emphasize card is pre-adoption */}
      {activeCaps.length > 0 && !isAvailable && (
        <div className="flex flex-row flex-wrap gap-1 mt-2">
          {activeCaps.map((c) => (
            <CapBadge key={c} label={c} active />
          ))}
        </div>
      )}

      {/* Process controls — only for fully enabled integrations */}
      {item.has_process && isRunnable && <ProcessControls item={item} />}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Render item types                                                  */
/* ------------------------------------------------------------------ */

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "card"; key: string; item: IntegrationItem };

/* ------------------------------------------------------------------ */
/*  Main screen                                                        */
/* ------------------------------------------------------------------ */

const TAB_KEYS = ["active", "library"] as const;
type TabKey = (typeof TAB_KEYS)[number];

export default function IntegrationsScreen() {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");
  const [showGuide, setShowGuide] = useState(false);
  const [activeTab, setActiveTab] = useHashTab<TabKey>("active", TAB_KEYS);

  const all = useMemo(() => {
    if (!data?.integrations) return undefined;
    return [...new Map(data.integrations.map((i) => [i.id, i])).values()];
  }, [data]);

  const activeCount = all?.filter((i) => i.lifecycle_status !== "available").length ?? 0;
  const libraryCount = all?.filter((i) => i.lifecycle_status === "available").length ?? 0;

  const filtered = useMemo(() => {
    if (!all) return [];
    const q = search.toLowerCase().trim();
    const scoped = all.filter((i) =>
      activeTab === "active"
        ? i.lifecycle_status !== "available"
        : i.lifecycle_status === "available",
    );
    if (!q) return scoped;
    return scoped.filter(
      (i) => i.name.toLowerCase().includes(q) || i.id.toLowerCase().includes(q),
    );
  }, [all, search, activeTab]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];

    if (activeTab === "library") {
      // Single flat list; library is a catalog, no internal grouping.
      return filtered.map((i) => ({ type: "card", key: i.id, item: i } as RenderItem));
    }

    // Active tab: split enabled into "Needs Setup" (missing required settings)
    // and "Ready" — two derived groups off a single lifecycle state.
    const needsSetup: IntegrationItem[] = [];
    const ready: IntegrationItem[] = [];

    for (const i of filtered) {
      if (i.lifecycle_status !== "enabled") continue;
      const missingRequired = i.env_vars.some((v) => v.required && !v.is_set);
      if (missingRequired) needsSetup.push(i);
      else ready.push(i);
    }

    const items: RenderItem[] = [];
    const add = (key: string, label: string, list: IntegrationItem[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const i of list) items.push({ type: "card", key: i.id, item: i });
    };

    add("needs-setup", "Needs Setup", needsSetup);
    add("ready", "Ready", ready);

    return items;
  }, [filtered, activeTab]);

  if (isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner color={t.accent} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Integrations" />

      {/* Tab bar */}
      <div
        className="flex flex-row items-center gap-1"
        style={{ padding: isWide ? "8px 16px 0" : "8px 12px 0" }}
      >
        {TAB_KEYS.map((key) => {
          const label = key === "active" ? "Active" : "Library";
          const count = key === "active" ? activeCount : libraryCount;
          const selected = activeTab === key;
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className="flex flex-row items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-semibold cursor-pointer"
              style={{
                background: selected ? t.accentSubtle : "transparent",
                color: selected ? t.accent : t.textMuted,
                border: "none",
                transition: "background 0.12s, color 0.12s",
              }}
            >
              {label}
              <span
                className="text-[10px] tabular-nums"
                style={{ color: selected ? t.accent : t.textDim, opacity: 0.75 }}
              >
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Toolbar */}
      <div
        className="flex flex-row items-center gap-2.5"
        style={{ padding: isWide ? "8px 16px" : "8px 12px", borderBottom: `1px solid ${t.surfaceBorder}` }}
      >
        {all && all.length > 0 && (
          <div
            className="flex flex-row items-center gap-1.5 rounded-md"
            style={{ background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, padding: "5px 10px", maxWidth: isWide ? 260 : undefined, flex: isWide ? undefined : 1 }}
          >
            <Search size={13} color={t.textDim} style={{ flexShrink: 0 }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter integrations..."
              className="bg-transparent border-none outline-none text-[12px] flex-1 w-full"
              style={{ color: t.text }}
            />
            {search && (
              <button onClick={() => setSearch("")} className="flex flex-row p-0 bg-transparent border-none cursor-pointer">
                <X size={12} color={t.textDim} />
              </button>
            )}
          </div>
        )}
        {all && all.length > 0 && (
          <span className="text-[11px] whitespace-nowrap" style={{ color: t.textDim }}>
            {filtered.length} {activeTab === "library" ? "available" : "active"}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => setShowGuide(true)}
          title="Integration Developer Guide"
          className="flex flex-row items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium cursor-pointer shrink-0"
          style={{ border: `1px solid ${t.surfaceBorder}`, background: "transparent", color: t.textMuted }}
        >
          <BookOpen size={13} />
          Dev Guide
        </button>
      </div>

      {/* Card grid */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: isWide ? "0 16px 16px" : "0 12px 12px" }}
      >
        {(!all || all.length === 0) && (
          <div className="p-10 text-center text-[13px]" style={{ color: t.textDim }}>
            No integrations discovered.
          </div>
        )}

        {all && all.length > 0 && filtered.length === 0 && (
          <div className="p-10 text-center text-[13px]" style={{ color: t.textDim }}>
            {search
              ? `No integrations match "${search}"`
              : activeTab === "active"
                ? "No integrations adopted yet. Browse the Library tab to add one."
                : "No available integrations — everything has been adopted."}
          </div>
        )}

        <div
          className="grid gap-2"
          style={{ gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(240px, 1fr))" : "1fr" }}
        >
          {renderItems.map((ri) =>
            ri.type === "header" ? (
              <SectionHeader key={ri.key} label={ri.label} count={ri.count} />
            ) : (
              <IntegrationCard key={ri.key} item={ri.item} />
            ),
          )}
        </div>
      </RefreshableScrollView>

      {showGuide && <IntegrationGuideModal onClose={() => setShowGuide(false)} />}
    </div>
  );
}
