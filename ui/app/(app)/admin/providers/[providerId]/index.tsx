import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ChevronLeft, Trash2, Zap } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useQueryClient } from "@tanstack/react-query";
import {
  useProvider, useCreateProvider, useUpdateProvider, useDeleteProvider, useTestProvider, useTestProviderInline,
} from "@/src/api/hooks/useProviders";
import { FormRow, TextInput, SelectInput, Toggle, Section, Row, Col } from "@/src/components/shared/FormControls";

const PROVIDER_TYPE_OPTIONS = [
  { label: "LiteLLM", value: "litellm" },
  { label: "OpenAI", value: "openai" },
  { label: "OpenAI Compatible", value: "openai-compatible" },
  { label: "Anthropic", value: "anthropic" },
  { label: "Anthropic Compatible", value: "anthropic-compatible" },
  { label: "Anthropic Subscription", value: "anthropic-subscription" },
];

function EnableToggle({ enabled, onChange, compact }: { enabled: boolean; onChange: (v: boolean) => void; compact?: boolean }) {
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      style={{
        display: "flex", alignItems: "center", gap: compact ? 0 : 6,
        padding: compact ? "5px 6px" : "5px 12px", fontSize: 12, fontWeight: 600,
        border: "none", cursor: "pointer", borderRadius: 6, flexShrink: 0,
        background: enabled ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)",
        color: enabled ? "#86efac" : "#fca5a5",
      }}
    >
      <div style={{
        width: 28, height: 16, borderRadius: 8, position: "relative",
        background: enabled ? "#22c55e" : "#555",
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

export default function ProviderDetailScreen() {
  const { providerId } = useLocalSearchParams<{ providerId: string }>();
  const isNew = providerId === "new";
  const goBack = useGoBack("/admin/providers");
  const qc = useQueryClient();
  const { data: provider, isLoading } = useProvider(isNew ? undefined : providerId);
  const createMut = useCreateProvider();
  const updateMut = useUpdateProvider(providerId);
  const deleteMut = useDeleteProvider();
  const testMut = useTestProvider();
  const testInlineMut = useTestProviderInline();

  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [providerType, setProviderType] = useState("litellm");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [tpmLimit, setTpmLimit] = useState("");
  const [rpmLimit, setRpmLimit] = useState("");
  const [credentialsPath, setCredentialsPath] = useState("");
  const [managementKey, setManagementKey] = useState("");
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [initialized, setInitialized] = useState(isNew);

  if (provider && !initialized) {
    setDisplayName(provider.display_name || "");
    setProviderType(provider.provider_type || "litellm");
    setBaseUrl(provider.base_url || "");
    setIsEnabled(provider.is_enabled);
    setTpmLimit(provider.tpm_limit ? String(provider.tpm_limit) : "");
    setRpmLimit(provider.rpm_limit ? String(provider.rpm_limit) : "");
    setCredentialsPath(provider.config?.credentials_path || "");
    setInitialized(true);
  }

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!id.trim() || !displayName.trim()) return;
      await createMut.mutateAsync({
        id: id.trim(), display_name: displayName.trim(), provider_type: providerType,
        api_key: apiKey || undefined, base_url: baseUrl || undefined,
        is_enabled: isEnabled,
        tpm_limit: tpmLimit ? parseInt(tpmLimit) : null,
        rpm_limit: rpmLimit ? parseInt(rpmLimit) : null,
        credentials_path: credentialsPath || undefined,
        management_key: managementKey || undefined,
      });
      goBack();
    } else {
      await updateMut.mutateAsync({
        display_name: displayName.trim(), provider_type: providerType,
        api_key: apiKey || undefined, base_url: baseUrl || undefined,
        is_enabled: isEnabled,
        tpm_limit: tpmLimit ? parseInt(tpmLimit) : undefined,
        rpm_limit: rpmLimit ? parseInt(rpmLimit) : undefined,
        clear_tpm_limit: !tpmLimit,
        clear_rpm_limit: !rpmLimit,
        credentials_path: credentialsPath || undefined,
        management_key: managementKey || undefined,
      });
    }
  }, [isNew, id, displayName, providerType, apiKey, baseUrl, isEnabled, tpmLimit, rpmLimit, credentialsPath, managementKey, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!providerId || !confirm("Delete this provider?")) return;
    await deleteMut.mutateAsync(providerId);
    goBack();
  }, [providerId, deleteMut, goBack]);

  const handleTest = useCallback(() => {
    setTestResult(null);
    const onSuccess = (r: { ok: boolean; message: string }) => setTestResult(r);
    const onError = (err: any) => setTestResult({ ok: false, message: err?.message || "Failed" });
    if (isNew) {
      testInlineMut.mutate({
        provider_type: providerType,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
        credentials_path: credentialsPath || undefined,
      }, { onSuccess, onError });
    } else {
      testMut.mutate(providerId, { onSuccess, onError });
    }
  }, [providerId, isNew, providerType, apiKey, baseUrl, credentialsPath, testMut, testInlineMut]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew ? (id.trim() && displayName.trim()) : displayName.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  // Fields visible per provider type
  const showApiKey = providerType !== "anthropic-subscription";
  const showBaseUrl = ["litellm", "openai", "openai-compatible", "anthropic-compatible"].includes(providerType);
  const showCredentialsPath = providerType === "anthropic-subscription";
  const showManagementKey = providerType === "litellm";

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: "1px solid #333", gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0, width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ChevronLeft size={22} color="#999" />
        </button>
        <span style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isNew ? "New Provider" : "Edit Provider"}
        </span>
        {!isNew && isWide && (
          <span style={{ color: "#555", fontSize: 11, fontFamily: "monospace" }}>{providerId}</span>
        )}
        <div style={{ flex: 1 }} />
        <button
          onClick={handleTest}
          disabled={testMut.isPending || testInlineMut.isPending}
          style={{
            display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
            padding: isWide ? "6px 14px" : "6px 8px", fontSize: 12, fontWeight: 600,
            border: "1px solid #333", borderRadius: 6,
            background: "transparent", color: "#999", cursor: "pointer", flexShrink: 0,
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
              border: "1px solid #7f1d1d", borderRadius: 6,
              background: "transparent", color: "#fca5a5", cursor: "pointer", flexShrink: 0,
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
            background: !canSave ? "#333" : "#3b82f6",
            color: !canSave ? "#666" : "#fff",
            cursor: !canSave ? "not-allowed" : "pointer",
          }}
        >
          {isSaving ? "..." : "Save"}
        </button>
      </div>

      {/* Error display */}
      {mutError && (
        <div style={{ padding: "8px 20px", background: "#7f1d1d", color: "#fca5a5", fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* Test result banner */}
      {testResult && (
        <div style={{
          padding: "8px 20px", fontSize: 12, fontWeight: 600,
          background: testResult.ok ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
          color: testResult.ok ? "#86efac" : "#fca5a5",
          borderBottom: "1px solid #222",
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
              <FormRow label="Provider ID" description="Unique slug, cannot be changed later">
                <TextInput value={id} onChangeText={setId} placeholder="e.g. my-litellm" style={{ fontFamily: "monospace" }} />
              </FormRow>
            )}
            <FormRow label="Display Name">
              <TextInput value={displayName} onChangeText={setDisplayName} placeholder="e.g. My LiteLLM Proxy" />
            </FormRow>
            <FormRow label="Provider Type">
              <SelectInput value={providerType} onChange={setProviderType} options={PROVIDER_TYPE_OPTIONS} />
            </FormRow>
          </Section>

          <Section title="Connection">
            {showApiKey && (
              <FormRow label="API Key" description={!isNew && provider?.has_api_key ? "Leave blank to keep existing" : undefined}>
                <TextInput
                  value={apiKey}
                  onChangeText={setApiKey}
                  placeholder={!isNew && provider?.has_api_key ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (unchanged)" : "sk-..."}
                  type="password"
                />
              </FormRow>
            )}
            {showBaseUrl && (
              <FormRow label="Base URL" description={
                providerType === "litellm" ? "URL of your LiteLLM proxy" :
                providerType === "openai-compatible" ? "Base URL of the OpenAI-compatible API (required)" :
                providerType === "anthropic-compatible" ? "Base URL of the Anthropic-compatible API (required)" :
                "Optional, uses default if blank"
              }>
                <TextInput value={baseUrl} onChangeText={setBaseUrl} placeholder={
                  providerType === "openai-compatible" ? "https://api.minimax.chat/v1" :
                  providerType === "anthropic-compatible" ? "https://api.minimax.chat/v1" :
                  "https://litellm.example.com"
                } />
              </FormRow>
            )}
            {showCredentialsPath && (
              <FormRow label="Credentials Path" description="Path to Claude credentials JSON file">
                <TextInput value={credentialsPath} onChangeText={setCredentialsPath} placeholder="~/.claude/.credentials.json" />
              </FormRow>
            )}
            {showManagementKey && (
              <FormRow label="Management Key" description="LiteLLM management key for model listing">
                <TextInput value={managementKey} onChangeText={setManagementKey} placeholder="Optional" type="password" />
              </FormRow>
            )}
          </Section>

          <Section title="Rate Limits" description="Optional per-provider rate limiting">
            <Row>
              <Col>
                <FormRow label="TPM Limit" description="Tokens per minute">
                  <TextInput value={tpmLimit} onChangeText={setTpmLimit} placeholder="No limit" type="number" />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="RPM Limit" description="Requests per minute">
                  <TextInput value={rpmLimit} onChangeText={setRpmLimit} placeholder="No limit" type="number" />
                </FormRow>
              </Col>
            </Row>
          </Section>

          {!isNew && provider && (
            <Section title="Info">
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#666" }}>ID</span>
                  <span style={{ color: "#ccc", fontFamily: "monospace" }}>{provider.id}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#666" }}>API Key</span>
                  <span style={{ color: provider.has_api_key ? "#86efac" : "#666" }}>
                    {provider.has_api_key ? "Set" : "Not set"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#666" }}>Created</span>
                  <span style={{ color: "#888" }}>
                    {new Date(provider.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#666" }}>Updated</span>
                  <span style={{ color: "#888" }}>
                    {new Date(provider.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
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
