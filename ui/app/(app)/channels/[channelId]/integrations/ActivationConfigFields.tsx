import React, { useState, useEffect, useRef, useCallback } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUpdateActivationConfig } from "@/src/api/hooks/useChannels";
import { FormRow, TextInput, SelectInput, Toggle } from "@/src/components/shared/FormControls";
import type { ActivatableIntegration, ConfigField } from "@/src/types/api";
import { MultiSelectPicker } from "./MultiSelectPicker";

/**
 * Renders config fields for an active integration with save-on-change behavior.
 * Text fields are debounced; toggles/selects/multiselects save immediately.
 */
export function ActivationConfigFields({
  ig,
  channelId,
}: {
  ig: ActivatableIntegration;
  channelId: string;
}) {
  const t = useThemeTokens();
  const configMut = useUpdateActivationConfig(channelId);
  const fields = ig.config_fields;
  if (!fields || fields.length === 0) return null;

  const config = ig.activation_config ?? {};

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${t.surfaceBorder}` }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
        <div style={{
          fontSize: 10,
          fontWeight: 600,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: 1,
        }}>
          Configuration
        </div>
        <div style={{ fontSize: 11, color: configMut.isError ? t.danger : t.textDim }}>
          {configMut.isPending
            ? "Saving changes..."
            : configMut.isError
              ? (configMut.error instanceof Error ? configMut.error.message : "Save failed")
              : "Saves automatically"}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {fields.map((field) => (
          <ConfigFieldRow
            key={field.key}
            field={field}
            value={config[field.key] ?? field.default}
            save={(newValue) =>
              configMut.mutate({ integrationType: field.source_integration ?? ig.integration_type, config: { [field.key]: newValue } })
            }
          />
        ))}
      </div>
    </div>
  );
}

function ConfigFieldRow({
  field,
  value,
  save,
}: {
  field: ConfigField;
  value: any;
  save: (newValue: any) => void;
}) {
  const saveField = useCallback((newValue: any) => save(newValue), [save]);

  switch (field.type) {
    case "string":
      return (
        <DebouncedTextField
          field={field}
          value={value ?? ""}
          onSave={saveField}
        />
      );
    case "boolean":
      return (
        <Toggle
          label={field.label}
          description={field.description}
          value={value ?? false}
          onChange={saveField}
        />
      );
    case "number":
      return (
        <DebouncedTextField
          field={field}
          value={value != null ? String(value) : ""}
          onSave={(v: string) => saveField(v === "" ? undefined : Number(v))}
          type="number"
        />
      );
    case "select":
      return (
        <FormRow label={field.label} description={field.description}>
          <SelectInput
            value={value ?? ""}
            onChange={saveField}
            options={field.options ?? []}
          />
        </FormRow>
      );
    case "multiselect":
      return (
        <FormRow label={field.label} description={field.description}>
          <MultiSelectPicker
            options={field.options ?? []}
            selected={Array.isArray(value) ? value : []}
            onChange={saveField}
          />
        </FormRow>
      );
    default:
      return null;
  }
}

function DebouncedTextField({
  field,
  value,
  onSave,
  type,
}: {
  field: ConfigField;
  value: string;
  onSave: (v: string) => void;
  type?: string;
}) {
  const [local, setLocal] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setLocal(value);
  }, [value]);

  const handleChange = (v: string) => {
    setLocal(v);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => onSave(v), 600);
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <FormRow label={field.label} description={field.description}>
      <TextInput
        value={local}
        onChangeText={handleChange}
        type={type}
      />
    </FormRow>
  );
}
