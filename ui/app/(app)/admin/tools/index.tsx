import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Wrench, Server, Cpu } from "lucide-react";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function TypeBadge({ tool }: { tool: ToolItem }) {
  if (tool.server_name) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(249,115,22,0.15)", color: "#fdba74",
      }}>
        mcp
      </span>
    );
  }
  if (tool.source_integration) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(168,85,247,0.15)", color: "#c4b5fd",
      }}>
        integration
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

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
}

function ToolRow({ tool, onPress, isWide }: { tool: ToolItem; onPress: () => void; isWide: boolean }) {
  const t = useThemeTokens();
  const desc = tool.description || "";
  const source = tool.server_name || tool.source_file || tool.source_dir || "";

  if (!isWide) {
    return (
      <button
        onClick={onPress}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${t.surfaceRaised}`, cursor: "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1, fontFamily: "monospace" }}>
            {tool.tool_name}
          </span>
          <TypeBadge tool={tool} />
        </div>
        {desc && (
          <div style={{
            fontSize: 11, color: t.textMuted,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {desc.slice(0, 120)}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: t.textDim }}>
          {source && <span style={{ fontFamily: "monospace" }}>{source}</span>}
        </div>
      </button>
    );
  }

  return (
    <button
      onClick={onPress}
      style={{
        display: "grid", gridTemplateColumns: "200px 1fr 90px 120px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        borderBottom: `1px solid ${t.surfaceRaised}`, cursor: "pointer",
        textAlign: "left", width: "100%", border: "none",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = t.inputBg)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <span style={{
        fontSize: 12, fontFamily: "monospace", color: t.text, fontWeight: 600,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {tool.tool_name}
      </span>
      <div style={{ overflow: "hidden" }}>
        <div style={{
          fontSize: 12, color: t.textMuted,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {desc || "\u2014"}
        </div>
        {source && (
          <div style={{
            fontSize: 10, color: t.textDim, fontFamily: "monospace",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            marginTop: 2,
          }}>
            {source}
          </div>
        )}
      </div>
      <TypeBadge tool={tool} />
      <span style={{ fontSize: 11, color: t.textDim, textAlign: "right" }}>
        {fmtDate(tool.indexed_at)}
      </span>
    </button>
  );
}

export default function ToolsScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: tools, isLoading } = useTools();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  // Group tools: local, integration, mcp
  const localTools = tools?.filter((t) => !t.server_name && !t.source_integration) ?? [];
  const integrationTools = tools?.filter((t) => !t.server_name && t.source_integration) ?? [];
  const mcpTools = tools?.filter((t) => t.server_name) ?? [];

  // Group MCP tools by server
  const mcpByServer = new Map<string, ToolItem[]>();
  for (const t of mcpTools) {
    const list = mcpByServer.get(t.server_name!) || [];
    list.push(t);
    mcpByServer.set(t.server_name!, list);
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Tools" subtitle={`${tools?.length ?? 0} indexed`} />

      {/* Table header (desktop only) */}
      {isWide && tools && tools.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "200px 1fr 90px 120px",
          gap: 12, padding: "8px 16px",
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: 1,
        }}>
          <span>Name</span>
          <span>Description</span>
          <span>Type</span>
          <span style={{ textAlign: "right" }}>Indexed</span>
        </div>
      )}

      {/* List */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }} contentContainerStyle={{
        padding: isWide ? 0 : 12,
        gap: isWide ? 0 : 8,
      }}>
        {(!tools || tools.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", color: t.textDim, fontSize: 13,
          }}>
            No tools indexed yet. Tools are indexed automatically on server startup.
          </div>
        )}

        {/* Local tools */}
        {localTools.length > 0 && !isWide && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 4px 4px", fontSize: 11, fontWeight: 600, color: t.textDim,
          }}>
            <Cpu size={12} color={t.textDim} />
            Local ({localTools.length})
          </div>
        )}
        {localTools.map((tool) => (
          <ToolRow
            key={tool.id}
            tool={tool}
            isWide={isWide}
            onPress={() => router.push(`/admin/tools/${encodeURIComponent(tool.tool_name)}` as any)}
          />
        ))}

        {/* Integration tools */}
        {integrationTools.length > 0 && !isWide && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "12px 4px 4px", fontSize: 11, fontWeight: 600, color: t.textDim,
          }}>
            <Wrench size={12} color={t.textDim} />
            Integration ({integrationTools.length})
          </div>
        )}
        {integrationTools.map((tool) => (
          <ToolRow
            key={tool.id}
            tool={tool}
            isWide={isWide}
            onPress={() => router.push(`/admin/tools/${encodeURIComponent(tool.tool_name)}` as any)}
          />
        ))}

        {/* MCP tools by server */}
        {[...mcpByServer.entries()].map(([server, serverTools]) => (
          <div key={server}>
            {!isWide && (
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "12px 4px 4px", fontSize: 11, fontWeight: 600, color: t.textDim,
              }}>
                <Server size={12} color={t.textDim} />
                {server} ({serverTools.length})
              </div>
            )}
            {serverTools.map((tool) => (
              <ToolRow
                key={tool.id}
                tool={tool}
                isWide={isWide}
                onPress={() => router.push(`/admin/tools/${encodeURIComponent(tool.tool_key)}` as any)}
              />
            ))}
          </div>
        ))}
      </RefreshableScrollView>
    </View>
  );
}
