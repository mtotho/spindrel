import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ChevronLeft, Trash2, Zap } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import {
  useMCPServer, useCreateMCPServer, useUpdateMCPServer, useDeleteMCPServer,
  useTestMCPServer, useTestMCPServerInline,
  type MCPServerTestResult,
} from "@/src/api/hooks/useMCPServers";
import { FormRow, TextInput, Section } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

function EnableToggle({ enabled, onChange, compact }: { enabled: boolean; onChange: (v: boolean) => void; compact?: boolean }) {
  const t = useThemeTokens();
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      style={{
        display: "flex", alignItems: "center", gap: compact ? 0 : 6,
        padding: compact ? "5px 6px" : "5px 12px", fontSize: 12, fontWeight: 600,
        border: "none", cursor: "pointer", borderRadius: 6, flexShrink: 0,
        background: enabled ? t.successSubtle : t.dangerSubtle,
        color: enabled ? t.success : t.danger,
      }}
    >
      <div style={{
        width: 28, height: 16, borderRadius: 8, position: "relative",
        background: enabled ? t.success : t.textDim,
        transition: "background 0.2s",
      }}>
        <div style={{
          width: 12, height: 12, borderRadius: 6, background: "#fff",
          position: "absolute", top: 2,
          left: enabled ? 14 : 2,
          transition: "left 0.2s",
        }} />
      </div>
      {!compact && (enabled ? "Enabled" : "Disabled")}
    </button>
  );
}

