import { useState, useMemo } from "react";
import { View, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useBots } from "@/src/api/hooks/useBots";
import {
  useUsageLogs,
  type UsageParams,
  type UsageLogEntry,
} from "@/src/api/hooks/useUsage";
import { fmtCost, fmtTokens, fmtTime, fmtDate, fmtDuration } from "./usageUtils";

// ---------------------------------------------------------------------------
// Trace grouping
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

// ---------------------------------------------------------------------------
// Trace view (expanded detail for a single trace group)
// ---------------------------------------------------------------------------
function TraceDetail({ group }: { group: TraceGroup }) {
  const router = useRouter();
  const t = useThemeTokens();
  return (
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
  );
}

// ---------------------------------------------------------------------------
// Trace row (single row in trace view)
// ---------------------------------------------------------------------------
function TraceRow({
  group,
  expanded,
  onToggle,
}: {
  group: TraceGroup;
  expanded: boolean;
  onToggle: () => void;
}) {
  const t = useThemeTokens();
  return (
    <div>
      <div
        onClick={onToggle}
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
      {expanded && <TraceDetail group={group} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Raw call row
// ---------------------------------------------------------------------------
function RawCallRow({ entry, botName }: { entry: UsageLogEntry; botName: string }) {
  const t = useThemeTokens();
  return (
    <div
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
        {botName}
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
}

// ---------------------------------------------------------------------------
// Logs tab
// ---------------------------------------------------------------------------
export function LogsTab({ params }: { params: UsageParams }) {
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
          {/* Trace view header */}
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
            <TraceRow
              key={group.correlation_id}
              group={group}
              expanded={expandedTrace === group.correlation_id}
              onToggle={() =>
                setExpandedTrace(
                  expandedTrace === group.correlation_id ? null : group.correlation_id,
                )
              }
            />
          ))}
        </>
      ) : (
        <>
          {/* Raw call view header */}
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
              <RawCallRow
                key={entry.id}
                entry={entry}
                botName={bot?.name || entry.bot_id || "--"}
              />
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
