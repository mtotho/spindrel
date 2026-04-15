import { useState, useMemo } from "react";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Search, Play, Square, RefreshCw, BookOpen, X, Plug,
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

const STATUS_META: Record<string, { color: string; label: string }> = {
  ready: { color: "#22c55e", label: "Ready" },
  partial: { color: "#eab308", label: "Needs setup" },
  not_configured: { color: "#6b7280", label: "Not configured" },
  disabled: { color: "#ef4444", label: "Disabled" },
};

function StatusDot({ status }: { status: string }) {
  const meta = STATUS_META[status] || STATUS_META.not_configured;
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
  const isDisabled = item.disabled;

  const envSetCount = item.env_vars.filter((v) => v.is_set).length;
  const envTotal = item.env_vars.length;
  const allEnvSet = envTotal > 0 && envSetCount === envTotal;
  const missingRequired = item.env_vars.some((v) => v.required && !v.is_set);

  const activeCaps = [
    item.has_router && "router",
    item.has_hooks && "hooks",
    item.has_tools && "tools",
    item.has_skills && "skills",
    item.has_carapaces && "capabilities",
  ].filter(Boolean) as string[];

  const effectiveStatus = isDisabled ? "disabled" : item.status;

  return (
    <button
      onClick={() => navigate(`/admin/integrations/${item.id}`)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="flex flex-col text-left w-full rounded-lg overflow-hidden"
      style={{
        background: hovered ? t.surfaceOverlay : t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        opacity: isDisabled ? 0.45 : 1,
        cursor: "pointer",
        transition: "background 0.12s, box-shadow 0.12s",
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
          <StatusDot status={effectiveStatus} />
        </div>
        {/* Env var indicator — top right */}
        {envTotal > 0 && (
          <span
            className="inline-flex flex-row items-center gap-1 text-[10px] font-medium tabular-nums shrink-0"
            style={{ color: allEnvSet ? "#22c55e" : missingRequired ? "#eab308" : t.textDim }}
          >
            {allEnvSet ? <CheckCircle2 size={10} /> : missingRequired ? <AlertTriangle size={10} /> : null}
            {envSetCount}/{envTotal}
          </span>
        )}
      </div>

      {/* Capability pills — horizontal wrap */}
      {activeCaps.length > 0 && (
        <div className="flex flex-row flex-wrap gap-1 mt-2">
          {activeCaps.map((c) => (
            <CapBadge key={c} label={c} active />
          ))}
        </div>
      )}

      {/* Process controls */}
      {item.has_process && !isDisabled && <ProcessControls item={item} />}
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

export default function IntegrationsScreen() {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");
  const [showGuide, setShowGuide] = useState(false);

  const all = useMemo(() => {
    if (!data?.integrations) return undefined;
    return [...new Map(data.integrations.map((i) => [i.id, i])).values()];
  }, [data]);

  const filtered = useMemo(() => {
    if (!all) return [];
    const q = search.toLowerCase().trim();
    if (!q) return all;
    return all.filter(
      (i) => i.name.toLowerCase().includes(q) || i.id.toLowerCase().includes(q),
    );
  }, [all, search]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];

    const ready: IntegrationItem[] = [];
    const needsSetup: IntegrationItem[] = [];
    const packages: IntegrationItem[] = [];
    const disabled: IntegrationItem[] = [];

    for (const i of filtered) {
      if (i.disabled) disabled.push(i);
      else if (i.source === "package") packages.push(i);
      else if (i.status === "ready") ready.push(i);
      else needsSetup.push(i);
    }

    const items: RenderItem[] = [];
    const add = (key: string, label: string, list: IntegrationItem[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const i of list) items.push({ type: "card", key: i.id, item: i });
    };

    add("ready", "Ready", ready);
    add("needs-setup", "Needs Setup", needsSetup);
    add("packages", "Packages", packages);
    add("disabled", "Disabled", disabled);

    return items;
  }, [filtered]);

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
            {search && filtered.length !== all.length ? `${filtered.length} / ${all.length}` : all.length} integrations
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
            No integrations match &ldquo;{search}&rdquo;
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
