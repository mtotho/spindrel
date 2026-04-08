import React, { useState, useEffect, useRef, useCallback } from "react";
import { Check } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useUpdateActivationConfig } from "@/src/api/hooks/useChannels";
import { FormRow, TextInput, SelectInput, Toggle } from "@/src/components/shared/FormControls";
import type { ActivatableIntegration, ConfigField } from "@/src/types/api";

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
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {options.map((opt) => {
        const isChecked = selected.includes(opt.value);
        return (
          <button
            key={opt.value}
            onClick={() => toggle(opt.value)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
            }}
          >
            <div
              style={{
                width: 16,
                height: 16,
                borderRadius: 3,
                border: `1.5px solid ${isChecked ? t.accent : t.surfaceBorder}`,
                backgroundColor: isChecked ? t.accent : "transparent",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.1s",
              }}
            >
              {isChecked && <Check size={11} color="#fff" strokeWidth={3} />}
            </div>
            <span style={{ fontSize: 13, color: t.text }}>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

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
  const fields = ig.config_fields;
  if (!fields || fields.length === 0) return null;

  const config = ig.activation_config ?? {};

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.surfaceBorder}` }}>
      <div style={{
        fontSize: 11,
        fontWeight: 600,
        color: t.textDim,
        marginBottom: 8,
        textTransform: "uppercase",
        letterSpacing: 0.5,
      }}>
        Configuration
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {fields.map((field) => (
          <ConfigFieldRow
            key={field.key}
            field={field}
            value={config[field.key] ?? field.default}
            channelId={channelId}
            integrationType={field.source_integration ?? ig.integration_type}
          />
        ))}
      </div>
    </div>
  );
}

function SaveIndicator({ visible }: { visible: boolean }) {
  const t = useThemeTokens();
  if (!visible) return null;
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 3,
      fontSize: 10,
      color: t.accent,
      fontWeight: 600,
      opacity: visible ? 1 : 0,
      transition: "opacity 0.2s",
    }}>
      <Check size={10} /> Saved
    </span>
  );
}

function ConfigFieldRow({
  field,
  value,
  channelId,
  integrationType,
}: {
  field: ConfigField;
  value: any;
  channelId: string;
  integrationType: string;
}) {
  const configMut = useUpdateActivationConfig(channelId);
  const [showSaved, setShowSaved] = useState(false);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const save = useCallback(
    (newValue: any) => {
      configMut.mutate(
        { integrationType, config: { [field.key]: newValue } },
        {
          onSuccess: () => {
            setShowSaved(true);
            if (savedTimer.current) clearTimeout(savedTimer.current);
            savedTimer.current = setTimeout(() => setShowSaved(false), 1500);
          },
        },
      );
    },
    [configMut, integrationType, field.key],
  );

  useEffect(() => {
    return () => { if (savedTimer.current) clearTimeout(savedTimer.current); };
  }, []);

  const labelSuffix = <SaveIndicator visible={showSaved} />;

  switch (field.type) {
    case "string":
      return (
        <DebouncedTextField
          field={field}
          value={value ?? ""}
          onSave={save}
          suffix={labelSuffix}
        />
      );
    case "boolean":
      return (
        <div>
          <Toggle
            label={field.label}
            description={field.description}
            value={value ?? false}
            onChange={save}
          />
          {labelSuffix}
        </div>
      );
    case "number":
      return (
        <DebouncedTextField
          field={field}
          value={value != null ? String(value) : ""}
          onSave={(v: string) => save(v === "" ? undefined : Number(v))}
          type="number"
          suffix={labelSuffix}
        />
      );
    case "select":
      return (
        <FormRow label={<>{field.label} {labelSuffix}</>} description={field.description}>
          <SelectInput
            value={value ?? ""}
            onChange={save}
            options={field.options ?? []}
          />
        </FormRow>
      );
    case "multiselect":
      return (
        <FormRow label={<>{field.label} {labelSuffix}</>} description={field.description}>
          <MultiSelectPicker
            options={field.options ?? []}
            selected={Array.isArray(value) ? value : []}
            onChange={save}
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
  suffix,
}: {
  field: ConfigField;
  value: string;
  onSave: (v: string) => void;
  type?: string;
  suffix?: React.ReactNode;
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
    <FormRow label={<>{field.label} {suffix}</>} description={field.description}>
      <TextInput
        value={local}
        onChangeText={handleChange}
        type={type}
      />
    </FormRow>
  );
}
