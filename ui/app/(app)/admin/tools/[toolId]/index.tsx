import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ChevronLeft } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useTool } from "@/src/api/hooks/useTools";
import { Section } from "@/src/components/shared/FormControls";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: "#666" }}>{label}</span>
      <span style={{
        fontSize: 11, color: "#ccc", fontFamily: "monospace",
        maxWidth: "60%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "right",
      }}>{value}</span>
    </div>
  );
}

function TypeBadge({ tool }: { tool: { server_name?: string | null; source_integration?: string | null } }) {
  if (tool.server_name) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(249,115,22,0.15)", color: "#fdba74",
      }}>
        mcp:{tool.server_name}
      </span>
    );
  }
  if (tool.source_integration) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(168,85,247,0.15)", color: "#c4b5fd",
      }}>
        integration:{tool.source_integration}
      </span>
    );
  }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: "rgba(59,130,246,0.15)", color: "#93c5fd",
    }}>
      local
    </span>
  );
}

function ParamRow({ name, param, required }: { name: string; param: any; required: boolean }) {
  const type = param.type || (param.enum ? "enum" : "any");
  return (
    <div style={{
      display: "flex", gap: 8, padding: "6px 0",
      borderBottom: "1px solid #1a1a1a",
      alignItems: "flex-start",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 140, flexShrink: 0 }}>
        <span style={{ fontSize: 12, fontFamily: "monospace", color: "#e5e5e5", fontWeight: 600 }}>
          {name}
        </span>
        {required && (
          <span style={{ fontSize: 9, color: "#f87171", fontWeight: 700 }}>REQ</span>
        )}
      </div>
      <span style={{ fontSize: 11, color: "#93c5fd", fontFamily: "monospace", flexShrink: 0 }}>
        {type}
        {param.enum && `: ${param.enum.join(" | ")}`}
      </span>
      {param.description && (
        <span style={{ fontSize: 11, color: "#888", flex: 1 }}>
          {param.description}
        </span>
      )}
    </div>
  );
}

export default function ToolDetailScreen() {
  const { toolId } = useLocalSearchParams<{ toolId: string }>();
  const goBack = useGoBack("/admin/tools");
  const { data: tool, isLoading } = useTool(toolId);
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  if (!tool) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <span style={{ color: "#666", fontSize: 13 }}>Tool not found</span>
      </View>
    );
  }

  const params = tool.parameters?.properties || {};
  const requiredParams = new Set<string>(tool.parameters?.required || []);
  const paramNames = Object.keys(params);
  const fullSchema = tool.schema_ || {};

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: "1px solid #333", gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}>
          <ChevronLeft size={22} color="#999" />
        </button>
        <span style={{
          color: "#e5e5e5", fontSize: 14, fontWeight: 700, fontFamily: "monospace", flexShrink: 0,
        }}>
          {tool.tool_name}
        </span>
        <TypeBadge tool={tool} />
        <div style={{ flex: 1 }} />
      </div>

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        ...(isWide ? { flexDirection: "row" } : {}),
      }}>
        {/* Main content */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: "1px solid #2a2a2a" } : {}),
          display: "flex", flexDirection: "column", gap: 20,
          padding: isWide ? "16px 20px" : "12px 12px",
        }}>
          {/* Description */}
          {tool.description && (
            <Section title="Description">
              <div style={{
                fontSize: 13, color: "#ccc", lineHeight: 1.6,
                padding: "8px 12px", background: "#111", borderRadius: 8,
                border: "1px solid #222",
              }}>
                {tool.description}
              </div>
            </Section>
          )}

          {/* Parameters */}
          <Section title={`Parameters (${paramNames.length})`}>
            {paramNames.length === 0 ? (
              <div style={{ fontSize: 12, color: "#555", padding: "8px 0" }}>
                No parameters
              </div>
            ) : (
              <div style={{
                background: "#111", borderRadius: 8, border: "1px solid #222",
                padding: "4px 12px",
              }}>
                {paramNames.map((name) => (
                  <ParamRow
                    key={name}
                    name={name}
                    param={params[name]}
                    required={requiredParams.has(name)}
                  />
                ))}
              </div>
            )}
          </Section>

          {/* Full schema */}
          <Section title="Full Schema (JSON)">
            <pre style={{
              background: "#0a0a0a", border: "1px solid #222", borderRadius: 8,
              padding: 12, fontSize: 11, lineHeight: 1.5,
              color: "#999", fontFamily: "monospace",
              overflow: "auto", maxHeight: 500,
              whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>
              {JSON.stringify(fullSchema, null, 2)}
            </pre>
          </Section>
        </div>

        {/* Sidebar info */}
        <div style={{
          ...(isWide ? { flex: 1.2, minWidth: 240 } : {}),
          padding: isWide ? "16px 20px" : "12px 12px",
          borderTop: isWide ? "none" : "1px solid #2a2a2a",
        }}>
          <Section title="Info">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <InfoRow label="Tool Key" value={tool.tool_key} />
              <InfoRow label="Type" value={tool.server_name ? "MCP" : tool.source_integration ? "Integration" : "Local"} />
              {tool.server_name && <InfoRow label="MCP Server" value={tool.server_name} />}
              {tool.source_integration && <InfoRow label="Integration" value={tool.source_integration} />}
              {tool.source_file && <InfoRow label="Source File" value={tool.source_file} />}
              {tool.source_dir && <InfoRow label="Source Dir" value={tool.source_dir} />}
              <InfoRow label="Indexed" value={fmtDate(tool.indexed_at)} />
            </div>
          </Section>
        </div>
      </ScrollView>
    </View>
  );
}
