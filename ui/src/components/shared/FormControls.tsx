/**
 * Shared form control primitives for settings pages.
 * All use raw HTML elements for web compat (no RN TextInput issues).
 */

import { ChevronDown } from "lucide-react";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";

// ---------------------------------------------------------------------------
// Section card
// ---------------------------------------------------------------------------
export function Section({ title, description, action, children, noDivider = false }: {
  title: React.ReactNode;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  noDivider?: boolean;
}) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      gap: 14,
      borderTop: "none",
      paddingTop: noDivider ? 0 : 4,
    }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <span style={{ color: t.text, fontSize: 14, fontWeight: 600, display: "block" }}>{title}</span>
          {description && (
            <span style={{ color: t.textDim, fontSize: 12, lineHeight: 1.5, marginTop: 3, display: "block", maxWidth: 860 }}>{description}</span>
          )}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form row (label + control + description)
// ---------------------------------------------------------------------------
export function FormRow({ label, description, children }: {
  label: React.ReactNode;
  description?: string;
  children: React.ReactNode;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ color: t.textMuted, fontSize: 12, fontWeight: 500 }}>{label}</label>
      {children}
      {description && (
        <div style={{ color: t.textDim, fontSize: 12 }}>{description}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Text / number input
// ---------------------------------------------------------------------------
function makeInputStyle(t: ThemeTokens): React.CSSProperties {
  return {
    background: t.inputBg,
    border: `1px solid ${t.inputBorder}`,
    borderRadius: 7,
    padding: "9px 12px",
    color: t.inputText,
    fontSize: 14,
    width: "100%",
    outline: "none",
    transition: "border-color 0.15s, background-color 0.15s",
  };
}

export function TextInput({ value, onChangeText, placeholder, type = "text", style }: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  type?: string;
  style?: React.CSSProperties;
}) {
  const t = useThemeTokens();
  const inputStyle = makeInputStyle(t);
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChangeText(e.target.value)}
      placeholder={placeholder}
      style={{ ...inputStyle, ...style }}
      onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
      onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
    />
  );
}

