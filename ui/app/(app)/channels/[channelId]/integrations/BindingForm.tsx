import { useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useBindingSuggestions,
  type AvailableIntegration,
  type BindingSuggestion,
} from "@/src/api/hooks/useChannels";
import {
  FormRow, TextInput, SelectInput, Toggle,
} from "@/src/components/shared/FormControls";
import { ActionButton } from "@/src/components/shared/SettingsControls";
import type { ConfigField } from "@/src/types/api";
import { initConfigValues, collectConfigValues } from "./helpers";
import { SuggestionsPicker } from "./SuggestionsPicker";
import { MultiSelectPicker } from "./MultiSelectPicker";

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

export function BindingForm({
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
  const t = useThemeTokens();
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
    if (s.config_values) {
      setConfigValues((prev) => ({ ...prev, ...s.config_values }));
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <FormRow label="Type">
        {lockType ? (
          <span style={{ fontSize: 13, fontWeight: 600, color: t.accent }}>{type}</span>
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
      <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
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
      </div>
      {isError && (
        <span style={{ fontSize: 12, color: t.danger }}>
          {errorMessage ?? "Failed"}
        </span>
      )}
    </div>
  );
}
