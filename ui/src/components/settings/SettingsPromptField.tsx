/**
 * Settings-adapted prompt field that wraps LlmPrompt.
 * For prompts with built-in defaults: shows the default as read-only text,
 * with a "Customize" action to switch to an editable LlmPrompt.
 */
import { useState, useEffect } from "react";
import { ChevronDown, Pencil, RotateCcw } from "lucide-react";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { useThemeTokens } from "@/src/theme/tokens";
import type { SettingItem } from "@/src/api/hooks/useSettings";

interface Props {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}

const FIELD_TYPE_MAP: Record<string, string> = {
  MEMORY_FLUSH_DEFAULT_PROMPT: "memory_flush",
  MEMORY_HYGIENE_PROMPT: "memory_hygiene",
  SKILL_REVIEW_PROMPT: "skill_review",
  HEARTBEAT_DEFAULT_PROMPT: "heartbeat",
  HEARTBEAT_REPETITION_WARNING: "heartbeat_warning",
};

export function SettingsPromptField({ item, value, onChange }: Props) {
  const t = useThemeTokens();
  const fieldType = FIELD_TYPE_MAP[item.key];
  const hasBuiltinDefault = !!item.builtin_default;
  const hasCustomValue = !!value;

  const [editing, setEditing] = useState(!hasBuiltinDefault || hasCustomValue);
  const [showDefault, setShowDefault] = useState(false);

  useEffect(() => {
    if (hasBuiltinDefault && !value) setEditing(false);
  }, [value, hasBuiltinDefault]);

  // No built-in default — just show the editor
  if (!hasBuiltinDefault) {
    return (
      <div style={{ width: "100%" }}>
        <LlmPrompt
          value={value}
          onChange={onChange}
          placeholder="Enter prompt..."
          rows={8}
          fieldType={fieldType}
          generateContext={`Setting: ${item.label}. ${item.description}`}
        />
      </div>
    );
  }

  // Has built-in default — toggle between viewing default and editing custom
  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 8 }}>
      {editing ? (
        <>
          <LlmPrompt
            value={value}
            onChange={onChange}
            placeholder="Enter custom prompt..."
            rows={8}
            fieldType={fieldType}
            generateContext={`Setting: ${item.label}. ${item.description}`}
          />
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12 }}>
            <button
              type="button"
              onClick={() => { onChange(""); setEditing(false); }}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                fontSize: 11, color: t.textDim, background: "transparent",
                border: "none", cursor: "pointer", padding: 0,
              }}
            >
              <RotateCcw size={11} />
              Revert to built-in default
            </button>
          </div>
          {/* Collapsible reference to built-in default */}
          <div style={{ borderRadius: 6, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden" }}>
            <button
              type="button"
              onClick={() => setShowDefault(!showDefault)}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                padding: "5px 10px", width: "100%", textAlign: "left",
                background: "transparent", border: "none", cursor: "pointer",
              }}
            >
              <ChevronDown
                size={11}
                color={t.textDim}
                style={{ transform: showDefault ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" }}
              />
              <span style={{ fontSize: 10, color: t.textDim }}>
                View built-in default for reference
              </span>
            </button>
            {showDefault && (
              <div style={{ padding: "0 10px 8px 10px" }}>
                <pre style={{
                  margin: 0, fontSize: 10, lineHeight: "16px", fontFamily: "monospace",
                  whiteSpace: "pre-wrap", color: t.textDim,
                  background: t.surfaceOverlay, borderRadius: 4, padding: 8,
                }}>
                  {item.builtin_default}
                </pre>
              </div>
            )}
          </div>
        </>
      ) : (
        /* View mode — show built-in default as read-only with customize button */
        <div style={{ borderRadius: 8, border: `1px solid ${t.surfaceBorder}`, overflow: "hidden" }}>
          <div style={{
            display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
            padding: "8px 12px", borderBottom: `1px solid ${t.surfaceBorder}`,
          }}>
            <span style={{ fontSize: 10, fontWeight: 600, color: t.purple }}>
              Built-in default active
            </span>
            <button
              type="button"
              onClick={() => { onChange(item.builtin_default!); setEditing(true); }}
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                fontSize: 10, color: t.accent, background: "transparent",
                border: "none", cursor: "pointer", padding: 0,
              }}
            >
              <Pencil size={10} />
              Customize
            </button>
          </div>
          <pre style={{
            margin: 0, fontSize: 11, lineHeight: "18px", fontFamily: "monospace",
            whiteSpace: "pre-wrap", color: t.textMuted, padding: 12,
            maxHeight: 200, overflowY: "auto",
          }}>
            {item.builtin_default}
          </pre>
        </div>
      )}
    </div>
  );
}
