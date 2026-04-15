import { useState, useMemo } from "react";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { Search, Play, Square, RefreshCw, BookOpen } from "lucide-react";
import { IntegrationGuideModal } from "./IntegrationGuideModal";
import {
  useIntegrations,
  useStartProcess,
  useStopProcess,
  useRestartProcess,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { StatusBadge, CapBadge, formatUptime } from "./components";

// ---------------------------------------------------------------------------
// Section header (matches skills/tools pattern)
// ---------------------------------------------------------------------------

function SectionHeader({ label, count, isWide }: { label: string; count: number; isWide: boolean }) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
      padding: isWide ? "14px 16px 6px 16px" : "14px 0 6px 0",
    }}>
      <span style={{
        fontSize: 11, fontWeight: 600, color: t.textMuted,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim, fontWeight: 500 }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline process controls (compact, for list rows)
// ---------------------------------------------------------------------------

function InlineProcessControls({ item }: { item: IntegrationItem }) {
  const t = useThemeTokens();
  const startMut = useStartProcess(item.id);
  const stopMut = useStopProcess(item.id);
  const restartMut = useRestartProcess(item.id);

  const ps = item.process_status;
  const isRunning = ps?.status === "running";
  const anyPending = startMut.isPending || stopMut.isPending || restartMut.isPending;

  const btnStyle = (bg: string, fg: string): React.CSSProperties => ({
    display: "flex", flexDirection: "row", alignItems: "center", gap: 3,
    padding: "2px 8px", borderRadius: 4, border: "none",
    background: bg, color: fg,
    fontSize: 10, fontWeight: 600,
    cursor: anyPending ? "wait" : "pointer",
    opacity: anyPending ? 0.5 : 1,
  });

  const stop = (e: React.MouseEvent) => { e.stopPropagation(); stopMut.mutate(); };
  const restart = (e: React.MouseEvent) => { e.stopPropagation(); restartMut.mutate(); };
  const start = (e: React.MouseEvent) => { e.stopPropagation(); startMut.mutate(); };

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexShrink: 0 }}>
      <span style={{
        width: 7, height: 7, borderRadius: 4,
        background: isRunning ? "#22c55e" : "#6b7280", flexShrink: 0,
      }} />
      <span style={{ fontSize: 11, fontWeight: 500, color: isRunning ? "#22c55e" : t.textDim, whiteSpace: "nowrap" }}>
        {isRunning ? "Running" : "Stopped"}
      </span>
      {isRunning && ps?.uptime_seconds != null && (
        <span style={{ fontSize: 10, color: t.textDim, whiteSpace: "nowrap" }}>{formatUptime(ps.uptime_seconds)}</span>
      )}
      {isRunning ? (
        <div style={{ display: "flex", flexDirection: "row", gap: 3 }}>
          <button onClick={stop} disabled={anyPending} title="Stop" style={btnStyle("rgba(239,68,68,0.15)", "#ef4444")}>
            <Square size={9} />
          </button>
          <button onClick={restart} disabled={anyPending} title="Restart" style={btnStyle("rgba(59,130,246,0.15)", "#3b82f6")}>
            <RefreshCw size={9} />
          </button>
        </div>
      ) : (
        <button onClick={start} disabled={anyPending} title="Start" style={btnStyle("rgba(34,197,94,0.15)", "#22c55e")}>
          <Play size={9} />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Integration row
// ---------------------------------------------------------------------------

function IntegrationRow({ item, isWide }: { item: IntegrationItem; isWide: boolean }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const isDisabled = item.disabled;

  const envSetCount = item.env_vars.filter((v) => v.is_set).length;
  const activeCaps = [
    item.has_router && "router",
    item.has_dispatcher && "dispatcher",
    item.has_hooks && "hooks",
    item.has_tools && "tools",
    item.has_skills && "skills",
    item.has_carapaces && "capabilities",
  ].filter(Boolean) as string[];

  const rowOpacity = isDisabled ? 0.45 : 1;
  const effectiveStatus = isDisabled ? "disabled" : item.status;

  if (!isWide) {
    // Mobile: card layout (matches skills/tools mobile pattern)
    return (
      <button
        onClick={() => navigate(`/admin/integrations/${item.id}`)}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`, cursor: "pointer",
          textAlign: "left", width: "100%",
          opacity: rowOpacity,
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>{item.name}</span>
          <StatusBadge status={effectiveStatus} />
        </div>
        <div style={{ display: "flex", flexDirection: "row", gap: 4, flexWrap: "wrap" }}>
          {activeCaps.map((c) => <CapBadge key={c} label={c} active />)}
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, fontSize: 11, color: t.textDim }}>
          <span style={{
            fontSize: 9, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
            background: "rgba(107,114,128,0.08)", textTransform: "uppercase", letterSpacing: 0.3,
          }}>
            {item.source}
          </span>
          {item.env_vars.length > 0 && (
            <span style={{ color: envSetCount === item.env_vars.length ? "#22c55e" : t.textDim }}>
              {envSetCount}/{item.env_vars.length} vars
            </span>
          )}
          {item.webhook && (
            <code style={{ fontFamily: "monospace", fontSize: 10, color: t.textDim }}>{item.webhook.path}</code>
          )}
        </div>
        {item.has_process && !isDisabled && <InlineProcessControls item={item} />}
      </button>
    );
  }

  // Desktop: table row (matches skills/tools desktop pattern)
  return (
    <button
      onClick={() => navigate(`/admin/integrations/${item.id}`)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        border: "none",
        borderBottom: `1px solid ${t.surfaceBorder}`,
        cursor: "pointer",
        textAlign: "left", width: "100%",
        opacity: rowOpacity,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = t.inputBg; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      {/* Name + meta */}
      <div style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{item.name}</span>
          <StatusBadge status={effectiveStatus} />
          <div style={{ display: "flex", flexDirection: "row", gap: 3, flexWrap: "wrap" }}>
            {activeCaps.map((c) => <CapBadge key={c} label={c} active />)}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2 }}>
          <span style={{
            fontSize: 9, fontWeight: 600, padding: "1px 5px", borderRadius: 3,
            background: "rgba(107,114,128,0.08)", color: t.textDim,
            textTransform: "uppercase", letterSpacing: 0.3,
          }}>
            {item.source}
          </span>
          {item.webhook && (
            <span style={{ fontSize: 11, color: t.textDim }}>
              <code style={{ fontFamily: "monospace", fontSize: 10, color: t.textDim }}>{item.webhook.path}</code>
            </span>
          )}
          {item.env_vars.length > 0 && (
            <span style={{ fontSize: 10, color: envSetCount === item.env_vars.length ? "#22c55e" : t.textDim }}>
              {envSetCount}/{item.env_vars.length} vars
            </span>
          )}
        </div>
      </div>

      {/* Process controls (right side) */}
      {item.has_process && !isDisabled && <InlineProcessControls item={item} />}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main list screen
// ---------------------------------------------------------------------------

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "row"; key: string; item: IntegrationItem };

export default function IntegrationsScreen() {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");
  const [showGuide, setShowGuide] = useState(false);

  // Deduplicate
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

    if (ready.length) {
      items.push({ type: "header", key: "ready", label: "Ready", count: ready.length });
      for (const i of ready) items.push({ type: "row", key: i.id, item: i });
    }
    if (needsSetup.length) {
      items.push({ type: "header", key: "needs-setup", label: "Needs Setup", count: needsSetup.length });
      for (const i of needsSetup) items.push({ type: "row", key: i.id, item: i });
    }
    if (packages.length) {
      items.push({ type: "header", key: "packages", label: "Packages", count: packages.length });
      for (const i of packages) items.push({ type: "row", key: i.id, item: i });
    }
    if (disabled.length) {
      items.push({ type: "header", key: "disabled", label: "Disabled", count: disabled.length });
      for (const i of disabled) items.push({ type: "row", key: i.id, item: i });
    }

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

      {/* Toolbar: search bar (when items exist) + guide button (always) */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        {all && all.length > 0 && (
          <>
            <div style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6, padding: "5px 10px",
              maxWidth: isWide ? 300 : undefined, flex: isWide ? undefined : 1,
            }}>
              <Search size={13} color={t.textDim} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter integrations..."
                style={{
                  background: "none", border: "none", outline: "none",
                  color: t.text, fontSize: 12, flex: 1, width: "100%",
                }}
              />
            </div>
            <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
              {search && filtered.length !== all.length
                ? `${filtered.length} / ${all.length}`
                : all.length}{" "}
              integrations
            </span>
          </>
        )}
        {(!all || all.length === 0) && <div style={{ flex: 1 }} />}
        <button
          onClick={() => setShowGuide(true)}
          title="Integration Developer Guide"
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
            padding: "4px 8px", borderRadius: 5, border: `1px solid ${t.surfaceBorder}`,
            background: "transparent", color: t.textMuted,
            fontSize: 11, fontWeight: 500,
            cursor: "pointer",
            marginLeft: all && all.length > 0 ? undefined : "auto",
          }}
        >
          <BookOpen size={13} />
          Dev Guide
        </button>
      </div>

      {/* Status legend */}
      {all && all.length > 0 && (
        <div style={{
          padding: isWide ? "4px 16px 6px" : "4px 12px 6px",
          fontSize: 11, color: t.textDim, lineHeight: 1.5,
        }}>
          <strong style={{ color: t.textMuted }}>Ready</strong> = configured{" \u00b7 "}
          <strong style={{ color: t.textMuted }}>Needs Setup</strong> = missing required vars{" \u00b7 "}
          <strong style={{ color: t.textMuted }}>Disabled</strong> = globally off (tools unloaded, process stopped)
        </div>
      )}

      {/* List */}
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{
          padding: isWide ? 0 : 12,
          gap: isWide ? 0 : 8,
        }}
      >
        {(!all || all.length === 0) && (
          <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No integrations discovered.
          </div>
        )}

        {all && all.length > 0 && filtered.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No integrations match "{search}"
          </div>
        )}

        {renderItems.map((ri) =>
          ri.type === "header" ? (
            <SectionHeader key={ri.key} label={ri.label} count={ri.count} isWide={isWide} />
          ) : (
            <IntegrationRow key={ri.key} item={ri.item} isWide={isWide} />
          ),
        )}
      </RefreshableScrollView>

      {showGuide && <IntegrationGuideModal onClose={() => setShowGuide(false)} />}
    </div>
  );
}
