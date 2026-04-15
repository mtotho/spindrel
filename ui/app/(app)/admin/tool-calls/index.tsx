import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState } from "react";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { AlertTriangle, Clock, Wrench, ExternalLink } from "lucide-react";
import {
  useToolCalls,
  useToolCallStats,
  type ToolCallItem,
  type ToolCallFilters,
} from "@/src/api/hooks/useToolCalls";
import { PageHeader } from "@/src/components/layout/PageHeader";
import {
  Section,
  FormRow,
  TextInput,
  SelectInput,
  Toggle,
  TabBar,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

function ToolTypeBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  const config: Record<string, { bg: string; color: string }> = {
    local: { bg: t.accentSubtle, color: t.accent },
    mcp: { bg: t.purpleSubtle, color: t.purple },
    client: { bg: t.successSubtle, color: t.success },
  };
  const c = config[type] || config.local;
  return (
    <span
      style={{
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        background: c.bg,
        color: c.color,
      }}
    >
      {type}
    </span>
  );
}

function ToolCallRow({ call }: { call: ToolCallItem }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const hasError = !!call.error;
  const createdAt = new Date(call.created_at).toLocaleString();

  return (
    <button
      onClick={() => setExpanded(!expanded)}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "12px 16px",
        background: t.inputBg,
        borderRadius: 8,
        border: hasError ? `1px solid ${t.dangerBorder}` : `1px solid ${t.surfaceOverlay}`,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        {hasError ? (
          <AlertTriangle size={14} color={t.danger} />
        ) : (
          <Wrench size={14} color={t.textDim} />
        )}
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: t.text,
            fontFamily: "monospace",
            flex: 1,
          }}
        >
          {call.tool_name}
        </span>
        <ToolTypeBadge type={call.tool_type} />
        {call.duration_ms != null && (
          <span style={{ fontSize: 11, color: t.textDim, display: "flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
            <Clock size={10} /> {call.duration_ms}ms
          </span>
        )}
      </div>

      <div
        style={{
          display: "flex", flexDirection: "row",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
        }}
      >
        {call.bot_id && (
          <span style={{ fontSize: 11, color: t.textMuted }}>
            bot:{call.bot_id}
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textDim }}>{createdAt}</span>
        {hasError && (
          <span style={{ fontSize: 11, color: t.danger }}>
            {call.error}
          </span>
        )}
      </div>

      {expanded && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            marginTop: 4,
          }}
        >
          <div>
            <div style={{ fontSize: 10, color: t.textDim, marginBottom: 2 }}>
              Arguments
            </div>
            <pre
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                background: t.surface,
                border: `1px solid ${t.surfaceRaised}`,
                fontSize: 11,
                color: t.textMuted,
                fontFamily: "monospace",
                overflow: "auto",
                maxHeight: 150,
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
          </div>
          {call.result && (
            <div>
              <div style={{ fontSize: 10, color: t.textDim, marginBottom: 2 }}>
                Result
              </div>
              <pre
                style={{
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: t.surface,
                  border: `1px solid ${t.surfaceRaised}`,
                  fontSize: 11,
                  color: hasError ? t.danger : t.textMuted,
                  fontFamily: "monospace",
                  overflow: "auto",
                  maxHeight: 200,
                  margin: 0,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-all",
                }}
              >
                {call.result}
              </pre>
            </div>
          )}
          <div style={{ fontSize: 10, color: t.textDim }}>
            ID: {call.id}
            {call.session_id && ` | Conv: ${call.session_id}`}
            {call.correlation_id && ` | Correlation: ${call.correlation_id}`}
          </div>
        </div>
      )}
    </button>
  );
}

