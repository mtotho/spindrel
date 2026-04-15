import { useCallback } from "react";
import { LlmModelDropdown } from "./LlmModelDropdown";
import { useThemeTokens } from "../../theme/tokens";

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
  const t = useThemeTokens();

  const updateEntry = useCallback(
    (index: number, model: string, providerId?: string | null) => {
      const next = [...value];
      next[index] = { ...next[index], model, provider_id: providerId ?? null };
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
        <div key={i} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <div style={{ flex: 1 }}>
            <LlmModelDropdown
              value={entry.model}
              selectedProviderId={entry.provider_id}
              onChange={(m, pid) => updateEntry(i, m, pid)}
              placeholder={placeholder ?? "Select fallback model..."}
              allowClear={false}
            />
          </div>
          <span
            onClick={() => removeEntry(i)}
            style={{
              color: t.textDim,
              cursor: "pointer",
              fontSize: 14,
              lineHeight: 1,
              padding: "4px 6px",
              borderRadius: 4,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = t.danger; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = t.textDim; }}
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
          border: `1px dashed ${t.surfaceBorder}`,
          borderRadius: 6,
          color: t.textMuted,
          cursor: "pointer",
          fontSize: 12,
          padding: "4px 12px",
          marginTop: value.length > 0 ? 2 : 0,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = t.accent;
          (e.currentTarget as HTMLElement).style.color = t.accent;
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = t.surfaceBorder;
          (e.currentTarget as HTMLElement).style.color = t.textMuted;
        }}
      >
        + Add fallback
      </button>
    </div>
  );
}
