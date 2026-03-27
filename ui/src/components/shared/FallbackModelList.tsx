import { useCallback } from "react";
import { LlmModelDropdown } from "./LlmModelDropdown";

export interface FallbackModelEntry {
  model: string;
  provider_id?: string | null;
}

interface Props {
  value: FallbackModelEntry[];
  onChange: (value: FallbackModelEntry[]) => void;
  placeholder?: string;
}

/**
 * Ordered list of fallback models. Each row is an LlmModelDropdown with a
 * remove button. "Add fallback" button at the bottom.
 */
export function FallbackModelList({ value, onChange, placeholder }: Props) {
  const updateEntry = useCallback(
    (index: number, model: string) => {
      const next = [...value];
      next[index] = { ...next[index], model };
      onChange(next);
    },
    [value, onChange],
  );

  const removeEntry = useCallback(
    (index: number) => {
      onChange(value.filter((_, i) => i !== index));
    },
    [value, onChange],
  );

  const addEntry = useCallback(() => {
    onChange([...value, { model: "", provider_id: null }]);
  }, [value, onChange]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {value.map((entry, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ flex: 1 }}>
            <LlmModelDropdown
              value={entry.model}
              onChange={(m) => updateEntry(i, m)}
              placeholder={placeholder ?? "Select fallback model..."}
              allowClear={false}
            />
          </div>
          <span
            onClick={() => removeEntry(i)}
            style={{
              color: "#666",
              cursor: "pointer",
              fontSize: 14,
              lineHeight: 1,
              padding: "4px 6px",
              borderRadius: 4,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "#ef4444"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "#666"; }}
          >
            ✕
          </span>
        </div>
      ))}
      <button
        type="button"
        onClick={addEntry}
        style={{
          alignSelf: "flex-start",
          background: "none",
          border: "1px dashed #444",
          borderRadius: 6,
          color: "#888",
          cursor: "pointer",
          fontSize: 12,
          padding: "4px 12px",
          marginTop: value.length > 0 ? 2 : 0,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = "#3b82f6";
          (e.currentTarget as HTMLElement).style.color = "#3b82f6";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = "#444";
          (e.currentTarget as HTMLElement).style.color = "#888";
        }}
      >
        + Add fallback
      </button>
    </div>
  );
}
