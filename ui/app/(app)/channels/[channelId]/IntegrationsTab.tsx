import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Plus, X, Pencil, Check, AlertTriangle, Zap, Power, Layers } from "lucide-react";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import { Link } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { prettyIntegrationName } from "@/src/utils/format";
import {
  useChannelIntegrations,
  useBindIntegration,
  useUnbindIntegration,
  useAvailableIntegrations,
  useBindingSuggestions,
  useActivatableIntegrations,
  useActivateIntegration,
  useDeactivateIntegration,
  useUpdateActivationConfig,
  type AvailableIntegration,
  type ConfigField,
  type BindingSuggestion,
} from "@/src/api/hooks/useChannels";
import {
  Section, FormRow, TextInput, SelectInput, Toggle, EmptyState,
} from "@/src/components/shared/FormControls";
import { ActionButton, StatusBadge, InfoBanner } from "@/src/components/shared/SettingsControls";
import type { ActivatableIntegration, ActivationResult } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Injection summary helpers
// ---------------------------------------------------------------------------

function CarapacePill({ id, t }: { id: string; t: any }) {
  return (
    <Link href={`/admin/carapaces/${id}` as any} asChild>
      <a
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 5,
          background: t.accentSubtle,
          border: `1px solid ${t.accentBorder}`,
          textDecoration: "none",
          cursor: "pointer",
        }}
      >
        <Layers size={10} color={t.accent} />
        <span style={{ fontSize: 11, fontWeight: 600, color: t.accent }}>{id}</span>
      </a>
    </Link>
  );
}

function InjectionSummaryLine({ ig }: { ig: ActivatableIntegration }) {
  const parts: string[] = [];
  if (ig.tools.length > 0) parts.push(`${ig.tools.length} tools`);
  if (ig.skill_count > 0) parts.push(`${ig.skill_count} skills`);
  if (ig.has_system_prompt) parts.push("system prompt");
  if (parts.length === 0) return null;
  const carapaceLabel = ig.carapaces.length > 0
    ? ig.carapaces.join(", ")
    : null;
  return (
    <span>
      Adds {parts.join(", ")}
      {carapaceLabel ? ` via ${carapaceLabel} capability` : ""}
    </span>
  );
}