// ---------------------------------------------------------------------------
// Select input
// ---------------------------------------------------------------------------
export function SelectInput({ value, onChange, options, style }: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
  style?: React.CSSProperties;
}) {
  const t = useThemeTokens();
  const inputStyle = makeInputStyle(t);
  const containerStyle: React.CSSProperties = {
    position: "relative",
    width: style?.width ?? "100%",
    minWidth: style?.minWidth,
    maxWidth: style?.maxWidth,
    flex: style?.flex,
  };
  const selectStyle: React.CSSProperties = {
    ...inputStyle,
    ...style,
    width: "100%",
    minWidth: undefined,
    maxWidth: undefined,
    flex: undefined,
    cursor: "pointer",
    appearance: "none",
    WebkitAppearance: "none",
    paddingRight: 34,
  };
  return (
    <div style={containerStyle}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={selectStyle}
        onFocus={(e) => { (e.target as HTMLSelectElement).style.borderColor = t.inputBorderFocus; }}
        onBlur={(e) => { (e.target as HTMLSelectElement).style.borderColor = t.inputBorder; }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      <span
        aria-hidden
        style={{
          position: "absolute",
          right: 11,
          top: "50%",
          transform: "translateY(-50%)",
          pointerEvents: "none",
          color: t.textDim,
          display: "flex",
        }}
      >
        <ChevronDown size={14} />
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toggle switch
// ---------------------------------------------------------------------------
export function Toggle({ value, onChange, label, description }: {
  value: boolean;
  onChange: (v: boolean) => void;
  label?: React.ReactNode;
  description?: string;
}) {
  const t = useThemeTokens();
  return (
    <div
      role="switch"
      aria-checked={value}
      tabIndex={0}
      onClick={() => onChange(!value)}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onChange(!value); } }}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "flex-start",
        gap: 10,
        padding: "8px 0",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {/* Custom toggle track */}
      <div style={{
        width: 36,
        height: 20,
        borderRadius: 10,
        background: value ? t.accent : t.surfaceBorder,
        position: "relative",
        flexShrink: 0,
        marginTop: 1,
        transition: "background 0.15s",
      }}>
        <div style={{
          width: 16,
          height: 16,
          borderRadius: 8,
          background: t.text,
          position: "absolute",
          top: 2,
          left: value ? 18 : 2,
          transition: "left 0.15s",
        }} />
      </div>
      {(label || description) && (
        <div>
          {label && <div style={{ fontSize: 13, color: t.text }}>{label}</div>}
          {description && (
            <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>{description}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slider input
// ---------------------------------------------------------------------------
export function Slider({ value, onChange, min, max, step, disabled, defaultValue }: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  defaultValue?: number | null;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, opacity: disabled ? 0.4 : 1 }}>
      <span style={{ fontSize: 11, color: t.textDim, minWidth: 24, textAlign: "right" }}>{min}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: t.accent, cursor: disabled ? "not-allowed" : "pointer" }}
      />
      <span style={{ fontSize: 11, color: t.textDim, minWidth: 24 }}>{max}</span>
      <span style={{
        fontSize: 12, color: t.text, fontWeight: 600, minWidth: 40, textAlign: "right",
        fontFamily: "monospace",
      }}>
        {value}
      </span>
      {defaultValue != null && (
        <button
          onClick={() => onChange(defaultValue)}
          disabled={disabled}
          style={{
            fontSize: 10, color: t.textDim, background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 4, padding: "2px 6px", cursor: disabled ? "not-allowed" : "pointer",
            whiteSpace: "nowrap",
          }}
          title={`Reset to default (${defaultValue})`}
        >
          default: {defaultValue}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row layout helpers
// ---------------------------------------------------------------------------
export function Row({ children, gap = 12, stack }: { children: React.ReactNode; gap?: number; stack?: boolean }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap, flexDirection: stack ? "column" : "row" }}>{children}</div>
  );
}

export function Col({ children, flex = 1, minWidth = 200 }: { children: React.ReactNode; flex?: number; minWidth?: number }) {
  return (
    <div style={{ flex, minWidth }}>{children}</div>
  );
}

// ---------------------------------------------------------------------------
// Tab bar (horizontally scrollable for many tabs on mobile)
// ---------------------------------------------------------------------------
export function TabBar({ tabs, active, onChange }: {
  tabs: { key: string; label: string }[];
  active: string;
  onChange: (key: string) => void;
}) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        gap: 4,
        overflowX: "auto",
        WebkitOverflowScrolling: "touch",
        scrollbarWidth: "none",
        paddingBottom: 4,
        paddingRight: 24,
        scrollSnapType: "x mandatory",
      }}
      className="hide-scrollbar"
    >
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            style={{
              padding: "6px 10px",
              fontSize: 12,
              fontWeight: isActive ? 600 : 500,
              border: "1px solid",
              borderColor: isActive ? t.accent : t.surfaceBorder,
              borderRadius: 6,
              background: isActive ? t.accent : "transparent",
              color: isActive ? "#fff" : t.textMuted,
              cursor: "pointer",
              whiteSpace: "nowrap",
              transition: "all 0.15s",
              flexShrink: 0,
              scrollSnapAlign: "start",
              minHeight: 36,
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state / placeholder
// ---------------------------------------------------------------------------
export function EmptyState({ message }: { message: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ padding: 32, textAlign: "center", color: t.textDim, fontSize: 13 }}>
      {message}
    </div>
  );
}

// Tri-state helpers for inherit/enabled/disabled fields
export const triStateOptions = [
  { label: "Inherit (default)", value: "" },
  { label: "Enabled", value: "true" },
  { label: "Disabled", value: "false" },
];

export function triStateValue(v: boolean | undefined | null): string {
  return v === true ? "true" : v === false ? "false" : "";
}

export function triStateParse(v: string): boolean | undefined {
  return v === "true" ? true : v === "false" ? false : undefined;
}