export default function MCPServerDetailScreen() {
  const t = useThemeTokens();
  const { serverId } = useLocalSearchParams<{ serverId: string }>();
  const isNew = serverId === "new";
  const goBack = useGoBack("/admin/mcp-servers");
  const { data: server, isLoading } = useMCPServer(isNew ? undefined : serverId);
  const createMut = useCreateMCPServer();
  const updateMut = useUpdateMCPServer(serverId);
  const deleteMut = useDeleteMCPServer();
  const testMut = useTestMCPServer();
  const testInlineMut = useTestMCPServerInline();

  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [testResult, setTestResult] = useState<MCPServerTestResult | null>(null);
  const [initialized, setInitialized] = useState(isNew);

  if (server && !initialized) {
    setDisplayName(server.display_name || "");
    setUrl(server.url || "");
    setIsEnabled(server.is_enabled);
    setInitialized(true);
  }

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!id.trim() || !displayName.trim() || !url.trim()) return;
      await createMut.mutateAsync({
        id: id.trim(), display_name: displayName.trim(), url: url.trim(),
        api_key: apiKey || undefined, is_enabled: isEnabled,
      });
      goBack();
    } else {
      await updateMut.mutateAsync({
        display_name: displayName.trim(), url: url.trim(),
        api_key: apiKey || undefined, is_enabled: isEnabled,
      });
    }
  }, [isNew, id, displayName, url, apiKey, isEnabled, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!serverId || !confirm("Delete this MCP server?")) return;
    await deleteMut.mutateAsync(serverId);
    goBack();
  }, [serverId, deleteMut, goBack]);

  const handleTest = useCallback(() => {
    setTestResult(null);
    const onSuccess = (r: MCPServerTestResult) => setTestResult(r);
    const onError = (err: any) => setTestResult({ ok: false, message: err?.message || "Failed", tool_count: 0, tools: [] });
    if (isNew) {
      testInlineMut.mutate({ url: url.trim(), api_key: apiKey || undefined }, { onSuccess, onError });
    } else {
      testMut.mutate(serverId, { onSuccess, onError });
    }
  }, [serverId, isNew, url, apiKey, testMut, testInlineMut]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew ? (id.trim() && displayName.trim() && url.trim()) : (displayName.trim() && url.trim());
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`, gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0, width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ChevronLeft size={22} color={t.textMuted} />
        </button>
        <span style={{ color: t.text, fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isNew ? "New MCP Server" : "Edit MCP Server"}
        </span>
        {!isNew && isWide && (
          <span style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace" }}>{serverId}</span>
        )}
        <div style={{ flex: 1 }} />
        <button
          onClick={handleTest}
          disabled={testMut.isPending || testInlineMut.isPending || (!isNew && !url.trim())}
          style={{
            display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
            padding: isWide ? "6px 14px" : "6px 8px", fontSize: 12, fontWeight: 600,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
            background: "transparent", color: t.textMuted, cursor: "pointer", flexShrink: 0,
          }}
        >
          <Zap size={13} />
          {isWide && ((testMut.isPending || testInlineMut.isPending) ? "Testing..." : "Test")}
        </button>
        {!isNew && (
          <button
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            title="Delete"
            style={{
              display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
              padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
              border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
              background: "transparent", color: t.danger, cursor: "pointer", flexShrink: 0,
            }}
          >
            <Trash2 size={14} />
            {isWide && "Delete"}
          </button>
        )}
        <EnableToggle enabled={isEnabled} onChange={setIsEnabled} compact={!isWide} />
        <button
          onClick={handleSave}
          disabled={isSaving || !canSave}
          style={{
            padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
            border: "none", borderRadius: 6, flexShrink: 0,
            background: !canSave ? t.surfaceBorder : t.accent,
            color: !canSave ? t.textDim : "#fff",
            cursor: !canSave ? "not-allowed" : "pointer",
          }}
        >
          {isSaving ? "..." : "Save"}
        </button>
      </div>

      {/* Error display */}
      {mutError && (
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* Test result banner */}
      {testResult && (
        <div style={{
          padding: "8px 20px", fontSize: 12, fontWeight: 600,
          background: testResult.ok ? t.successSubtle : t.dangerSubtle,
          color: testResult.ok ? t.success : t.danger,
          borderBottom: `1px solid ${t.surfaceOverlay}`,
        }}>
          {testResult.ok ? "\u2713" : "\u2717"} {testResult.message}
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        paddingVertical: isWide ? 20 : 12,
        paddingHorizontal: isWide ? 24 : 12,
        maxWidth: 700,
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <Section title="Identity">
            {isNew && (
              <FormRow label="Server ID" description="Unique slug bots reference, cannot be changed later">
                <TextInput value={id} onChangeText={setId} placeholder="e.g. homeassistant" style={{ fontFamily: "monospace" }} />
              </FormRow>
            )}
            <FormRow label="Display Name">
              <TextInput value={displayName} onChangeText={setDisplayName} placeholder="e.g. Home Assistant" />
            </FormRow>
          </Section>

          <Section title="Connection">
            <FormRow label="URL" description="MCP server HTTP endpoint">
              <TextInput value={url} onChangeText={setUrl} placeholder="https://mcp.example.com/mcp" />
            </FormRow>
            <FormRow label="API Key" description={!isNew && server?.has_api_key ? "Leave blank to keep existing" : undefined}>
              <TextInput
                value={apiKey}
                onChangeText={setApiKey}
                placeholder={!isNew && server?.has_api_key ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (unchanged)" : "Optional bearer token"}
                type="password"
              />
            </FormRow>
          </Section>

          {/* Discovered tools (after test) */}
          {testResult?.ok && testResult.tools.length > 0 && (
            <Section title="Discovered Tools" description={`${testResult.tool_count} tools available from this server`}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {testResult.tools.map((name) => (
                  <span
                    key={name}
                    style={{
                      padding: "3px 10px", borderRadius: 5, fontSize: 11,
                      fontFamily: "monospace", fontWeight: 500,
                      background: t.surfaceRaised, color: t.text,
                    }}
                  >
                    {name}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {!isNew && server && (
            <Section title="Info">
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>ID</span>
                  <span style={{ color: t.text, fontFamily: "monospace" }}>{server.id}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Source</span>
                  <span style={{ color: t.textMuted }}>{server.source}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>API Key</span>
                  <span style={{ color: server.has_api_key ? t.success : t.textDim }}>
                    {server.has_api_key ? "Set" : "Not set"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Created</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(server.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Updated</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(server.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
              </div>
            </Section>
          )}
        </div>
      </ScrollView>
    </View>
  );
}