function StatsPanel({
  botId,
  onDrillDown,
}: {
  botId?: string;
  onDrillDown: (filters: { toolName?: string; botId?: string; errorOnly: boolean }) => void;
}) {
  const t = useThemeTokens();
  const [groupBy, setGroupBy] = useState<"tool_name" | "bot_id" | "tool_type">(
    "tool_name"
  );
  const { data: stats, isLoading } = useToolCallStats(groupBy, botId);

  return (
    <Section title="Statistics">
      <div style={{ marginBottom: 12 }}>
        <TabBar
          tabs={[
            { key: "tool_name", label: "By Tool" },
            { key: "bot_id", label: "By Bot" },
            { key: "tool_type", label: "By Type" },
          ]}
          active={groupBy}
          onChange={(k) =>
            setGroupBy(k as "tool_name" | "bot_id" | "tool_type")
          }
        />
      </div>

      {isLoading ? (
        <Spinner />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {stats?.stats.map((s) => (
            <div
              key={s.key}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 12,
                padding: "8px 12px",
                background: t.inputBg,
                borderRadius: 6,
                border: `1px solid ${t.surfaceRaised}`,
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  color: t.text,
                  fontFamily: "monospace",
                  flex: 1,
                }}
              >
                {s.key}
              </span>
              <button
                onClick={() => {
                  const filters: { toolName?: string; botId?: string; errorOnly: boolean } = { errorOnly: false };
                  if (groupBy === "tool_name") filters.toolName = s.key;
                  else if (groupBy === "bot_id") filters.botId = s.key;
                  onDrillDown(filters);
                }}
                style={{
                  fontSize: 12,
                  color: t.accent,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 3,
                  padding: 0,
                }}
                title="View all calls"
              >
                {s.count} calls <ExternalLink size={10} />
              </button>
              <span style={{ fontSize: 12, color: t.textDim }}>
                avg {s.avg_duration_ms}ms
              </span>
              {s.error_count > 0 && (
                <button
                  onClick={() => {
                    const filters: { toolName?: string; botId?: string; errorOnly: boolean } = { errorOnly: true };
                    if (groupBy === "tool_name") filters.toolName = s.key;
                    else if (groupBy === "bot_id") filters.botId = s.key;
                    onDrillDown(filters);
                  }}
                  style={{
                    fontSize: 12,
                    color: t.danger,
                    background: t.dangerSubtle,
                    border: `1px solid ${t.dangerBorder}`,
                    borderRadius: 4,
                    cursor: "pointer",
                    padding: "2px 8px",
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 3,
                  }}
                  title="View errors only"
                >
                  {s.error_count} errors <ExternalLink size={10} />
                </button>
              )}
            </div>
          ))}
          {stats?.stats.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: t.textDim, fontSize: 13 }}>
              No data yet.
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

export default function ToolCallsScreen() {
  const t = useThemeTokens();
  const [tab, setTab] = useState("calls");
  const [botId, setBotId] = useState("");
  const [toolName, setToolName] = useState("");
  const [errorOnly, setErrorOnly] = useState(false);
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();

  const filters: ToolCallFilters = {
    limit: 100,
    ...(botId ? { bot_id: botId } : {}),
    ...(toolName ? { tool_name: toolName } : {}),
    ...(errorOnly ? { error_only: true } : {}),
  };
  const { data: calls, isLoading } = useToolCalls(filters);

  const handleDrillDown = (drillFilters: { toolName?: string; botId?: string; errorOnly: boolean }) => {
    if (drillFilters.toolName) setToolName(drillFilters.toolName);
    if (drillFilters.botId) setBotId(drillFilters.botId);
    setErrorOnly(drillFilters.errorOnly);
    setTab("calls");
  };

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Tool Calls" />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
        <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
          <div style={{ marginBottom: 16 }}>
            <TabBar
              tabs={[
                { key: "calls", label: "Call Log" },
                { key: "stats", label: "Statistics" },
              ]}
              active={tab}
              onChange={setTab}
            />
          </div>

          {tab === "stats" ? (
            <StatsPanel botId={botId || undefined} onDrillDown={handleDrillDown} />
          ) : (
            <>
              {/* Filters */}
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  flexWrap: "wrap",
                  gap: 12,
                  marginBottom: 16,
                  alignItems: "flex-end",
                }}
              >
                <div style={{ minWidth: 160 }}>
                  <FormRow label="Bot ID">
                    <TextInput
                      value={botId}
                      onChangeText={setBotId}
                      placeholder="(all)"
                      style={{ fontSize: 13, padding: "6px 10px" }}
                    />
                  </FormRow>
                </div>
                <div style={{ minWidth: 160 }}>
                  <FormRow label="Tool Name">
                    <TextInput
                      value={toolName}
                      onChangeText={setToolName}
                      placeholder="(all)"
                      style={{ fontSize: 13, padding: "6px 10px" }}
                    />
                  </FormRow>
                </div>
                <Toggle
                  value={errorOnly}
                  onChange={setErrorOnly}
                  label="Errors only"
                />
                {(toolName || botId || errorOnly) && (
                  <button
                    onClick={() => {
                      setToolName("");
                      setBotId("");
                      setErrorOnly(false);
                    }}
                    style={{
                      fontSize: 12,
                      color: t.textMuted,
                      background: t.surfaceRaised,
                      border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 5,
                      padding: "6px 12px",
                      cursor: "pointer",
                    }}
                  >
                    Clear filters
                  </button>
                )}
              </div>

              {/* Active filter indicator */}
              {(toolName || botId || errorOnly) && (
                <div style={{
                  fontSize: 11,
                  color: t.accent,
                  marginBottom: 12,
                  padding: "6px 12px",
                  background: t.accentSubtle,
                  borderRadius: 6,
                  border: `1px solid ${t.accentBorder}`,
                }}>
                  Filtered:{" "}
                  {toolName && <span>tool=<strong>{toolName}</strong> </span>}
                  {botId && <span>bot=<strong>{botId}</strong> </span>}
                  {errorOnly && <span><strong>errors only</strong></span>}
                </div>
              )}

              {/* Results */}
              {isLoading ? (
                <div className="items-center justify-center py-20">
                  <Spinner />
                </div>
              ) : (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  {calls?.map((c) => (
                    <ToolCallRow key={c.id} call={c} />
                  ))}
                  {calls?.length === 0 && (
                    <div
                      style={{
                        padding: 40,
                        textAlign: "center",
                        color: t.textDim,
                        fontSize: 14,
                      }}
                    >
                      No tool calls found.
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
