/**
 * Workflow parameter editor — compact key-value table.
 * Extracted from WorkflowFormParts.tsx.
 */
import { View, Text, Pressable } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { Plus, X } from "lucide-react";

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
    const existing = new Set(Object.keys(value));
    let n = entries.length + 1;
    while (existing.has(`param_${n}`)) n++;
    onChange({ ...value, [`param_${n}`]: { type: "string" } });
  };

  if (entries.length === 0) {
    return (
      <View style={{ gap: 8 }}>
        <Text style={{ color: t.textDim, fontSize: 12, fontStyle: "italic" }}>
          No parameters defined
        </Text>
        {!disabled && (
          <Pressable
            onPress={addParam}
            style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 }}
          >
            <Plus size={12} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 12 }}>Add Parameter</Text>
          </Pressable>
        )}
      </View>
    );
  }

  return (
    <View style={{ gap: 6 }}>
      {/* Header */}
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

      {entries.map(([name, def], idx) => (
        <div
          key={idx}
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
          style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 6 }}
        >
          <Plus size={12} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12 }}>Add Parameter</Text>
        </Pressable>
      )}
    </View>
  );
}
