import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useCallback, useEffect } from "react";

import { useParams } from "react-router-dom";
import { Trash2, Zap, Plus, X } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useQueryClient } from "@tanstack/react-query";
import {
  useProvider, useCreateProvider, useUpdateProvider, useDeleteProvider, useTestProvider, useTestProviderInline,
  useProviderModels, useAddProviderModel, useDeleteProviderModel, useUpdateProviderModel,
  useProviderTypeCapabilities, useDeleteRemoteModel,
  useOpenAIOAuthStatus, useStartOpenAIOAuth, usePollOpenAIOAuth, useDisconnectOpenAIOAuth,
  type ProviderModelItem,
} from "@/src/api/hooks/useProviders";
import { FormRow, TextInput, SelectInput, Toggle, Section, Row, Col } from "@/src/components/shared/FormControls";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { useThemeTokens } from "@/src/theme/tokens";
import { ProviderCapabilitySections } from "./ProviderCapabilitySections";
import { OpenAISubscriptionSection } from "./OpenAISubscriptionSection";
import { ProviderExtraHeadersSection } from "./ProviderExtraHeadersSection";

const PROVIDER_TYPE_OPTIONS = [
  { label: "LiteLLM", value: "litellm" },
  { label: "OpenAI", value: "openai" },
  { label: "OpenAI Compatible", value: "openai-compatible" },
  { label: "OpenAI (ChatGPT subscription)", value: "openai-subscription" },
  { label: "Anthropic", value: "anthropic" },
  { label: "Anthropic Compatible", value: "anthropic-compatible" },
  { label: "Ollama", value: "ollama" },
];

