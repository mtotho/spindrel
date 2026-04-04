/**
 * DateTimePicker — thin wrapper around <input type="datetime-local">.
 * Value format: "YYYY-MM-DDTHH:MM" (same as datetime-local).
 * Web-only — uses native browser date/time picker which handles typing,
 * calendar dropdown, and z-index correctly.
 */
import { Calendar, X } from "lucide-react";
import { useRef } from "react";
import { useThemeTokens } from "../../theme/tokens";

interface Props {
  value: string; // "YYYY-MM-DDTHH:MM" or ""
  onChange: (v: string) => void;
  placeholder?: string;
}

export function DateTimePicker({ value, onChange, placeholder = "Select date & time..." }: Props) {
  const t = useThemeTokens();
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <Calendar
        size={14}
        color={t.textMuted}
        style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}
      />
      <input
        ref={inputRef}
        type="datetime-local"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%",
          background: t.inputBg,
          border: `1px solid ${t.inputBorder}`,
          borderRadius: 8,
          padding: "8px 32px 8px 34px",
          color: t.inputText,
          fontSize: 13,
          outline: "none",
          colorScheme: "dark",
        }}
      />
      {value && (
        <span
          onClick={() => onChange("")}
          style={{
            position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
            cursor: "pointer", lineHeight: 0, padding: 2,
          }}
        >
          <X size={13} color={t.textDim} />
        </span>
      )}
    </div>
  );
}
