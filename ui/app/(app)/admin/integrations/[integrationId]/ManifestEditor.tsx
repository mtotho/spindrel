/**
 * Integration manifest editor — Home Assistant-style Visual/YAML toggle.
 *
 * Both views read/write the same DB manifest. Switching between them
 * reflects changes immediately (full round-trip).
 */
import { useState, useCallback, useEffect, useRef } from "react";
import { View, ActivityIndicator } from "react-native";
import {
  Server, CheckCircle, XCircle,
  Copy, Check, AlertTriangle, RefreshCw,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useIntegrationYaml,
  useUpdateIntegrationYaml,
  useIntegrationManifest,
} from "@/src/api/hooks/useIntegrations";
import { useMCPServers, useTestMCPServer } from "@/src/api/hooks/useMCPServers";
import { YamlSyntaxEditor } from "@/app/(app)/admin/workflows/YamlEditor";
import { writeToClipboard } from "@/src/utils/clipboard";
import { SectionBox } from "./index";
import yaml from "js-yaml";

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

type ViewMode = "visual" | "yaml";

function ViewToggle({
  mode,
  onChange,
}: {
  mode: ViewMode;
  onChange: (m: ViewMode) => void;
}) {
  const t = useThemeTokens();
  const tabs: { key: ViewMode; label: string }[] = [
    { key: "visual", label: "Visual" },
    { key: "yaml", label: "YAML" },
  ];

  return (
    <div style={{ display: "flex", gap: 0, borderRadius: 6, overflow: "hidden", border: `1px solid ${t.surfaceBorder}` }}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          style={{
            padding: "6px 16px",
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: 0.3,
            textTransform: "uppercase",
            border: "none",
            cursor: "pointer",
            background: mode === tab.key ? t.accent : "transparent",
            color: mode === tab.key ? "#fff" : t.textDim,
            transition: "all 0.15s",
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Server Card
// ---------------------------------------------------------------------------

interface MCPServerInfo {
  id: string;
  display_name?: string;
  url?: string;
  image?: string;
  port?: number;
  connected?: boolean;
  url_configured?: boolean;
}

function MCPServerCard({ server }: { server: MCPServerInfo }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const testMut = useTestMCPServer();

  const isConnected = server.connected;
  const needsSetup = server.image && !server.url;

  const handleTest = () => {
    testMut.mutate(server.id);
  };

  const dockerCmd = server.image
    ? `docker run -d --name spindrel-mcp-${server.id} -p ${server.port || 3000}:${server.port || 3000} ${server.image}`
    : null;

  const handleCopyCmd = async () => {
    if (dockerCmd) {
      await writeToClipboard(dockerCmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div
      style={{
        background: t.surfaceRaised,
        borderRadius: 8,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Server size={14} color={t.textDim} />
        <span style={{ fontSize: 12, fontWeight: 600, color: t.text, flex: 1 }}>
          {server.display_name || server.id}
        </span>
        {/* Status dot */}
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            background: isConnected ? "#22c55e" : needsSetup ? "#f59e0b" : "#ef4444",
          }}
        />
        <span style={{ fontSize: 10, color: t.textDim }}>
          {isConnected ? "Connected" : needsSetup ? "Setup required" : "Disconnected"}
        </span>
      </div>

      {/* URL / image info */}
      {server.url && (
        <div style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted }}>
          {server.url}
        </div>
      )}

      {/* Setup instructions for container-based servers */}
      {needsSetup && (
        <div
          style={{
            background: "rgba(245,158,11,0.08)",
            borderRadius: 6,
            padding: 10,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <AlertTriangle size={12} color="#f59e0b" />
            <span style={{ fontSize: 11, fontWeight: 600, color: "#f59e0b" }}>
              This MCP server needs to be running
            </span>
          </div>
          {dockerCmd && (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <code
                style={{
                  fontSize: 10,
                  fontFamily: "monospace",
                  color: t.textMuted,
                  background: t.surface,
                  padding: "4px 8px",
                  borderRadius: 4,
                  flex: 1,
                  overflowX: "auto",
                  whiteSpace: "nowrap",
                }}
              >
                {dockerCmd}
              </code>
              <button
                onClick={handleCopyCmd}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 4,
                  display: "flex",
                  flexShrink: 0,
                }}
                title="Copy command"
              >
                {copied ? (
                  <Check size={12} color="#22c55e" />
                ) : (
                  <Copy size={12} color={t.textDim} />
                )}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Test button */}
      <div style={{ display: "flex", gap: 6 }}>
        <button
          onClick={handleTest}
          disabled={testMut.isPending || !server.url}
          style={{
            padding: "4px 12px",
            fontSize: 10,
            fontWeight: 600,
            borderRadius: 4,
            border: `1px solid ${t.surfaceBorder}`,
            background: "transparent",
            color: t.textDim,
            cursor: !server.url ? "not-allowed" : "pointer",
            opacity: !server.url ? 0.5 : 1,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <RefreshCw size={10} />
          Test Connection
        </button>
        {testMut.isSuccess && (
          <span style={{ fontSize: 10, color: "#22c55e", display: "flex", alignItems: "center", gap: 4 }}>
            <CheckCircle size={10} /> Connected
          </span>
        )}
        {testMut.isError && (
          <span style={{ fontSize: 10, color: "#ef4444", display: "flex", alignItems: "center", gap: 4 }}>
            <XCircle size={10} /> Failed
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Servers Section
// ---------------------------------------------------------------------------

function MCPServersSection({ servers }: { servers: MCPServerInfo[] }) {
  if (!servers || servers.length === 0) return null;

  return (
    <SectionBox title={`MCP Servers (${servers.length})`}>
      {servers.map((srv) => (
        <MCPServerCard key={srv.id} server={srv} />
      ))}
    </SectionBox>
  );
}

// ---------------------------------------------------------------------------
// YAML Editor Tab
// ---------------------------------------------------------------------------

function YamlEditorTab({
  integrationId,
  onManifestChange,
}: {
  integrationId: string;
  onManifestChange?: () => void;
}) {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrationYaml(integrationId);
  const updateMut = useUpdateIntegrationYaml(integrationId);
  const [draft, setDraft] = useState<string>("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const prevIdRef = useRef(integrationId);
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Initialize draft from fetched YAML, reset when integrationId changes
  useEffect(() => {
    if (prevIdRef.current !== integrationId) {
      prevIdRef.current = integrationId;
      setDraft("");
      setParseError(null);
      setSaved(false);
    }
    if (data?.yaml && draft === "") {
      setDraft(data.yaml);
    }
  }, [data, integrationId, draft]);

  const handleChange = useCallback((text: string) => {
    setDraft(text);
    setSaved(false);
    // Debounce YAML validation to avoid jank on large files
    if (validateTimer.current) clearTimeout(validateTimer.current);
    validateTimer.current = setTimeout(() => {
      try {
        yaml.load(text);
        setParseError(null);
      } catch (e: any) {
        setParseError(e.message || "Invalid YAML");
      }
    }, 300);
  }, []);

  const handleSave = useCallback(() => {
    if (parseError) return;
    updateMut.mutate(draft, {
      onSuccess: () => {
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
        onManifestChange?.();
      },
    });
  }, [draft, parseError, updateMut, onManifestChange]);

  if (isLoading) {
    return (
      <div style={{ padding: 20, display: "flex", justifyContent: "center" }}>
        <ActivityIndicator color={t.accent} />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Save bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button
          onClick={handleSave}
          disabled={!!parseError || updateMut.isPending}
          style={{
            padding: "6px 16px",
            fontSize: 11,
            fontWeight: 600,
            borderRadius: 6,
            border: "none",
            background: parseError ? t.surfaceBorder : t.accent,
            color: "#fff",
            cursor: parseError ? "not-allowed" : "pointer",
            opacity: updateMut.isPending ? 0.6 : 1,
          }}
        >
          {updateMut.isPending ? "Saving..." : "Save"}
        </button>
        {saved && (
          <span style={{ fontSize: 11, color: "#22c55e", display: "flex", alignItems: "center", gap: 4 }}>
            <CheckCircle size={12} /> Saved
          </span>
        )}
        {updateMut.isError && (
          <span style={{ fontSize: 11, color: "#ef4444" }}>
            Failed to save
          </span>
        )}
      </div>

      {/* Editor */}
      <YamlSyntaxEditor
        value={draft}
        onChange={handleChange}
        parseError={parseError}
        t={t}
        minHeight={500}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Export
// ---------------------------------------------------------------------------

export function ManifestEditor({ integrationId }: { integrationId: string }) {
  const t = useThemeTokens();
  const [mode, setMode] = useState<ViewMode>("visual");
  const { data: manifestData } = useIntegrationManifest(integrationId);

  const manifest = manifestData?.manifest;
  const mcpServers = (manifest?.mcp_servers as MCPServerInfo[] | undefined) ?? [];
  const fileDrift = manifest?._file_drift as { drifted: boolean; reason: string } | undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Tab toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <ViewToggle mode={mode} onChange={setMode} />
        {fileDrift?.drifted && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              fontSize: 10,
              color: "#f59e0b",
            }}
          >
            <AlertTriangle size={10} />
            Source file has changed on disk
          </div>
        )}
      </div>

      {/* Content */}
      {mode === "visual" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* MCP servers section */}
          {mcpServers.length > 0 && <MCPServersSection servers={mcpServers} />}
        </div>
      ) : (
        <YamlEditorTab integrationId={integrationId} />
      )}
    </div>
  );
}
