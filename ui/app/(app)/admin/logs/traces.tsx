import { useState, useMemo, useCallback } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import {
  AlertTriangle, Wrench, MessageSquare, Clock, Heart,
  Zap, Bot, X, ChevronRight,
} from "lucide-react";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { LogsTabBar } from "@/src/components/logs/LogsTabBar";
import { useTraces, type TraceSummary } from "@/src/api/hooks/useLogs";
import { useBots } from "@/src/api/hooks/useBots";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { openTraceInspector } from "@/src/stores/traceInspector";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Source badge
// ---------------------------------------------------------------------------

function getSourceStyle(source: string, t: ThemeTokens) {
  switch (source) {
    case "agent":
      return { bg: t.accentSubtle, fg: t.accent, icon: MessageSquare, label: "Agent" };
    case "heartbeat":
      return { bg: t.warningSubtle, fg: t.warning, icon: Heart, label: "Heartbeat" };
    case "workflow":
      return { bg: t.purpleSubtle, fg: t.purple, icon: Zap, label: "Workflow" };
    case "task":
      return { bg: t.surfaceRaised, fg: t.textMuted, icon: Clock, label: "Task" };
    default:
      return { bg: t.surfaceRaised, fg: t.textDim, icon: Bot, label: source };
  }
}

