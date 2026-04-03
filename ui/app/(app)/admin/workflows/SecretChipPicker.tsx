/**
 * Multi-select chip picker for secrets.
 * Shows available secrets as clickable chips — selected ones are highlighted.
 */
import { type ThemeTokens } from "@/src/theme/tokens";
interface SecretChipPickerProps {
  /** Full list of available secret names to pick from */
  available: string[];
  /** Currently selected secret names */
  selected: string[];
  onChange: (secrets: string[]) => void;
  disabled?: boolean;
  t: ThemeTokens;
  /** Show "none available" with link to secrets page when empty */
  emptyMessage?: string;
}

export function SecretChipPicker({
  available, selected, onChange, disabled, t,
  emptyMessage = "No secrets in vault.",
}: SecretChipPickerProps) {
  const toggle = (name: string) => {
    if (disabled) return;
    if (selected.includes(name)) {
      onChange(selected.filter((s) => s !== name));
    } else {
      onChange([...selected, name]);
    }
  };

  const stale = selected.filter((s) => !available.includes(s));

  if (available.length === 0 && stale.length === 0) {
    return (
      <span style={{ fontSize: 12, color: t.textDim }}>
        {emptyMessage}{" "}
        <a href="/admin/secret-values" style={{ color: t.accent, fontSize: 12 }}>
          Manage secrets
        </a>
      </span>
    );
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {available.map((name) => {
        const isSelected = selected.includes(name);
        return (
          <button
            key={name}
            onClick={() => toggle(name)}
            disabled={disabled}
            style={{
              padding: "3px 10px", borderRadius: 6,
              fontSize: 12, cursor: disabled ? "default" : "pointer",
              border: `1px solid ${isSelected ? t.accentBorder : t.surfaceBorder}`,
              background: isSelected ? t.accentSubtle : "transparent",
              color: isSelected ? t.accent : t.textDim,
              fontWeight: isSelected ? 600 : 400,
              opacity: disabled ? 0.6 : 1,
              transition: "all 0.15s ease",
            }}
          >
            {name}
          </button>
        );
      })}
      {stale.map((name) => (
        <button
          key={name}
          onClick={() => !disabled && onChange(selected.filter((s) => s !== name))}
          disabled={disabled}
          title="This secret no longer exists — click to remove"
          style={{
            padding: "3px 10px", borderRadius: 6,
            fontSize: 12, cursor: disabled ? "default" : "pointer",
            border: `1px solid ${t.dangerBorder || "#e55"}`,
            background: "transparent",
            color: t.danger || "#e55",
            fontWeight: 400, opacity: 0.7,
            textDecoration: "line-through",
          }}
        >
          {name}
        </button>
      ))}
    </div>
  );
}
