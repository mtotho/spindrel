import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState } from "react";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Plus, ExternalLink } from "lucide-react";
import { useMCPServers, useTestMCPServer, type MCPServerItem } from "@/src/api/hooks/useMCPServers";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function SourceBadge({ source }: { source: string }) {
  const t = useThemeTokens();
  const isFile = source === "file";
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: isFile ? "rgba(59,130,246,0.15)" : "rgba(100,100,100,0.15)",
      color: isFile ? "#2563eb" : "#999",
      whiteSpace: "nowrap",
    }}>
      {source}
    </span>
  );
}

function ServerCard({ server, onClick, isWide }: { server: MCPServerItem; onClick: () => void; isWide: boolean }) {
  const t = useThemeTokens();
  const testMut = useTestMCPServer();
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; tool_count?: number } | null>(null);

  const handleTest = (e: React.MouseEvent) => {
    e.stopPropagation();
    setTestResult(null);
    testMut.mutate(server.id, {
      onSuccess: (r) => setTestResult(r),
      onError: (err) => setTestResult({ ok: false, message: (err as any)?.message || "Failed" }),
    });
  };

  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", flexDirection: "column", gap: 10,
        padding: isWide ? "16px 20px" : "12px 14px",
        background: t.inputBg, borderRadius: 10,
        border: `1px solid ${server.is_enabled ? t.surfaceRaised : t.dangerBorder}`,
        cursor: "pointer", textAlign: "left", width: "100%",
        opacity: server.is_enabled ? 1 : 0.6,
      }}
    >
      {/* Top row: name + source + enabled */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 8, height: 8, borderRadius: 4, flexShrink: 0,
          background: server.is_enabled ? t.success : t.danger,
        }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: t.text, flex: 1 }}>
          {server.display_name}
        </span>
        <SourceBadge source={server.source} />
      </div>

      {/* Info row */}
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 12, fontSize: 11, color: t.textDim }}>
        <span style={{ fontFamily: "monospace" }}>{server.id}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
          <ExternalLink size={10} />
          {server.url.replace(/^https?:\/\//, "").slice(0, 40)}
        </span>
        {server.has_api_key && <span style={{ color: t.textDim }}>API key set</span>}
      </div>

      {/* Test button + result */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2 }}>
        <button
          onClick={handleTest}
          disabled={testMut.isPending}
          style={{
            padding: "4px 12px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
            background: "transparent", color: t.textMuted, cursor: "pointer",
          }}
        >
          {testMut.isPending ? "Testing..." : "Test Connection"}
        </button>
        {testResult && (
          <span style={{
            fontSize: 11, fontWeight: 600,
            color: testResult.ok ? t.success : t.danger,
          }}>
            {testResult.ok ? "\u2713" : "\u2717"} {testResult.message}
          </span>
        )}
      </div>
    </button>
  );
}

export default function MCPServersScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: servers, isLoading } = useMCPServers();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <div className="flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="MCP Servers"
        right={
          <button
            onClick={() => navigate("/admin/mcp-servers/new")}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: t.accent, color: "#fff", cursor: "pointer",
            }}
          >
            <Plus size={14} />
            New Server
          </button>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
        {(!servers || servers.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", fontSize: 13,
          }}>
            <div style={{ color: t.textDim, marginBottom: 8 }}>No MCP servers configured.</div>
            <div style={{ color: t.textDim, fontSize: 12 }}>
              Add an MCP server above, or place a <code style={{ color: t.textDim }}>mcp.yaml</code> file in the server root to auto-seed on first boot.
            </div>
          </div>
        )}

        {servers && servers.length > 0 && (
          <div style={{
            display: "grid",
            gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(380px, 1fr))" : "1fr",
            gap: isWide ? 12 : 10,
          }}>
            {servers.map((s) => (
              <ServerCard
                key={s.id}
                server={s}
                isWide={isWide}
                onClick={() => navigate(`/admin/mcp-servers/${s.id}`)}
              />
            ))}
          </div>
        )}
      </RefreshableScrollView>
    </div>
  );
}
