import React, { useState, useEffect, useRef, useCallback } from "react";
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
  const configMut = useUpdateActivationConfig(channelId);
  const fields = ig.config_fields;
  if (!fields || fields.length === 0) return null;

  const config = ig.activation_config ?? {};
  const saveStatus = configMut.isPending
    ? "Saving changes..."
    : configMut.isError
      ? (configMut.error instanceof Error ? configMut.error.message : "Save failed")
      : "Saves automatically";

  return (
    <div className="mt-3 border-t border-surface-border pt-3">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
          Configuration
        </div>
        <div className={`text-[11px] ${configMut.isError ? "text-danger" : "text-text-dim"}`}>
          {saveStatus}
        </div>
      </div>
      <div className="flex flex-col gap-2.5">
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