function InjectionDetails({ ig, t }: { ig: ActivatableIntegration; t: any }) {
  if (ig.tools.length === 0 && ig.skill_count === 0 && !ig.has_system_prompt && ig.carapaces.length === 0) return null;
  return (
    <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${t.surfaceBorder}` }}>
      {ig.carapaces.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: t.text }}>Capability:</span>
          {ig.carapaces.map((id) => (
            <CarapacePill key={id} id={id} t={t} />
          ))}
          <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
            from {prettyIntegrationName(ig.integration_type)}
          </span>
        </div>
      )}
      {ig.tools.length > 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 3 }}>
          <span style={{ fontWeight: 600, color: t.text }}>Tools: </span>
          {ig.tools.join(", ")}
        </div>
      )}
      {ig.skill_count > 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 3 }}>
          <span style={{ fontWeight: 600, color: t.text }}>Skills: </span>
          {ig.skill_count}
        </div>
      )}
      {ig.has_system_prompt && (
        <div style={{ fontSize: 11, color: t.textDim }}>
          <span style={{ fontWeight: 600, color: t.text }}>System prompt: </span>
          injected
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HUD preset picker
// ---------------------------------------------------------------------------

function HudPresetPicker({
  ig,
  channelId,
}: {
  ig: ActivatableIntegration;
  channelId: string;
}) {
  const t = useThemeTokens();
  const configMut = useUpdateActivationConfig(channelId);
  const presets = ig.chat_hud_presets;
  if (!presets || Object.keys(presets).length < 2) return null;

  const presetEntries = Object.entries(presets);
  const currentPreset = ig.activation_config?.hud_preset as string | undefined;
  const selectedKey = (currentPreset && presets[currentPreset]) ? currentPreset : presetEntries[0][0];

  // Build widget ID → label map from chat_hud declarations
  const widgetLabels: Record<string, string> = {};
  for (const w of ig.chat_hud ?? []) {
    widgetLabels[w.id] = w.label ?? w.id;
  }

  const handleSelect = (key: string) => {
    if (key === selectedKey) return;
    configMut.mutate({
      integrationType: ig.integration_type,
      config: { hud_preset: key },
    });
  };

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.surfaceBorder}` }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: t.textDim, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
        HUD Layout
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {presetEntries.map(([key, preset]) => {
          const isSelected = key === selectedKey;
          return (
            <button
              key={key}
              onClick={() => handleSelect(key)}
              disabled={configMut.isPending}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "8px 10px",
                borderRadius: 8,
                border: `1.5px solid ${isSelected ? t.accent : t.surfaceBorder}`,
                background: isSelected ? t.accentSubtle : "transparent",
                cursor: configMut.isPending ? "wait" : "pointer",
                textAlign: "left",
                transition: "all 0.12s",
              }}
            >
              {/* Radio dot */}
              <div style={{
                width: 16, height: 16, borderRadius: 8, flexShrink: 0, marginTop: 1,
                border: `2px solid ${isSelected ? t.accent : t.surfaceBorder}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "border-color 0.12s",
              }}>
                {isSelected && (
                  <div style={{ width: 8, height: 8, borderRadius: 4, background: t.accent }} />
                )}
              </div>

              {/* Label + description + widget pills */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                    {preset.label}
                  </span>
                  <span style={{ fontSize: 10, color: t.textDim }}>
                    {preset.widgets.length} widget{preset.widgets.length !== 1 ? "s" : ""}
                  </span>
                </div>
                {preset.description && (
                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 2, lineHeight: "1.35" }}>
                    {preset.description}
                  </div>
                )}
                {preset.widgets.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 5 }}>
                    {preset.widgets.map((wid) => (
                      <span
                        key={wid}
                        style={{
                          fontSize: 10,
                          fontWeight: 500,
                          color: isSelected ? t.accent : t.textDim,
                          padding: "1px 6px",
                          borderRadius: 4,
                          background: isSelected ? `${t.accent}18` : t.surfaceOverlay,
                          border: `1px solid ${isSelected ? `${t.accent}33` : t.surfaceBorder}`,
                        }}
                      >
                        {widgetLabels[wid] ?? wid}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Generic multi-select picker (checkbox list)
// ---------------------------------------------------------------------------

function MultiSelectPicker({
  options,
  selected,
  onChange,
}: {
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const t = useThemeTokens();

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <View className="gap-1.5">
      {options.map((opt) => {
        const isChecked = selected.includes(opt.value);
        return (
          <Pressable
            key={opt.value}
            onPress={() => toggle(opt.value)}
            className="flex-row items-center gap-2"
          >
            <View
              style={{
                width: 16,
                height: 16,
                borderRadius: 3,
                borderWidth: 1.5,
                borderColor: isChecked ? t.accent : t.surfaceBorder,
                backgroundColor: isChecked ? t.accent : "transparent",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {isChecked && <Check size={11} color="#fff" strokeWidth={3} />}
            </View>
            <Text className="text-text text-sm">{opt.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Generic config field renderer
// ---------------------------------------------------------------------------

function BindingConfigFields({
  fields,
  values,
  onChange,
}: {
  fields: ConfigField[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}) {
  return (
    <>
      {fields.map((field) => {
        const val = values[field.key] ?? field.default;
        switch (field.type) {
          case "string":
            return (
              <FormRow key={field.key} label={field.label} description={field.description}>
                <TextInput
                  value={val ?? ""}
                  onChangeText={(v: string) => onChange(field.key, v)}
                />
              </FormRow>
            );
          case "boolean":
            return (
              <Toggle
                key={field.key}
                label={field.label}
                description={field.description}
                value={val ?? false}
                onChange={(v: boolean) => onChange(field.key, v)}
              />
            );
          case "number":
            return (
              <FormRow key={field.key} label={field.label} description={field.description}>
                <TextInput
                  value={val != null ? String(val) : ""}
                  onChangeText={(v: string) => onChange(field.key, v === "" ? undefined : Number(v))}
                  type="number"
                />
              </FormRow>
            );
          case "select":
            return (
              <FormRow key={field.key} label={field.label} description={field.description}>
                <SelectInput
                  value={val ?? ""}
                  onChange={(v: string) => onChange(field.key, v)}
                  options={field.options ?? []}
                />
              </FormRow>
            );
          case "multiselect":
            return (
              <FormRow key={field.key} label={field.label} description={field.description}>
                <MultiSelectPicker
                  options={field.options ?? []}
                  selected={Array.isArray(val) ? val : []}
                  onChange={(v: string[]) => onChange(field.key, v)}
                />
              </FormRow>
            );
          default:
            return null;
        }
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Activation section
// ---------------------------------------------------------------------------

function ActivationsSection({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
  const t = useThemeTokens();
  const { data: integrations, isLoading } = useActivatableIntegrations(channelId);
  const activateMut = useActivateIntegration(channelId);
  const deactivateMut = useDeactivateIntegration(channelId);
  const [warnings, setWarnings] = useState<ActivationResult["warnings"]>([]);
  const [togglingType, setTogglingType] = useState<string | null>(null);

  if (isLoading || !integrations || integrations.length === 0) return null;

  const handleToggle = async (integrationType: string, currentlyActive: boolean) => {
    setTogglingType(integrationType);
    setWarnings([]);
    try {
      if (currentlyActive) {
        await deactivateMut.mutateAsync(integrationType);
      } else {
        const result = await activateMut.mutateAsync(integrationType);
        if (result.warnings?.length) {
          setWarnings(result.warnings);
        }
      }
    } finally {
      setTogglingType(null);
    }
  };

  return (
    <Section
      title="Integration Features"
      description="Enable integration features on this channel."
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {integrations.map((ig) => {
          const disabled = ig.requires_workspace && !workspaceEnabled && !ig.activated;
          const toggling = togglingType === ig.integration_type;

          return (
            <div
              key={ig.integration_type}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 14px",
                borderRadius: 10,
                border: `1px solid ${ig.activated ? t.accentBorder : t.surfaceBorder}`,
                background: ig.activated ? t.accentSubtle : t.surfaceRaised,
                transition: "all 0.15s ease",
              }}
            >
              {/* Icon */}
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 8,
                  background: ig.activated ? t.accent : t.surfaceOverlay,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  transition: "background 0.15s",
                }}
              >
                <Zap
                  size={16}
                  color={ig.activated ? "#fff" : t.textDim}
                  fill={ig.activated ? "#fff" : "none"}
                />
              </div>

              {/* Content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                    {prettyIntegrationName(ig.integration_type)}
                  </span>
                  {ig.activated && (
                    <StatusBadge label="Active" variant="success" />
                  )}
                  {ig.includes?.length > 0 && (
                    <span style={{
                      fontSize: 10,
                      fontWeight: 600,
                      color: t.textDim,
                      padding: "1px 6px",
                      borderRadius: 3,
                      background: t.surfaceOverlay,
                    }}>
                      includes {ig.includes.map(i => prettyIntegrationName(i)).join(", ")}
                    </span>
                  )}
                  {ig.requires_workspace && !workspaceEnabled && (
                    <StatusBadge label="Requires workspace" variant="warning" />
                  )}
                </div>
                {ig.description && (
                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 3, lineHeight: "1.4" }}>
                    {ig.description}
                  </div>
                )}
                {ig.activated ? (
                  <>
                    <InjectionDetails ig={ig} t={t} />
                    <HudPresetPicker ig={ig} channelId={channelId} />
                  </>
                ) : (
                  (ig.tools.length > 0 || ig.skill_count > 0) && (
                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 3, fontStyle: "italic" }}>
                      <InjectionSummaryLine ig={ig} />
                    </div>
                  )
                )}
              </div>

              {/* Toggle button */}
              <button
                onClick={() => !disabled && !toggling && handleToggle(ig.integration_type, ig.activated)}
                disabled={disabled || toggling}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: ig.activated
                    ? `1px solid ${t.dangerBorder}`
                    : `1px solid ${t.accentBorder}`,
                  background: ig.activated ? "transparent" : t.accent,
                  color: ig.activated ? t.danger : "#fff",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: disabled || toggling ? "not-allowed" : "pointer",
                  opacity: disabled ? 0.4 : 1,
                  flexShrink: 0,
                  transition: "all 0.12s",
                }}
              >
                {toggling ? (
                  <ActivityIndicator size={12} color={ig.activated ? t.danger : "#fff"} />
                ) : (
                  <Power size={12} />
                )}
                {ig.activated ? "Deactivate" : "Activate"}
              </button>
            </div>
          );
        })}
      </div>

      {/* Warnings from activation */}
      {warnings.length > 0 && (
        <InfoBanner
          variant="warning"
          icon={<AlertTriangle size={14} />}
        >
          <div>
            {warnings.map((w, i) => (
              <div key={i}>{w.message}</div>
            ))}
          </div>
        </InfoBanner>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Binding form (shared between Add and Edit)
// ---------------------------------------------------------------------------

/** Build initial config values from config_fields defaults, overlaid with existing dispatch_config. */
function initConfigValues(
  fields: ConfigField[] | undefined,
  dispatchConfig: Record<string, any> | undefined,
): Record<string, any> {
  const values: Record<string, any> = {};
  if (!fields) return values;
  for (const f of fields) {
    values[f.key] = dispatchConfig?.[f.key] ?? f.default;
  }
  return values;
}

/** Collect non-default, non-empty config values for submission. */
function collectConfigValues(
  fields: ConfigField[] | undefined,
  values: Record<string, any>,
): Record<string, any> {
  const result: Record<string, any> = {};
  if (!fields) return result;
  for (const f of fields) {
    const v = values[f.key];
    if (v === undefined || v === null) continue;
    // Skip empty arrays and empty strings that match defaults
    if (Array.isArray(v) && v.length === 0) continue;
    if (v === f.default) continue;
    result[f.key] = v;
  }
  return result;
}

// ---------------------------------------------------------------------------
// Suggestions picker (shown when integration provides suggestions_endpoint)
// ---------------------------------------------------------------------------

function SuggestionsPicker({
  suggestions,
  isLoading,
  onSelect,
  selectedClientId,
}: {
  suggestions: BindingSuggestion[];
  isLoading: boolean;
  onSelect: (s: BindingSuggestion) => void;
  selectedClientId: string;
}) {
  const t = useThemeTokens();

  if (isLoading) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0" }}>
        <ActivityIndicator size={12} color={t.textDim} />
        <span style={{ fontSize: 11, color: t.textDim }}>Loading recent chats...</span>
      </div>
    );
  }

  if (suggestions.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim }}>Recent chats</span>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          maxHeight: 200,
          overflowY: "auto",
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.surfaceRaised,
        }}
      >
        {suggestions.map((s) => {
          const isSelected = selectedClientId === s.client_id;
          return (
            <button
              key={s.client_id}
              onClick={() => onSelect(s)}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 1,
                padding: "8px 12px",
                background: isSelected ? t.accentSubtle : "transparent",
                border: "none",
                borderBottom: `1px solid ${t.surfaceBorder}`,
                cursor: "pointer",
                textAlign: "left",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = t.surfaceOverlay; }}
              onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
            >
              <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                {s.display_name}
              </span>
              <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                {s.client_id}
              </span>
              {s.description && (
                <span style={{
                  fontSize: 10,
                  color: t.textMuted,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: "100%",
                }}>
                  {s.description}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function BindingForm({
  availableIntegrations,
  initialType,
  initialClientId,
  initialDisplayName,
  initialDispatchConfig,
  onSubmit,
  onCancel,
  isPending,
  isError,
  errorMessage,
  submitLabel,
  lockType,
}: {
  availableIntegrations: AvailableIntegration[];
  initialType: string;
  initialClientId: string;
  initialDisplayName: string;
  initialDispatchConfig?: Record<string, any>;
  onSubmit: (type: string, clientId: string, displayName: string, dispatchConfig: Record<string, any>) => void;
  onCancel: () => void;
  isPending: boolean;
  isError: boolean;
  errorMessage?: string;
  submitLabel: string;
  lockType?: boolean;
}) {
  const selected = availableIntegrations.find((i) => i.type === initialType);
  const [type, setType] = useState(initialType);
  const [clientId, setClientId] = useState(initialClientId);
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [configValues, setConfigValues] = useState<Record<string, any>>(() =>
    initConfigValues(selected?.binding?.config_fields, initialDispatchConfig),
  );

  const currentSelected = availableIntegrations.find((i) => i.type === type);
  const binding = currentSelected?.binding;
  const configFields = binding?.config_fields;
  const suggestionsEndpoint = binding?.suggestions_endpoint;

  const { data: suggestions, isLoading: suggestionsLoading } = useBindingSuggestions(suggestionsEndpoint);

  const handleTypeChange = (newType: string) => {
    setType(newType);
    const newBinding = availableIntegrations.find((i) => i.type === newType)?.binding;
    setConfigValues(initConfigValues(newBinding?.config_fields, undefined));
    if (newBinding?.client_id_prefix && !clientId) {
      setClientId(newBinding.client_id_prefix);
    }
  };

  const handleConfigChange = (key: string, value: any) => {
    setConfigValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSuggestionSelect = (s: BindingSuggestion) => {
    setClientId(s.client_id);
    setDisplayName(s.display_name);
  };

  return (
    <View className="gap-3">
      <FormRow label="Type">
        {lockType ? (
          <Text className="text-accent text-sm font-semibold">{type}</Text>
        ) : (
          <SelectInput
            value={type}
            onChange={handleTypeChange}
            options={availableIntegrations.map((i) => ({ label: i.type, value: i.type }))}
          />
        )}
      </FormRow>
      {(suggestionsEndpoint && (suggestionsLoading || (suggestions && suggestions.length > 0))) && (
        <SuggestionsPicker
          suggestions={suggestions ?? []}
          isLoading={suggestionsLoading}
          onSelect={handleSuggestionSelect}
          selectedClientId={clientId}
        />
      )}
      <FormRow
        label="Client ID"
        description={binding?.client_id_description}
      >
        <TextInput
          value={clientId}
          onChangeText={setClientId}
          placeholder={binding?.client_id_placeholder ?? `${type}:...`}
        />
      </FormRow>
      <FormRow label="Display Name (optional)">
        <TextInput
          value={displayName}
          onChangeText={setDisplayName}
          placeholder={binding?.display_name_placeholder ?? ""}
        />
      </FormRow>
      {configFields && configFields.length > 0 && (
        <BindingConfigFields
          fields={configFields}
          values={configValues}
          onChange={handleConfigChange}
        />
      )}
      <View className="flex-row gap-2">
        <ActionButton
          label={isPending ? "Saving..." : submitLabel}
          onPress={() => onSubmit(type, clientId.trim(), displayName.trim(), collectConfigValues(configFields, configValues))}
          disabled={!type || !clientId.trim() || isPending}
          size="small"
        />
        <ActionButton
          label="Cancel"
          onPress={onCancel}
          variant="ghost"
          size="small"
        />
      </View>
      {isError && (
        <Text className="text-red-400 text-xs">
          {errorMessage ?? "Failed"}
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Config summary for binding display
// ---------------------------------------------------------------------------

function configSummaryText(
  dc: Record<string, any>,
  integration: AvailableIntegration | undefined,
): string | null {
  const fields = integration?.binding?.config_fields;
  if (!fields || fields.length === 0) {
    // Fallback: show raw dispatch_config keys (minus internal ones like type/chat_guid/server_url/password)
    const userKeys = Object.keys(dc).filter(
      (k) => !["type", "chat_guid", "server_url", "password"].includes(k),
    );
    if (userKeys.length === 0) return null;
    return userKeys
      .map((k) => {
        const v = dc[k];
        if (Array.isArray(v)) return `${k}: ${v.join(", ")}`;
        return `${k}: ${v}`;
      })
      .join(" · ");
  }
  const parts: string[] = [];
  for (const f of fields) {
    const v = dc[f.key];
    if (v === undefined || v === null) continue;
    if (v === f.default) continue;
    if (Array.isArray(v)) {
      if (v.length > 0) parts.push(`${f.label}: ${v.join(", ")}`);
    } else if (typeof v === "boolean") {
      parts.push(`${f.label}: ${v ? "on" : "off"}`);
    } else if (v !== "") {
      parts.push(`${f.label}: ${v}`);
    }
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

// ---------------------------------------------------------------------------
// Integrations Tab
// ---------------------------------------------------------------------------
export function IntegrationsTab({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
  const t = useThemeTokens();
  const { data: bindings, isLoading } = useChannelIntegrations(channelId);
  const { data: availableIntegrations } = useAvailableIntegrations();
  const bindMutation = useBindIntegration(channelId);
  const unbindMutation = useUnbindIntegration(channelId);

  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [unbindTarget, setUnbindTarget] = useState<{ id: string; type: string; clientId: string } | null>(null);

  const available = availableIntegrations ?? [];

  const handleAdd = async (type: string, clientId: string, displayName: string, dispatchConfig: Record<string, any>) => {
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
      dispatch_config: Object.keys(dispatchConfig).length > 0 ? dispatchConfig : undefined,
    });
    setShowAdd(false);
  };

  const handleEdit = async (bindingId: string, type: string, clientId: string, displayName: string, dispatchConfig: Record<string, any>) => {
    // Unbind old, bind new
    await unbindMutation.mutateAsync(bindingId);
    await bindMutation.mutateAsync({
      integration_type: type,
      client_id: clientId,
      display_name: displayName || undefined,
      dispatch_config: Object.keys(dispatchConfig).length > 0 ? dispatchConfig : undefined,
    });
    setEditingId(null);
  };

  if (isLoading) return <ActivityIndicator color={t.accent} />;

  return (
    <>
      {/* Activation section — above dispatcher bindings */}
      <ActivationsSection
        channelId={channelId}
        workspaceEnabled={workspaceEnabled}
      />

      <Section title="Dispatcher Bindings" description="Route bot responses to external services.">
        {(!bindings || bindings.length === 0) ? (
          <EmptyState message="No integrations bound to this channel" />
        ) : (
          <View className="gap-2">
            {bindings.map((b) => {
              const dc = b.dispatch_config ?? {};
              const configSummary = configSummaryText(dc, available.find((a) => a.type === b.integration_type));
              return editingId === b.id ? (
                <View
                  key={b.id}
                  className="bg-surface-raised border border-surface-border rounded-lg p-3"
                >
                  <BindingForm
                    availableIntegrations={available}
                    initialType={b.integration_type}
                    initialClientId={b.client_id}
                    initialDisplayName={b.display_name ?? ""}
                    initialDispatchConfig={dc}
                    onSubmit={(type, clientId, displayName, dispatchConfig) =>
                      handleEdit(b.id, type, clientId, displayName, dispatchConfig)
                    }
                    onCancel={() => setEditingId(null)}
                    isPending={bindMutation.isPending || unbindMutation.isPending}
                    isError={bindMutation.isError}
                    errorMessage={bindMutation.error instanceof Error ? bindMutation.error.message : undefined}
                    submitLabel="Save"
                    lockType
                  />
                </View>
              ) : (
                <div
                  key={b.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 14px",
                    borderRadius: 10,
                    border: `1px solid ${t.surfaceBorder}`,
                    background: t.surfaceRaised,
                  }}
                >
                  <StatusBadge label={b.integration_type} variant="info" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {b.client_id}
                    </div>
                    {b.display_name && (
                      <div style={{ fontSize: 11, color: t.textDim, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {b.display_name}
                      </div>
                    )}
                    {configSummary && (
                      <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                        {configSummary}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => setEditingId(b.id)}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: 6,
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    <Pencil size={13} color={t.textDim} />
                  </button>
                  <button
                    onClick={() => setUnbindTarget({ id: b.id, type: b.integration_type, clientId: b.client_id })}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      padding: 6,
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    <X size={14} color={t.danger} />
                  </button>
                </div>
              );
            })}
          </View>
        )}
      </Section>

      {!showAdd ? (
        <ActionButton
          label="Add Binding"
          onPress={() => setShowAdd(true)}
          variant="secondary"
          size="small"
          icon={<Plus size={12} />}
        />
      ) : (
        <Section title="Add Binding">
          <BindingForm
            availableIntegrations={available}
            initialType={available[0]?.type ?? ""}
            initialClientId=""
            initialDisplayName=""
            onSubmit={handleAdd}
            onCancel={() => setShowAdd(false)}
            isPending={bindMutation.isPending}
            isError={bindMutation.isError}
            errorMessage={bindMutation.error instanceof Error ? bindMutation.error.message : undefined}
            submitLabel="Bind"
          />
        </Section>
      )}

      <ConfirmDialog
        open={unbindTarget !== null}
        title="Unbind Integration"
        message={unbindTarget ? `Remove "${unbindTarget.type}" binding (${unbindTarget.clientId})?` : ""}
        confirmLabel="Unbind"
        variant="danger"
        onConfirm={() => {
          if (unbindTarget) unbindMutation.mutate(unbindTarget.id);
          setUnbindTarget(null);
        }}
        onCancel={() => setUnbindTarget(null)}
      />
    </>
  );
}
