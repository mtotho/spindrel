/**
 * Default execution config editor for workflows.
 * Extracted from WorkflowFormParts.tsx.
 */
import { useState, useCallback, useEffect } from "react";
import { View, Text } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { useBots } from "@/src/api/hooks/useBots";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FormRow, Toggle } from "@/src/components/shared/FormControls";

interface DefaultsEditorProps {
  value: Record<string, any>;
  onChange: (v: Record<string, any>) => void;
  disabled?: boolean;
}

export function DefaultsEditor({ value, onChange, disabled }: DefaultsEditorProps) {
  const t = useThemeTokens();
  const { data: bots } = useBots();
  const [showRaw, setShowRaw] = useState(false);
  const [rawText, setRawText] = useState(JSON.stringify(value, null, 2));

  // Sync rawText when value changes externally (e.g., from YAML tab)
  useEffect(() => {
    if (!showRaw) {
      setRawText(JSON.stringify(value, null, 2));
    }
  }, [value, showRaw]);

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 13, width: "100%", outline: "none",
    opacity: disabled ? 0.6 : 1,
  };

  const update = useCallback((key: string, val: any) => {
    const next = { ...value };
    if (val === "" || val === null || val === undefined) {
      delete next[key];
    } else {
      next[key] = val;
    }
    onChange(next);
    setRawText(JSON.stringify(next, null, 2));
  }, [value, onChange]);

  if (showRaw) {
    let isValid = true;
    try { JSON.parse(rawText); } catch { isValid = false; }
    return (
      <View style={{ gap: 8 }}>
        <textarea
          value={rawText}
          onChange={(e) => {
            setRawText(e.target.value);
            try {
              onChange(JSON.parse(e.target.value));
            } catch { /* wait for valid JSON */ }
          }}
          style={{
            ...inputStyle, fontFamily: "monospace", fontSize: 12,
            minHeight: 120, resize: "vertical" as const,
            borderColor: isValid ? t.inputBorder : t.danger,
          }}
          disabled={disabled}
        />
        {!isValid && rawText.trim() && (
          <Text style={{ color: t.danger, fontSize: 11 }}>Invalid JSON</Text>
        )}
        <button
          onClick={() => setShowRaw(false)}
          style={{
            background: "none", border: "none", color: t.accent,
            fontSize: 11, cursor: "pointer", padding: 0, alignSelf: "flex-start",
          }}
        >
          Form mode
        </button>
      </View>
    );
  }

  return (
    <View style={{ gap: 14 }}>
      <FormRow label="Bot" description="Default bot for all steps">
        <select
          value={value.bot_id || ""}
          onChange={(e) => update("bot_id", e.target.value || undefined)}
          style={{ ...inputStyle, cursor: "pointer" }}
          disabled={disabled}
        >
          <option value="">Select bot...</option>
          {bots?.map((b) => (
            <option key={b.id} value={b.id}>{b.name} ({b.id})</option>
          ))}
        </select>
      </FormRow>

      <FormRow label="Model" description="Default model for all steps">
        <LlmModelDropdown
          value={value.model || ""}
          onChange={(v) => update("model", v || undefined)}
          placeholder="Use bot default"
          allowClear
        />
      </FormRow>

      <FormRow label="Timeout (seconds)" description="Default step timeout">
        <input
          type="number"
          value={value.timeout ?? ""}
          onChange={(e) => update("timeout", e.target.value ? parseInt(e.target.value) : undefined)}
          placeholder="300"
          style={inputStyle}
          disabled={disabled}
        />
      </FormRow>

      <FormRow label="Tools" description="Default tools for all steps (comma-separated)">
        <input
          value={(value.tools || []).join(", ")}
          onChange={(e) => update("tools", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
          placeholder="web_search, exec_command"
          style={inputStyle}
          disabled={disabled}
        />
      </FormRow>

      <FormRow label="Carapaces" description="Default carapaces for all steps">
        <input
          value={(value.carapaces || []).join(", ")}
          onChange={(e) => update("carapaces", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
          placeholder="qa, code-review"
          style={inputStyle}
          disabled={disabled}
        />
      </FormRow>

      <Toggle
        value={!!value.inject_prior_results}
        onChange={(v) => update("inject_prior_results", v || undefined)}
        label="Inject Prior Results"
        description="Include completed step results in each step's system preamble"
      />

      {value.inject_prior_results && (
        <FormRow label="Prior Result Max Chars" description="Truncate each prior result to this length">
          <input
            type="number"
            value={value.prior_result_max_chars ?? ""}
            onChange={(e) => update("prior_result_max_chars", e.target.value ? parseInt(e.target.value) : undefined)}
            placeholder="500"
            style={inputStyle}
            disabled={disabled}
          />
        </FormRow>
      )}

      <FormRow label="Result Max Chars" description="Max characters stored from step results (default: 2000)">
        <input
          type="number"
          value={value.result_max_chars ?? ""}
          onChange={(e) => update("result_max_chars", e.target.value ? parseInt(e.target.value) : undefined)}
          placeholder="2000"
          style={inputStyle}
          disabled={disabled}
        />
      </FormRow>

      <button
        onClick={() => { setRawText(JSON.stringify(value, null, 2)); setShowRaw(true); }}
        style={{
          background: "none", border: "none", color: t.accent,
          fontSize: 11, cursor: "pointer", padding: 0, alignSelf: "flex-start",
        }}
      >
        Raw JSON
      </button>
    </View>
  );
}
