/**
 * Structured form editors for workflow defaults, params, and triggers.
 * Replaces JSON textareas with proper form controls.
 */
import { useState, useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { useBots } from "@/src/api/hooks/useBots";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FormRow, Toggle } from "@/src/components/shared/FormControls";
import { Plus, X } from "lucide-react";

// ---------------------------------------------------------------------------
// DefaultsEditor
// ---------------------------------------------------------------------------

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
      {/* Bot ID */}
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

      {/* Model */}
      <FormRow label="Model" description="Default model for all steps">
        <LlmModelDropdown
          value={value.model || ""}
          onChange={(v) => update("model", v || undefined)}
          placeholder="Use bot default"
          allowClear
        />
      </FormRow>

      {/* Timeout */}
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

      {/* Tools */}
      <FormRow label="Tools" description="Default tools for all steps (comma-separated)">
        <input
          value={(value.tools || []).join(", ")}
          onChange={(e) => update("tools", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
          placeholder="web_search, exec_command"
          style={inputStyle}
          disabled={disabled}
        />
      </FormRow>

      {/* Carapaces */}
      <FormRow label="Carapaces" description="Default carapaces for all steps">
        <input
          value={(value.carapaces || []).join(", ")}
          onChange={(e) => update("carapaces", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
          placeholder="qa, code-review"
          style={inputStyle}
          disabled={disabled}
        />
      </FormRow>

      {/* Inject prior results */}
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

      {/* Result max chars */}
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


// ---------------------------------------------------------------------------
// ParamsEditor — key-value table
// ---------------------------------------------------------------------------

interface ParamDef {
  type: string;
  required?: boolean;
  default?: any;
  description?: string;
}

interface ParamsEditorProps {
  value: Record<string, ParamDef>;
  onChange: (v: Record<string, any>) => void;
  disabled?: boolean;
}

export function ParamsEditor({ value, onChange, disabled }: ParamsEditorProps) {
  const t = useThemeTokens();
  const entries = Object.entries(value);

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 6, padding: "6px 10px", color: t.inputText,
    fontSize: 12, outline: "none", width: "100%",
    opacity: disabled ? 0.6 : 1,
  };

  const updateParam = (oldName: string, newName: string, def: ParamDef) => {
    const next = { ...value };
    if (oldName !== newName) delete next[oldName];
    next[newName] = def;
    onChange(next);
  };

  const removeParam = (name: string) => {
    const next = { ...value };
    delete next[name];
    onChange(next);
  };

  const addParam = () => {
    const name = `param_${entries.length + 1}`;
    onChange({ ...value, [name]: { type: "string" } });
  };

  return (
    <View style={{ gap: 6 }}>
      {/* Header */}
      {entries.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 80px 50px 1fr 24px",
          gap: 6, padding: "0 4px",
          fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase",
          letterSpacing: 0.5,
        }}>
          <span>Name</span>
          <span>Type</span>
          <span>Req</span>
          <span>Default</span>
          <span />
        </div>
      )}

      {entries.map(([name, def]) => (
        <div
          key={name}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 80px 50px 1fr 24px",
            gap: 6, alignItems: "center",
          }}
        >
          <input
            value={name}
            onChange={(e) => updateParam(name, e.target.value, def)}
            style={inputStyle}
            disabled={disabled}
          />
          <select
            value={def.type || "string"}
            onChange={(e) => updateParam(name, name, { ...def, type: e.target.value })}
            style={{ ...inputStyle, cursor: "pointer" }}
            disabled={disabled}
          >
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="boolean">boolean</option>
          </select>
          <input
            type="checkbox"
            checked={!!def.required}
            onChange={(e) => updateParam(name, name, { ...def, required: e.target.checked })}
            disabled={disabled}
            style={{ width: 16, height: 16, cursor: "pointer" }}
          />
          <input
            value={def.default ?? ""}
            onChange={(e) => updateParam(name, name, { ...def, default: e.target.value || undefined })}
            placeholder="default"
            style={inputStyle}
            disabled={disabled}
          />
          {!disabled && (
            <Pressable onPress={() => removeParam(name)} style={{ opacity: 0.5 }}>
              <X size={14} color={t.textDim} />
            </Pressable>
          )}
        </div>
      ))}

      {!disabled && (
        <Pressable
          onPress={addParam}
          style={{
            flexDirection: "row", alignItems: "center", gap: 4,
            paddingVertical: 6,
          }}
        >
          <Plus size={12} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12 }}>Add Parameter</Text>
        </Pressable>
      )}
    </View>
  );
}


// ---------------------------------------------------------------------------
// TriggersEditor — three toggles
// ---------------------------------------------------------------------------

interface TriggersEditorProps {
  value: Record<string, boolean>;
  onChange: (v: Record<string, boolean>) => void;
  disabled?: boolean;
}

export function TriggersEditor({ value, onChange, disabled }: TriggersEditorProps) {
  const update = (key: string, v: boolean) => onChange({ ...value, [key]: v });

  return (
    <View style={{ gap: 4 }}>
      <Toggle
        value={!!value.tool}
        onChange={(v) => update("tool", v)}
        label="Tool"
        description="Can be triggered by bots via manage_workflow tool"
      />
      <Toggle
        value={!!value.api}
        onChange={(v) => update("api", v)}
        label="API"
        description="Can be triggered via the admin API"
      />
      <Toggle
        value={!!value.heartbeat}
        onChange={(v) => update("heartbeat", v)}
        label="Heartbeat"
        description="Can be triggered from heartbeat prompts"
      />
      <Toggle
        value={!!value.task}
        onChange={(v) => update("task", v)}
        label="Scheduled Task"
        description="Can be triggered by scheduled tasks"
      />
    </View>
  );
}