function SourceBadge({ source, t }: { source: string; t: ThemeTokens }) {
  const s = getSourceStyle(source, t);
  const Icon = s.icon;
  return (
    <span style={{
      display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 700,
      background: s.bg, color: s.fg, textTransform: "uppercase", letterSpacing: 0.5,
      flexShrink: 0,
    }}>
      <Icon size={10} />
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

const SOURCE_FILTERS = [
  { label: "All", value: "" },
  { label: "Agent", value: "agent" },
  { label: "Workflow", value: "workflow" },
  { label: "Task", value: "task" },
  { label: "Heartbeat", value: "heartbeat" },
];

function FilterBar({
  sourceFilter, setSourceFilter, botFilter, setBotFilter,
  bots, hasFilters, clearFilters, t,
}: {
  sourceFilter: string; setSourceFilter: (v: string) => void;
  botFilter: string; setBotFilter: (v: string) => void;
  bots: any[] | undefined;
  hasFilters: boolean; clearFilters: () => void;
  t: ThemeTokens;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "row", gap: 8, padding: "8px 20px",
      borderBottom: `1px solid ${t.surfaceRaised}`, flexWrap: "wrap", alignItems: "center",
    }}>
      {/* Source filter pills */}
      <div style={{ display: "flex", flexDirection: "row", gap: 4 }}>
        {SOURCE_FILTERS.map((f) => {
          const active = sourceFilter === f.value;
          return (
            <button
              key={f.value}
              onClick={() => setSourceFilter(f.value)}
              style={{
                padding: "4px 10px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                border: `1px solid ${active ? t.accent : t.surfaceBorder}`,
                background: active ? t.accentMuted : "transparent",
                color: active ? t.accent : t.textMuted, cursor: "pointer",
              }}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {/* Bot filter */}
      <select
        value={botFilter}
        onChange={(e) => setBotFilter(e.target.value)}
        style={{
          background: t.surfaceRaised, color: t.textMuted, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px", fontSize: 12, outline: "none",
        }}
      >
        <option value="">All Bots</option>
        {(bots ?? []).map((b: any) => (
          <option key={b.id} value={b.id}>{b.name || b.id}</option>
        ))}
      </select>

      {hasFilters && (
        <button
          onClick={clearFilters}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
            background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 12,
          }}
        >
          <X size={12} /> Clear
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trace row
// ---------------------------------------------------------------------------

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function TraceRow({ trace, t, onPress }: { trace: TraceSummary; t: ThemeTokens; onPress: () => void }) {
  const title = trace.title || trace.correlation_id.slice(0, 12);
  const dur = fmtDuration(trace.duration_ms);

  return (
    <div
      onClick={onPress}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = t.accent; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = t.surfaceRaised; }}
      style={{
        padding: "10px 16px", background: t.inputBg, borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`, cursor: "pointer", marginBottom: 2,
        transition: "border-color 0.15s",
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
        <SourceBadge source={trace.source_type} t={t} />

        <span style={{
          fontSize: 13, fontWeight: 600, color: t.text,
          flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {title}
        </span>

        {trace.has_error && (
          <span style={{
            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
            padding: "1px 6px", borderRadius: 4, fontSize: 10, fontWeight: 600,
            background: t.dangerSubtle, color: t.danger,
          }}>
            <AlertTriangle size={10} /> Error
          </span>
        )}

        {trace.tool_call_count > 0 && (
          <span style={{
            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
            fontSize: 10, color: t.textDim,
          }}>
            <Wrench size={10} /> {trace.tool_call_count}
          </span>
        )}

        {trace.total_tokens > 0 && (
          <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
            {trace.total_tokens.toLocaleString()} tok
          </span>
        )}

        {dur && (
          <span style={{ fontSize: 10, color: t.textDim }}>{dur}</span>
        )}

        {trace.bot_id && (
          <span style={{ fontSize: 10, color: t.textDim }}>{trace.bot_id}</span>
        )}

        {trace.channel_name && (
          <span style={{ fontSize: 10, color: t.textDim }}>#{trace.channel_name}</span>
        )}

        <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
          {fmtTime(trace.created_at)}
        </span>

        <ChevronRight size={14} color={t.textDim} style={{ flexShrink: 0 }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TracesScreen() {
  const t = useThemeTokens();
  const { refreshing, onRefresh } = usePageRefresh();
  const { data: bots } = useBots();

  const [sourceFilter, setSourceFilter] = useState("");
  const [botFilter, setBotFilter] = useState("");
  const [beforeCursor, setBeforeCursor] = useState<string | undefined>(undefined);

  const PAGE_SIZE = 50;

  const params = useMemo(() => ({
    count: PAGE_SIZE,
    ...(sourceFilter ? { source_type: sourceFilter } : {}),
    ...(botFilter ? { bot_id: botFilter } : {}),
    ...(beforeCursor ? { before: beforeCursor } : {}),
  }), [sourceFilter, botFilter, beforeCursor]);

  const { data, isLoading } = useTraces(params);
  const traces = data?.traces ?? [];

  const hasFilters = !!(sourceFilter || botFilter);
  const clearFilters = useCallback(() => {
    setSourceFilter("");
    setBotFilter("");
    setBeforeCursor(undefined);
  }, []);

  const handleFilterChange = useCallback((setter: (v: any) => void, value: any) => {
    setter(value);
    setBeforeCursor(undefined);
  }, []);

  // Group by date
  const grouped = useMemo(() => {
    const groups: { label: string; traces: TraceSummary[] }[] = [];
    let currentLabel = "";
    for (const tr of traces) {
      const label = fmtDate(tr.created_at);
      if (label !== currentLabel) {
        groups.push({ label, traces: [] });
        currentLabel = label;
      }
      groups[groups.length - 1].traces.push(tr);
    }
    return groups;
  }, [traces]);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Traces" subtitle={data ? `${traces.length} traces` : "Loading..."} />

      <LogsTabBar active="traces" />

      <FilterBar
        sourceFilter={sourceFilter}
        setSourceFilter={(v) => handleFilterChange(setSourceFilter, v)}
        botFilter={botFilter}
        setBotFilter={(v) => handleFilterChange(setBotFilter, v)}
        bots={bots}
        hasFilters={hasFilters}
        clearFilters={clearFilters}
        t={t}
      />

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
          <div style={{ display: "flex", flexDirection: "column", padding: "8px 20px" }}>
            {grouped.map((group) => (
              <div key={group.label}>
                <div style={{
                  fontSize: 11, fontWeight: 700, color: t.textDim,
                  textTransform: "uppercase", letterSpacing: 0.5,
                  padding: "12px 0 6px",
                }}>
                  {group.label}
                </div>
                {group.traces.map((tr) => (
                  <TraceRow
                    key={tr.correlation_id}
                    trace={tr}
                    t={t}
                    onPress={() => openTraceInspector({
                      correlationId: tr.correlation_id,
                      title: tr.title || "Trace",
                      subtitle: `${tr.source_type}${tr.bot_id ? ` · ${tr.bot_id}` : ""}`,
                    })}
                  />
                ))}
              </div>
            ))}

            {traces.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
                No traces found.
              </div>
            )}
          </div>

          {/* Load more */}
          {data?.has_more && traces.length > 0 && (
            <div style={{ display: "flex", flexDirection: "row", justifyContent: "center", padding: "16px 20px" }}>
              <button
                onClick={() => {
                  const last = traces[traces.length - 1];
                  if (last) setBeforeCursor(last.created_at);
                }}
                style={{
                  background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 6, padding: "8px 24px", fontSize: 12, color: t.textMuted,
                  cursor: "pointer",
                }}
              >
                Load older traces
              </button>
            </div>
          )}
        </RefreshableScrollView>
      )}
    </div>
  );
}