function EnableToggle({ enabled, onChange, compact }: { enabled: boolean; onChange: (v: boolean) => void; compact?: boolean }) {
  const t = useThemeTokens();
  return (
    <button
      onClick={() => onChange(!enabled)}
      title={enabled ? "Enabled" : "Disabled"}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: compact ? 0 : 6,
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

export default function ProviderDetailScreen() {
  const t = useThemeTokens();
  const { providerId } = useParams<{ providerId: string }>();
  const isNew = providerId === "new";
  const goBack = useGoBack("/admin/providers");
  const qc = useQueryClient();
  const { data: provider, isLoading } = useProvider(isNew ? undefined : providerId);
  const createMut = useCreateProvider();
  const updateMut = useUpdateProvider(providerId);
  const deleteMut = useDeleteProvider();
  const testMut = useTestProvider();
  const testInlineMut = useTestProviderInline();

  const { width } = useWindowSize();
  const isWide = width >= 768;

  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [providerType, setProviderType] = useState("litellm");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [tpmLimit, setTpmLimit] = useState("");
  const [rpmLimit, setRpmLimit] = useState("");
  const [managementKey, setManagementKey] = useState("");
  const [billingType, setBillingType] = useState("usage");
  const [planCost, setPlanCost] = useState("");
  const [planPeriod, setPlanPeriod] = useState("monthly");
  const [extraHeaders, setExtraHeaders] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [initialized, setInitialized] = useState(isNew);

  // Models
  const { data: providerModels, isLoading: modelsLoading } = useProviderModels(isNew ? undefined : providerId);
  const addModelMut = useAddProviderModel(providerId);
  const deleteModelMut = useDeleteProviderModel(providerId);
  const updateModelMut = useUpdateProviderModel(providerId);
  const deleteRemoteMut = useDeleteRemoteModel(isNew ? undefined : providerId);
  const [newModelId, setNewModelId] = useState("");
  const [newModelDisplay, setNewModelDisplay] = useState("");
  const [newModelMaxTokens, setNewModelMaxTokens] = useState("");
  const [newModelInputCost, setNewModelInputCost] = useState("");
  const [newModelOutputCost, setNewModelOutputCost] = useState("");
  const [newModelNoSysMsg, setNewModelNoSysMsg] = useState(false);
  const [newModelNoTools, setNewModelNoTools] = useState(false);
  const [newModelReasoning, setNewModelReasoning] = useState(false);
  const [newModelPromptStyle, setNewModelPromptStyle] = useState<"markdown" | "xml" | "structured">("markdown");
  const [editingModelId, setEditingModelId] = useState<number | null>(null);
  const [editModelDisplay, setEditModelDisplay] = useState("");
  const [editModelMaxTokens, setEditModelMaxTokens] = useState("");
  const [editModelContextWindow, setEditModelContextWindow] = useState("");
  const [editModelMaxOutputTokens, setEditModelMaxOutputTokens] = useState("");
  const [editModelInputCost, setEditModelInputCost] = useState("");
  const [editModelOutputCost, setEditModelOutputCost] = useState("");
  const [editModelCachedInputCost, setEditModelCachedInputCost] = useState("");
  const [editModelNoSysMsg, setEditModelNoSysMsg] = useState(false);
  const [editModelSupportsTools, setEditModelSupportsTools] = useState(true);
  const [editModelSupportsVision, setEditModelSupportsVision] = useState(true);
  const [editModelReasoning, setEditModelReasoning] = useState(false);
  const [editModelPromptCaching, setEditModelPromptCaching] = useState(false);
  const [editModelStructuredOutput, setEditModelStructuredOutput] = useState(false);
  const [editModelImageGen, setEditModelImageGen] = useState(false);
  const [editModelPromptStyle, setEditModelPromptStyle] = useState<"markdown" | "xml" | "structured">("markdown");
  const [editModelExtraBody, setEditModelExtraBody] = useState("");
  const [editModelExtraBodyError, setEditModelExtraBodyError] = useState<string | null>(null);
  const { confirm, ConfirmDialogSlot } = useConfirm();

  useEffect(() => {
    if (!provider || initialized) return;

    setDisplayName(provider.display_name || "");
    setProviderType(provider.provider_type || "litellm");
    setBaseUrl(provider.base_url || "");
    setIsEnabled(provider.is_enabled);
    setTpmLimit(provider.tpm_limit ? String(provider.tpm_limit) : "");
    setRpmLimit(provider.rpm_limit ? String(provider.rpm_limit) : "");
    setBillingType(provider.billing_type || "usage");
    setPlanCost(provider.plan_cost ? String(provider.plan_cost) : "");
    setPlanPeriod(provider.plan_period || "monthly");
    const cfgHeaders = provider.config?.extra_headers;
    setExtraHeaders(
      cfgHeaders && typeof cfgHeaders === "object" && !Array.isArray(cfgHeaders)
        ? Object.fromEntries(
            Object.entries(cfgHeaders as Record<string, unknown>).map(([k, v]) => [k, String(v ?? "")])
          )
        : {}
    );
    setInitialized(true);
  }, [provider, initialized]);

  const handleSave = useCallback(async () => {
    const headersPayload = Object.keys(extraHeaders).length > 0 ? extraHeaders : null;
    if (isNew) {
      if (!id.trim() || !displayName.trim()) return;
      await createMut.mutateAsync({
        id: id.trim(), display_name: displayName.trim(), provider_type: providerType,
        api_key: apiKey || undefined, base_url: baseUrl || undefined,
        is_enabled: isEnabled,
        tpm_limit: tpmLimit ? parseInt(tpmLimit) : null,
        rpm_limit: rpmLimit ? parseInt(rpmLimit) : null,
        management_key: managementKey || undefined,
        billing_type: billingType,
        plan_cost: billingType === "plan" && planCost ? parseFloat(planCost) : null,
        plan_period: billingType === "plan" ? planPeriod : null,
        extra_headers: headersPayload,
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
        management_key: managementKey || undefined,
        billing_type: billingType,
        plan_cost: billingType === "plan" && planCost ? parseFloat(planCost) : undefined,
        plan_period: billingType === "plan" ? planPeriod : undefined,
        clear_plan_cost: billingType === "usage",
        extra_headers: headersPayload,
        clear_extra_headers: headersPayload === null,
      });
    }
  }, [isNew, id, displayName, providerType, apiKey, baseUrl, isEnabled, tpmLimit, rpmLimit, managementKey, billingType, planCost, planPeriod, extraHeaders, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!providerId) return;
    const ok = await confirm("Delete this provider?", {
      title: "Delete provider",
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    await deleteMut.mutateAsync(providerId);
    goBack();
  }, [providerId, deleteMut, goBack, confirm]);

  const beginEditModel = useCallback((model: ProviderModelItem) => {
    setEditingModelId(model.id);
    setEditModelDisplay(model.display_name || "");
    setEditModelMaxTokens(model.max_tokens ? String(model.max_tokens) : "");
    setEditModelContextWindow(model.context_window ? String(model.context_window) : "");
    setEditModelMaxOutputTokens(model.max_output_tokens ? String(model.max_output_tokens) : "");
    setEditModelInputCost(model.input_cost_per_1m || "");
    setEditModelOutputCost(model.output_cost_per_1m || "");
    setEditModelCachedInputCost(model.cached_input_cost_per_1m || "");
    setEditModelNoSysMsg(!!model.no_system_messages);
    setEditModelSupportsTools(model.supports_tools !== false);
    setEditModelSupportsVision(model.supports_vision !== false);
    setEditModelReasoning(!!model.supports_reasoning);
    setEditModelPromptCaching(!!model.supports_prompt_caching);
    setEditModelStructuredOutput(!!model.supports_structured_output);
    setEditModelImageGen(!!model.supports_image_generation);
    setEditModelPromptStyle(model.prompt_style || "markdown");
    setEditModelExtraBody(
      model.extra_body && Object.keys(model.extra_body).length > 0
        ? JSON.stringify(model.extra_body, null, 2)
        : ""
    );
    setEditModelExtraBodyError(null);
  }, []);

  const cancelEditModel = useCallback(() => {
    setEditingModelId(null);
    setEditModelDisplay("");
    setEditModelMaxTokens("");
    setEditModelContextWindow("");
    setEditModelMaxOutputTokens("");
    setEditModelInputCost("");
    setEditModelOutputCost("");
    setEditModelCachedInputCost("");
    setEditModelNoSysMsg(false);
    setEditModelSupportsTools(true);
    setEditModelSupportsVision(true);
    setEditModelReasoning(false);
    setEditModelPromptCaching(false);
    setEditModelStructuredOutput(false);
    setEditModelPromptStyle("markdown");
    setEditModelExtraBody("");
    setEditModelExtraBodyError(null);
  }, []);

  const handleTest = useCallback(() => {
    setTestResult(null);
    const onSuccess = (r: { ok: boolean; message: string }) => setTestResult(r);
    const onError = (err: any) => setTestResult({ ok: false, message: err?.message || "Failed" });
    if (isNew) {
      testInlineMut.mutate({
        provider_type: providerType,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
      }, { onSuccess, onError });
    } else {
      testMut.mutate(providerId!, { onSuccess, onError });
    }
  }, [providerId, isNew, providerType, apiKey, baseUrl, testMut, testInlineMut]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew ? (id.trim() && displayName.trim()) : displayName.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  // Capabilities-driven field visibility
  const { data: caps } = useProviderTypeCapabilities(providerType);
  const showApiKey = caps?.requires_api_key ?? providerType !== "ollama";
  const showBaseUrl = caps?.requires_base_url ?? !["anthropic", "openai"].includes(providerType);
  const showManagementKey = caps?.management_key ?? providerType === "litellm";

  if (!isNew && isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Providers"
        backTo="/admin/providers"
        title={isNew ? "New Provider" : "Edit Provider"}
        subtitle={!isNew ? providerId : undefined}
        right={
          <>
            <button
              onClick={handleTest}
              disabled={testMut.isPending || testInlineMut.isPending}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: isWide ? 6 : 0,
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
                  display: "flex", flexDirection: "row", alignItems: "center", gap: isWide ? 6 : 0,
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
          </>
        }
      />

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
      <div style={{ flex: 1, padding: isWide ? "20px 24px" : "16px", overflowY: "auto" }}>
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
              <SelectInput
                value={providerType}
                onChange={(v) => {
                  setProviderType(v);
                  // Seed sensible billing defaults when picking a subscription
                  // provider — user can still override before saving.
                  if (v === "openai-subscription" && billingType !== "plan") {
                    setBillingType("plan");
                    if (!planCost) setPlanCost("20");
                    setPlanPeriod("monthly");
                  }
                }}
                options={PROVIDER_TYPE_OPTIONS}
              />
            </FormRow>
          </Section>

          {(showApiKey || showBaseUrl || showManagementKey) && (
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
                providerType === "ollama" ? "Ollama server URL (chat uses /v1, native APIs use /api)" :
                "Optional, uses default if blank"
              }>
                <TextInput value={baseUrl} onChangeText={setBaseUrl} placeholder={
                  providerType === "ollama" ? "http://localhost:11434" :
                  providerType === "openai-compatible" ? "https://api.minimax.chat/v1" :
                  providerType === "anthropic-compatible" ? "https://api.minimax.chat/v1" :
                  "https://litellm.example.com"
                } />
              </FormRow>
            )}
            {showManagementKey && (
              <FormRow label="Management Key" description="LiteLLM management key for model listing">
                <TextInput value={managementKey} onChangeText={setManagementKey} placeholder="Optional" type="password" />
              </FormRow>
            )}
          </Section>
          )}

          {providerType === "openai-subscription" && (
            <OpenAISubscriptionSection providerId={isNew ? undefined : providerId} />
          )}

          <ProviderExtraHeadersSection
            initial={extraHeaders}
            onChange={setExtraHeaders}
          />

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

          <Section title="Billing" description={
            billingType === "plan"
              ? "Fixed-rate plan: per-call cost tracked as $0, flat cost added to forecast"
              : "Per-token: cost computed from model pricing per request"
          }>
            <FormRow label="Billing Type">
              <SelectInput
                value={billingType}
                onChange={setBillingType}
                options={[
                  { label: "Per-token usage", value: "usage" },
                  { label: "Fixed plan (e.g. subscription)", value: "plan" },
                ]}
              />
            </FormRow>
            {billingType === "plan" && (
              <Row>
                <Col>
                  <FormRow label="Plan Cost (USD)" description={!planCost ? "Required for forecast" : `$${parseFloat(planCost).toFixed(2)} / ${planPeriod}`}>
                    <TextInput value={planCost} onChangeText={setPlanCost} placeholder="e.g. 40.00" type="number" />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Plan Period">
                    <SelectInput
                      value={planPeriod}
                      onChange={setPlanPeriod}
                      options={[
                        { label: "Monthly", value: "monthly" },
                        { label: "Weekly", value: "weekly" },
                      ]}
                    />
                  </FormRow>
                </Col>
              </Row>
            )}
          </Section>

          {!isNew && (
            <Section title="Models" description="Manually defined models for providers without a /models API endpoint">
              {/* Existing models list */}
              {modelsLoading ? (
                <div style={{ color: t.textDim, fontSize: 12, padding: "8px 0" }}>Loading...</div>
              ) : providerModels && providerModels.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {providerModels.map((m: ProviderModelItem) => (
                    <div
                      key={m.id}
                      style={{
                        display: "flex", flexDirection: "column", gap: 8,
                        padding: "8px 10px", background: t.surfaceRaised, borderRadius: 6,
                        fontSize: 12,
                      }}
                    >
                      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ color: t.text, fontFamily: "monospace", flex: 1 }}>
                          {m.model_id}
                        </span>
                        {editingModelId === m.id ? (
                          <>
                            <button
                              onClick={async () => {
                                let parsedExtraBody: Record<string, any> | null = null;
                                if (editModelExtraBody.trim()) {
                                  try {
                                    parsedExtraBody = JSON.parse(editModelExtraBody);
                                    if (parsedExtraBody === null || typeof parsedExtraBody !== "object" || Array.isArray(parsedExtraBody)) {
                                      setEditModelExtraBodyError("extra_body must be a JSON object");
                                      return;
                                    }
                                  } catch (err) {
                                    setEditModelExtraBodyError(`Invalid JSON: ${(err as Error).message}`);
                                    return;
                                  }
                                }
                                setEditModelExtraBodyError(null);
                                await updateModelMut.mutateAsync({
                                  modelPk: m.id,
                                  data: {
                                    display_name: editModelDisplay.trim() || null,
                                    max_tokens: editModelMaxTokens ? parseInt(editModelMaxTokens) : null,
                                    context_window: editModelContextWindow ? parseInt(editModelContextWindow) : null,
                                    max_output_tokens: editModelMaxOutputTokens ? parseInt(editModelMaxOutputTokens) : null,
                                    input_cost_per_1m: editModelInputCost.trim() || null,
                                    output_cost_per_1m: editModelOutputCost.trim() || null,
                                    cached_input_cost_per_1m: editModelCachedInputCost.trim() || null,
                                    no_system_messages: editModelNoSysMsg,
                                    supports_tools: editModelSupportsTools,
                                    supports_vision: editModelSupportsVision,
                                    supports_reasoning: editModelReasoning,
                                    supports_prompt_caching: editModelPromptCaching,
                                    supports_structured_output: editModelStructuredOutput,
                                    supports_image_generation: editModelImageGen,
                                    prompt_style: editModelPromptStyle,
                                    extra_body: parsedExtraBody ?? {},
                                  },
                                });
                                cancelEditModel();
                              }}
                              disabled={updateModelMut.isPending}
                              style={{
                                background: t.accent, border: "none", borderRadius: 4,
                                color: "#fff", cursor: "pointer", padding: "4px 8px",
                                fontSize: 11, fontWeight: 600,
                              }}
                              title="Save model row"
                            >
                              Save
                            </button>
                            <button
                              onClick={cancelEditModel}
                              disabled={updateModelMut.isPending}
                              style={{
                                background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                                color: t.textMuted, cursor: "pointer", padding: "4px 8px",
                                fontSize: 11, fontWeight: 600,
                              }}
                              title="Cancel editing"
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={() => beginEditModel(m)}
                            disabled={updateModelMut.isPending || editingModelId !== null}
                            style={{
                              background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                              color: t.textMuted, cursor: editingModelId !== null ? "not-allowed" : "pointer",
                              padding: "4px 8px", fontSize: 11, fontWeight: 600, opacity: editingModelId !== null ? 0.6 : 1,
                            }}
                            title="Edit model row"
                          >
                            Edit
                          </button>
                        )}
                        {caps?.delete_model && (
                          <button
                            onClick={async () => {
                              const ok = await confirm(`Remove ${m.model_id} from provider?`, {
                                title: "Remove model",
                                confirmLabel: "Remove",
                                variant: "danger",
                              });
                              if (ok) deleteRemoteMut.mutate(m.model_id);
                            }}
                            disabled={deleteRemoteMut.isPending || editingModelId === m.id}
                            style={{
                              background: "none", border: "none", cursor: "pointer",
                              padding: "2px 4px", color: t.danger, flexShrink: 0,
                              fontSize: 10, fontWeight: 600,
                            }}
                            title="Remove from provider"
                          >
                            <Trash2 size={11} />
                          </button>
                        )}
                        <button
                          onClick={() => deleteModelMut.mutate(m.id)}
                          disabled={deleteModelMut.isPending || editingModelId === m.id}
                          style={{
                            background: "none", border: "none", cursor: "pointer",
                            padding: 2, color: t.textDim, flexShrink: 0,
                          }}
                          title="Remove from DB"
                        >
                          <X size={13} />
                        </button>
                      </div>

                      {editingModelId === m.id ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          <div style={{ display: "flex", flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
                            <div style={{ flex: 2, minWidth: 140 }}>
                              <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Display Name</div>
                              <input
                                value={editModelDisplay}
                                onChange={(e) => setEditModelDisplay(e.target.value)}
                                placeholder="Optional"
                                style={{
                                  width: "100%", padding: "6px 8px", fontSize: 12,
                                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                                  color: t.text,
                                }}
                              />
                            </div>
                            <div style={{ flex: 1, minWidth: 120 }}>
                              <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Max Tokens</div>
                              <input
                                value={editModelMaxTokens}
                                onChange={(e) => setEditModelMaxTokens(e.target.value)}
                                placeholder="Optional"
                                type="number"
                                style={{
                                  width: "100%", padding: "6px 8px", fontSize: 12,
                                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                                  color: t.text,
                                }}
                              />
                            </div>
                            <div style={{ flex: 1, minWidth: 120 }}>
                              <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Input $/1M</div>
                              <input
                                value={editModelInputCost}
                                onChange={(e) => setEditModelInputCost(e.target.value)}
                                placeholder="Optional"
                                style={{
                                  width: "100%", padding: "6px 8px", fontSize: 12,
                                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                                  color: t.text,
                                }}
                              />
                            </div>
                            <div style={{ flex: 1, minWidth: 120 }}>
                              <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Output $/1M</div>
                              <input
                                value={editModelOutputCost}
                                onChange={(e) => setEditModelOutputCost(e.target.value)}
                                placeholder="Optional"
                                style={{
                                  width: "100%", padding: "6px 8px", fontSize: 12,
                                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                                  color: t.text,
                                }}
                              />
                            </div>
                            <div style={{ minWidth: 110 }}>
                              <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Prompt style</div>
                              <select
                                value={editModelPromptStyle}
                                onChange={(e) => setEditModelPromptStyle(e.target.value as "markdown" | "xml" | "structured")}
                                style={{
                                  width: "100%", padding: "5px 6px", fontSize: 12,
                                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                                  color: t.text,
                                }}
                              >
                                <option value="markdown">markdown</option>
                                <option value="xml">xml</option>
                                <option value="structured">structured</option>
                              </select>
                            </div>
                          </div>

                          <div className="flex flex-row gap-2 flex-wrap">
                            <div className="flex-1 min-w-[120px]">
                              <div className="text-text-dim text-[10px] mb-0.5">Context window</div>
                              <input
                                value={editModelContextWindow}
                                onChange={(e) => setEditModelContextWindow(e.target.value)}
                                placeholder="Input cap"
                                type="number"
                                className="w-full px-2 py-1.5 text-xs rounded bg-input-bg border border-surface-border text-text"
                              />
                            </div>
                            <div className="flex-1 min-w-[120px]">
                              <div className="text-text-dim text-[10px] mb-0.5">Max output tokens</div>
                              <input
                                value={editModelMaxOutputTokens}
                                onChange={(e) => setEditModelMaxOutputTokens(e.target.value)}
                                placeholder="Output cap"
                                type="number"
                                className="w-full px-2 py-1.5 text-xs rounded bg-input-bg border border-surface-border text-text"
                              />
                            </div>
                            <div className="flex-1 min-w-[120px]">
                              <div className="text-text-dim text-[10px] mb-0.5">Cached input $/1M</div>
                              <input
                                value={editModelCachedInputCost}
                                onChange={(e) => setEditModelCachedInputCost(e.target.value)}
                                placeholder="$0.30"
                                className="w-full px-2 py-1.5 text-xs rounded bg-input-bg border border-surface-border text-text"
                              />
                            </div>
                          </div>

                          <div style={{ display: "flex", flexDirection: "row", gap: 12, flexWrap: "wrap" }}>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelNoSysMsg}
                                onChange={(e) => setEditModelNoSysMsg(e.target.checked)}
                                style={{ accentColor: t.warning }}
                              />
                              No system msgs
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelSupportsTools}
                                onChange={(e) => setEditModelSupportsTools(e.target.checked)}
                                style={{ accentColor: t.accent }}
                              />
                              Supports tools
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelSupportsVision}
                                onChange={(e) => setEditModelSupportsVision(e.target.checked)}
                                style={{ accentColor: t.accent }}
                              />
                              Supports vision
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelReasoning}
                                onChange={(e) => setEditModelReasoning(e.target.checked)}
                                style={{ accentColor: t.accent }}
                              />
                              Reasoning
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelPromptCaching}
                                onChange={(e) => setEditModelPromptCaching(e.target.checked)}
                                style={{ accentColor: t.accent }}
                              />
                              Prompt caching
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelStructuredOutput}
                                onChange={(e) => setEditModelStructuredOutput(e.target.checked)}
                                style={{ accentColor: t.accent }}
                              />
                              Structured output
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textMuted }}>
                              <input
                                type="checkbox"
                                checked={editModelImageGen}
                                onChange={(e) => setEditModelImageGen(e.target.checked)}
                                style={{ accentColor: t.accent }}
                              />
                              Image generation
                            </label>
                          </div>

                          <div className="flex flex-col gap-1">
                            <div className="text-text-dim text-[10px]">
                              Extra body (JSON) — merged into request <code>extra_body</code>; e.g. <code>{`{"options":{"num_ctx":16384}}`}</code> for Ollama
                            </div>
                            <textarea
                              value={editModelExtraBody}
                              onChange={(e) => {
                                setEditModelExtraBody(e.target.value);
                                if (editModelExtraBodyError) setEditModelExtraBodyError(null);
                              }}
                              placeholder='{}'
                              rows={3}
                              className="w-full px-2 py-1.5 text-xs font-mono rounded bg-input-bg border border-surface-border text-text resize-y"
                            />
                            {editModelExtraBodyError && (
                              <div className="text-danger text-[11px]">{editModelExtraBodyError}</div>
                            )}
                          </div>
                        </div>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          {m.display_name && (
                            <span style={{ color: t.textMuted, fontSize: 11 }}>{m.display_name}</span>
                          )}
                          {m.max_tokens && (
                            <span style={{ color: t.textDim, fontSize: 11 }}>{Math.round(m.max_tokens / 1000)}k</span>
                          )}
                          {(m.input_cost_per_1m || m.output_cost_per_1m) && (
                            <span style={{ color: t.textDim, fontSize: 11 }}>
                              {m.input_cost_per_1m || "?"}/{m.output_cost_per_1m || "?"}
                            </span>
                          )}
                          {m.no_system_messages && (
                            <span style={{
                              color: t.warning, fontSize: 10, fontWeight: 600,
                              background: t.warningSubtle, padding: "1px 5px",
                              borderRadius: 4,
                            }}>no-sys</span>
                          )}
                          {m.supports_tools === false && (
                            <span style={{
                              color: t.warning, fontSize: 10, fontWeight: 600,
                              background: t.warningSubtle, padding: "1px 5px",
                              borderRadius: 4,
                            }}>no-tools</span>
                          )}
                          {m.supports_vision === false && (
                            <span style={{
                              color: t.warning, fontSize: 10, fontWeight: 600,
                              background: t.warningSubtle, padding: "1px 5px",
                              borderRadius: 4,
                            }}>no-vision</span>
                          )}
                          {m.supports_reasoning && (
                            <span style={{
                              color: t.accent, fontSize: 10, fontWeight: 600,
                              background: t.surfaceOverlay, padding: "1px 5px",
                              borderRadius: 4,
                            }} title="Model supports reasoning / effort budget">reasoning</span>
                          )}
                          {m.supports_image_generation && (
                            <span style={{
                              color: t.accent, fontSize: 10, fontWeight: 600,
                              background: t.surfaceOverlay, padding: "1px 5px",
                              borderRadius: 4,
                            }} title="Model can generate images">image-gen</span>
                          )}
                          <span
                            style={{
                              color: t.textMuted, fontSize: 10, fontWeight: 600,
                              background: t.surfaceOverlay, padding: "1px 5px",
                              borderRadius: 4,
                            }}
                            title="Framework prompts render in this dialect for this model"
                          >{m.prompt_style || "markdown"}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: t.textDim, fontSize: 12, padding: "4px 0" }}>
                  No models defined. Add models below if this provider doesn't support the /models API.
                </div>
              )}

              {/* Add model form */}
              <div style={{ display: "flex", flexDirection: "row", gap: 6, marginTop: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ flex: 2, minWidth: 160 }}>
                  <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Model ID *</div>
                  <input
                    value={newModelId}
                    onChange={(e) => {
                      const v = e.target.value;
                      setNewModelId(v);
                      if (v.toLowerCase().includes("minimax")) setNewModelNoSysMsg(true);
                    }}
                    placeholder="e.g. gpt-4o"
                    style={{
                      width: "100%", padding: "6px 8px", fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                      color: t.text, fontFamily: "monospace",
                    }}
                  />
                </div>
                <div style={{ flex: 2, minWidth: 120 }}>
                  <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Display Name</div>
                  <input
                    value={newModelDisplay}
                    onChange={(e) => setNewModelDisplay(e.target.value)}
                    placeholder="Optional"
                    style={{
                      width: "100%", padding: "6px 8px", fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                      color: t.text,
                    }}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 80 }}>
                  <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Max Tokens</div>
                  <input
                    value={newModelMaxTokens}
                    onChange={(e) => setNewModelMaxTokens(e.target.value)}
                    placeholder="e.g. 128000"
                    type="number"
                    style={{
                      width: "100%", padding: "6px 8px", fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                      color: t.text,
                    }}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 80 }}>
                  <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Input $/1M</div>
                  <input
                    value={newModelInputCost}
                    onChange={(e) => setNewModelInputCost(e.target.value)}
                    placeholder="e.g. $3.00"
                    style={{
                      width: "100%", padding: "6px 8px", fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                      color: t.text,
                    }}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 80 }}>
                  <div style={{ color: t.textDim, fontSize: 10, marginBottom: 2 }}>Output $/1M</div>
                  <input
                    value={newModelOutputCost}
                    onChange={(e) => setNewModelOutputCost(e.target.value)}
                    placeholder="e.g. $15.00"
                    style={{
                      width: "100%", padding: "6px 8px", fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                      color: t.text,
                    }}
                  />
                </div>
                <label style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  fontSize: 10, color: t.textMuted, cursor: "pointer",
                  flexShrink: 0, alignSelf: "flex-end", paddingBottom: 6,
                }}>
                  <input
                    type="checkbox"
                    checked={newModelNoSysMsg}
                    onChange={(e) => setNewModelNoSysMsg(e.target.checked)}
                    style={{ accentColor: t.warning }}
                  />
                  No system msgs
                </label>
                <label style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  fontSize: 10, color: t.textMuted, cursor: "pointer",
                  flexShrink: 0, alignSelf: "flex-end", paddingBottom: 6,
                }}>
                  <input
                    type="checkbox"
                    checked={newModelNoTools}
                    onChange={(e) => setNewModelNoTools(e.target.checked)}
                    style={{ accentColor: t.warning }}
                  />
                  No tools
                </label>
                <label style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  fontSize: 10, color: t.textMuted, cursor: "pointer",
                  flexShrink: 0, alignSelf: "flex-end", paddingBottom: 6,
                }}
                title="Model supports a reasoning / thinking budget. Gates the Reasoning effort control in the bot editor and the /effort slash command."
                >
                  <input
                    type="checkbox"
                    checked={newModelReasoning}
                    onChange={(e) => setNewModelReasoning(e.target.checked)}
                    style={{ accentColor: t.accent }}
                  />
                  Reasoning
                </label>
                <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 110, alignSelf: "flex-end" }}>
                  <div style={{ color: t.textDim, fontSize: 10 }}>Prompt style</div>
                  <select
                    value={newModelPromptStyle}
                    onChange={(e) => setNewModelPromptStyle(e.target.value as "markdown" | "xml" | "structured")}
                    style={{
                      padding: "5px 6px", fontSize: 12,
                      background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                      color: t.text,
                    }}
                    title="How framework prompts (global base, memory scheme, channel workspace) are rendered for this model. Anthropic native → xml; everything else → markdown."
                  >
                    <option value="markdown">markdown</option>
                    <option value="xml">xml</option>
                    <option value="structured">structured</option>
                  </select>
                </div>
                <button
                  onClick={async () => {
                    if (!newModelId.trim()) return;
                    await addModelMut.mutateAsync({
                      model_id: newModelId.trim(),
                      display_name: newModelDisplay.trim() || undefined,
                      max_tokens: newModelMaxTokens ? parseInt(newModelMaxTokens) : undefined,
                      input_cost_per_1m: newModelInputCost.trim() || undefined,
                      output_cost_per_1m: newModelOutputCost.trim() || undefined,
                      no_system_messages: newModelNoSysMsg || undefined,
                      supports_tools: newModelNoTools ? false : undefined,
                      supports_reasoning: newModelReasoning || undefined,
                      prompt_style: newModelPromptStyle !== "markdown" ? newModelPromptStyle : undefined,
                    });
                    setNewModelId("");
                    setNewModelDisplay("");
                    setNewModelMaxTokens("");
                    setNewModelInputCost("");
                    setNewModelOutputCost("");
                    setNewModelNoSysMsg(false);
                    setNewModelNoTools(false);
                    setNewModelReasoning(false);
                    setNewModelPromptStyle("markdown");
                  }}
                  disabled={!newModelId.trim() || addModelMut.isPending}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                    padding: "6px 12px", fontSize: 12, fontWeight: 600,
                    border: "none", borderRadius: 4, flexShrink: 0,
                    background: !newModelId.trim() ? t.surfaceOverlay : t.accent,
                    color: !newModelId.trim() ? t.textDim : "#fff",
                    cursor: !newModelId.trim() ? "not-allowed" : "pointer",
                  }}
                >
                  <Plus size={13} />
                  Add
                </button>
              </div>
            </Section>
          )}

          {!isNew && caps && (
            <ProviderCapabilitySections
              providerId={providerId!}
              capabilities={caps}
              lastRefreshTs={provider?.config?.last_refresh_ts as string | undefined}
              lastRefreshError={provider?.config?.last_refresh_error as string | undefined}
            />
          )}

          {!isNew && provider && (
            <Section title="Info">
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>ID</span>
                  <span style={{ color: t.text, fontFamily: "monospace" }}>{provider.id}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>API Key</span>
                  <span style={{ color: provider.has_api_key ? t.success : t.textDim }}>
                    {provider.has_api_key ? "Set" : "Not set"}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Created</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(provider.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                  <span style={{ color: t.textDim }}>Updated</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(provider.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
              </div>
            </Section>
          )}
        </div>
      </div>
      <ConfirmDialogSlot />
    </div>
  );
}
