import { Check } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

export function MultiSelectPicker({
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
              display: "flex", flexDirection: "row",
              alignItems: "center",
              gap: 8,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "2px 0",
            }}
          >
            <div
              style={{
                width: 16,
                height: 16,
                borderRadius: 4,
                border: `1.5px solid ${isChecked ? t.accent : t.surfaceBorder}`,
                backgroundColor: isChecked ? t.accent : "transparent",
                display: "flex", flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.12s",
                flexShrink: 0,
              }}
            >
              {isChecked && <Check size={10} color="#fff" strokeWidth={3} />}
            </div>
            <span style={{ fontSize: 13, color: t.text, lineHeight: "1.3" }}>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
