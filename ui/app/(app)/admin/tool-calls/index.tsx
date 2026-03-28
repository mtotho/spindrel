import { useState } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { AlertTriangle, Clock, Wrench } from "lucide-react";
import {
  useToolCalls,
  useToolCallStats,
  type ToolCallItem,
  type ToolCallFilters,
} from "@/src/api/hooks/useToolCalls";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import {
  Section,
  FormRow,
  TextInput,
  SelectInput,
  Toggle,
  TabBar,
} from "@/src/components/shared/FormControls";

function ToolTypeBadge({ type }: { type: string }) {
  const config: Record<string, { bg: string; color: string }> = {
    local: { bg: "rgba(59,130,246,0.12)", color: "#93c5fd" },
    mcp: { bg: "rgba(168,85,247,0.12)", color: "#c4b5fd" },
    client: { bg: "rgba(34,197,94,0.12)", color: "#86efac" },
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
        background: "#111",
        borderRadius: 8,
        border: hasError ? "1px solid rgba(239,68,68,0.2)" : "1px solid #222",
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {hasError ? (
          <AlertTriangle size={14} color="#ef4444" />
        ) : (
          <Wrench size={14} color="#666" />
        )}
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#e5e5e5",
            fontFamily: "monospace",
            flex: 1,
          }}
        >
          {call.tool_name}
        </span>
        <ToolTypeBadge type={call.tool_type} />
        {call.duration_ms != null && (
          <span style={{ fontSize: 11, color: "#555", display: "flex", alignItems: "center", gap: 3 }}>
            <Clock size={10} /> {call.duration_ms}ms
          </span>
        )}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
        }}
      >
        {call.bot_id && (
          <span style={{ fontSize: 11, color: "#888" }}>
            bot:{call.bot_id}
          </span>
        )}
        <span style={{ fontSize: 11, color: "#555" }}>{createdAt}</span>
        {hasError && (
          <span style={{ fontSize: 11, color: "#fca5a5" }}>
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
            <div style={{ fontSize: 10, color: "#666", marginBottom: 2 }}>
              Arguments
            </div>
            <pre
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                background: "#0a0a0a",
                border: "1px solid #1a1a1a",
                fontSize: 11,
                color: "#888",
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
              <div style={{ fontSize: 10, color: "#666", marginBottom: 2 }}>
                Result
              </div>
              <pre
                style={{
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: "#0a0a0a",
                  border: "1px solid #1a1a1a",
                  fontSize: 11,
                  color: hasError ? "#fca5a5" : "#888",
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
          <div style={{ fontSize: 10, color: "#555" }}>
            ID: {call.id}
            {call.session_id && ` | Session: ${call.session_id}`}
            {call.correlation_id && ` | Correlation: ${call.correlation_id}`}
          </div>
        </div>
      )}
    </button>
  );
}

function StatsPanel({ botId }: { botId?: string }) {
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
        <ActivityIndicator color="#3b82f6" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {stats?.stats.map((s) => (
            <div
              key={s.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "8px 12px",
                background: "#111",
                borderRadius: 6,
                border: "1px solid #1a1a1a",
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  color: "#e5e5e5",
                  fontFamily: "monospace",
                  flex: 1,
                }}
              >
                {s.key}
              </span>
              <span style={{ fontSize: 12, color: "#888" }}>
                {s.count} calls
              </span>
              <span style={{ fontSize: 12, color: "#666" }}>
                avg {s.avg_duration_ms}ms
              </span>
              {s.error_count > 0 && (
                <span style={{ fontSize: 12, color: "#fca5a5" }}>
                  {s.error_count} errors
                </span>
              )}
            </div>
          ))}
          {stats?.stats.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: "#555", fontSize: 13 }}>
              No data yet.
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

export default function ToolCallsScreen() {
  const [tab, setTab] = useState("calls");
  const [botId, setBotId] = useState("");
  const [toolName, setToolName] = useState("");
  const [errorOnly, setErrorOnly] = useState(false);
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();

  const filters: ToolCallFilters = {
    limit: 100,
    ...(botId ? { bot_id: botId } : {}),
    ...(toolName ? { tool_name: toolName } : {}),
    ...(errorOnly ? { error_only: true } : {}),
  };
  const { data: calls, isLoading } = useToolCalls(filters);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Tool Calls" />

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
            <StatsPanel botId={botId || undefined} />
          ) : (
            <>
              {/* Filters */}
              <div
                style={{
                  display: "flex",
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
              </div>

              {/* Results */}
              {isLoading ? (
                <View className="items-center justify-center py-20">
                  <ActivityIndicator color="#3b82f6" />
                </View>
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
                        color: "#555",
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
    </View>
  );
}
