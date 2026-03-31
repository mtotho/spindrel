import { useState } from "react";
import { View, Text, Pressable } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMCChannelContext } from "@/src/api/hooks/useMissionControl";
import {
  ChevronDown,
  ChevronRight,
  Settings,
  FileText,
  Code2,
  Wrench,
  Activity,
  Layers,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Collapsible Section
// ---------------------------------------------------------------------------
function Section({
  title,
  icon: Icon,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  badge?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const t = useThemeTokens();
  return (
    <View className="rounded-xl border border-surface-border overflow-hidden">
      <Pressable
        onPress={() => setOpen(!open)}
        className="flex-row items-center gap-2 px-4 py-3 hover:bg-surface-overlay"
      >
        {open ? (
          <ChevronDown size={14} color={t.textDim} />
        ) : (
          <ChevronRight size={14} color={t.textDim} />
        )}
        <Icon size={14} color={t.textDim} />
        <Text className="text-text font-semibold text-sm flex-1">{title}</Text>
        {badge && (
          <View
            className="rounded-full px-2 py-0.5"
            style={{ backgroundColor: "rgba(107,114,128,0.1)" }}
          >
            <Text className="text-text-dim text-[10px] font-semibold">
              {badge}
            </Text>
          </View>
        )}
      </Pressable>
      {open && (
        <View className="px-4 pb-4 border-t border-surface-border pt-3">
          {children}
        </View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Config row
// ---------------------------------------------------------------------------
function ConfigRow({ label, value }: { label: string; value: string }) {
  const t = useThemeTokens();
  return (
    <View className="flex-row items-start gap-3 py-1.5">
      <Text
        className="text-text-dim text-xs font-medium"
        style={{ width: 140, flexShrink: 0 }}
      >
        {label}
      </Text>
      <Text className="text-text-muted text-xs flex-1" selectable>
        {value || "—"}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Tool call row
// ---------------------------------------------------------------------------
function ToolCallRow({
  tc,
}: {
  tc: {
    id: string;
    tool_name: string;
    tool_type: string;
    arguments: Record<string, unknown>;
    result: string;
    error: string | null;
    duration_ms: number | null;
    created_at: string | null;
  };
}) {
  const [expanded, setExpanded] = useState(false);
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={() => setExpanded(!expanded)}
      className="rounded-lg border border-surface-border p-3 hover:bg-surface-overlay"
    >
      <View className="flex-row items-center gap-2">
        <Text className="text-text font-medium text-xs flex-1" numberOfLines={1}>
          {tc.tool_name}
        </Text>
        <Text className="text-text-dim text-[10px]">{tc.tool_type}</Text>
        {tc.duration_ms !== null && (
          <Text className="text-text-dim text-[10px]">{tc.duration_ms}ms</Text>
        )}
        {tc.error && (
          <View
            className="rounded-full px-1.5 py-0.5"
            style={{ backgroundColor: "rgba(239,68,68,0.15)" }}
          >
            <Text style={{ fontSize: 9, color: "#ef4444", fontWeight: "600" }}>
              ERR
            </Text>
          </View>
        )}
      </View>
      {tc.created_at && (
        <Text className="text-text-dim text-[10px] mt-1">
          {new Date(tc.created_at).toLocaleString()}
        </Text>
      )}

      {expanded && (
        <View className="mt-3 pt-3 border-t border-surface-border gap-2">
          <View>
            <Text className="text-text-dim text-[10px] font-semibold mb-1">
              ARGUMENTS
            </Text>
            <Text
              className="text-text-muted text-[10px]"
              style={{ fontFamily: "monospace" }}
              selectable
            >
              {JSON.stringify(tc.arguments, null, 2)}
            </Text>
          </View>
          {tc.result && (
            <View>
              <Text className="text-text-dim text-[10px] font-semibold mb-1">
                RESULT
              </Text>
              <Text
                className="text-text-muted text-[10px]"
                style={{ fontFamily: "monospace" }}
                selectable
                numberOfLines={20}
              >
                {tc.result}
              </Text>
            </View>
          )}
          {tc.error && (
            <View>
              <Text
                className="text-[10px] font-semibold mb-1"
                style={{ color: "#ef4444" }}
              >
                ERROR
              </Text>
              <Text
                className="text-[10px]"
                style={{ fontFamily: "monospace", color: "#ef4444" }}
                selectable
              >
                {tc.error}
              </Text>
            </View>
          )}
        </View>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Trace event row
// ---------------------------------------------------------------------------
function TraceRow({
  te,
}: {
  te: {
    id: string;
    event_type: string;
    event_name: string | null;
    data: Record<string, unknown> | null;
    duration_ms: number | null;
    created_at: string | null;
  };
}) {
  const [expanded, setExpanded] = useState(false);
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={() => setExpanded(!expanded)}
      className="rounded-lg border border-surface-border p-3 hover:bg-surface-overlay"
    >
      <View className="flex-row items-center gap-2">
        <Text className="text-text font-medium text-xs flex-1" numberOfLines={1}>
          {te.event_type}
          {te.event_name ? ` — ${te.event_name}` : ""}
        </Text>
        {te.duration_ms !== null && (
          <Text className="text-text-dim text-[10px]">{te.duration_ms}ms</Text>
        )}
      </View>
      {te.created_at && (
        <Text className="text-text-dim text-[10px] mt-1">
          {new Date(te.created_at).toLocaleString()}
        </Text>
      )}
      {expanded && te.data && (
        <View className="mt-3 pt-3 border-t border-surface-border">
          <Text
            className="text-text-muted text-[10px]"
            style={{ fontFamily: "monospace" }}
            selectable
          >
            {JSON.stringify(te.data, null, 2)}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCChannelContext() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const router = useRouter();
  const { data, isLoading } = useMCChannelContext(channelId);
  const { refreshing, onRefresh } = usePageRefresh([
    ["mc-channel-context", channelId!],
  ]);
  const t = useThemeTokens();

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title={data?.config.channel_name || "Channel Context"}
        subtitle="Debug inspector"
        onBack={() => router.back()}
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 40 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading...</Text>
        ) : !data ? (
          <Text className="text-text-muted text-sm">Channel not found</Text>
        ) : (
          <>
            {/* 1. Configuration */}
            <Section title="Configuration" icon={Settings} defaultOpen>
              <View>
                <ConfigRow label="Channel ID" value={data.config.channel_id} />
                <ConfigRow label="Bot" value={`${data.config.bot_name} (${data.config.bot_id})`} />
                <ConfigRow label="Model" value={data.config.model} />
                <ConfigRow label="Workspace" value={data.config.workspace_enabled ? "Enabled" : "Disabled"} />
                <ConfigRow label="Workspace RAG" value={data.config.workspace_rag ? "On" : "Off"} />
                <ConfigRow label="Compaction" value={data.config.context_compaction ? "On" : "Off"} />
                <ConfigRow label="Memory Scheme" value={data.config.memory_scheme || "none"} />
                <ConfigRow label="History Mode" value={data.config.history_mode || "default"} />
                <ConfigRow label="Tools" value={data.config.tools.join(", ") || "none"} />
                <ConfigRow label="MCP Servers" value={data.config.mcp_servers.join(", ") || "none"} />
                <ConfigRow label="Skills" value={data.config.skills.join(", ") || "none"} />
                <ConfigRow label="Pinned Tools" value={data.config.pinned_tools.join(", ") || "none"} />
              </View>
            </Section>

            {/* 2. Workspace Schema */}
            <Section
              title="Workspace Schema"
              icon={Layers}
              badge={data.schema.template_name || undefined}
            >
              {data.schema.content ? (
                <Text
                  className="text-text-muted text-xs"
                  style={{ fontFamily: "monospace", lineHeight: 18 }}
                  selectable
                >
                  {data.schema.content}
                </Text>
              ) : (
                <Text className="text-text-dim text-xs italic">
                  No workspace schema assigned
                </Text>
              )}
              {data.schema.content && (
                <Text className="text-text-dim text-[10px] mt-2">
                  {data.schema.content.length.toLocaleString()} chars
                </Text>
              )}
            </Section>

            {/* 3. Workspace Files */}
            <Section
              title="Workspace Files"
              icon={FileText}
              badge={`${data.files.length}`}
            >
              {data.files.length === 0 ? (
                <Text className="text-text-dim text-xs italic">
                  No workspace files
                </Text>
              ) : (
                <View className="gap-2">
                  {data.files.map((f) => (
                    <View
                      key={f.path}
                      className="flex-row items-center gap-2 rounded-lg border border-surface-border px-3 py-2"
                    >
                      <FileText size={12} color={t.textDim} />
                      <Text className="text-text-muted text-xs flex-1" numberOfLines={1}>
                        {f.name}
                      </Text>
                      <Text className="text-text-dim text-[10px]">
                        {f.section}
                      </Text>
                      <Text className="text-text-dim text-[10px]">
                        {(f.size / 1024).toFixed(1)}KB
                      </Text>
                    </View>
                  ))}
                </View>
              )}
            </Section>

            {/* 4. Recent Tool Calls */}
            <Section
              title="Recent Tool Calls"
              icon={Wrench}
              badge={`${data.tool_calls.length}`}
            >
              {data.tool_calls.length === 0 ? (
                <Text className="text-text-dim text-xs italic">
                  No recent tool calls
                </Text>
              ) : (
                <View className="gap-2">
                  {data.tool_calls.map((tc) => (
                    <ToolCallRow key={tc.id} tc={tc} />
                  ))}
                </View>
              )}
            </Section>

            {/* 5. Recent Trace Events */}
            <Section
              title="Recent Traces"
              icon={Activity}
              badge={`${data.trace_events.length}`}
            >
              {data.trace_events.length === 0 ? (
                <Text className="text-text-dim text-xs italic">
                  No recent trace events
                </Text>
              ) : (
                <View className="gap-2">
                  {data.trace_events.map((te) => (
                    <TraceRow key={te.id} te={te} />
                  ))}
                </View>
              )}
            </Section>
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
