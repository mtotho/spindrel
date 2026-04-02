import { forwardRef } from "react";
import { useThemeTokens } from "@/src/theme/tokens";

const BigTextarea = forwardRef<HTMLTextAreaElement, {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  minRows?: number;
  readOnly?: boolean;
}>(function BigTextarea({ value, onChange, placeholder, minRows = 24, readOnly }, ref) {
  const t = useThemeTokens();
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      readOnly={readOnly}
      rows={minRows}
      style={{
        width: "100%", fontFamily: "monospace", fontSize: 16, lineHeight: "1.6",
        padding: "12px 16px", borderRadius: 8,
        border: `1px solid ${t.inputBorder}`, background: t.inputBg, color: t.inputText,
        resize: "vertical", outline: "none", transition: "border-color 0.15s",
        minHeight: minRows * 20,
      }}
      onFocus={(e) => { e.target.style.borderColor = t.accent; }}
      onBlur={(e) => { e.target.style.borderColor = t.surfaceBorder; }}
    />
  );
});

export { BigTextarea };
