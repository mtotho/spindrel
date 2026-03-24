/**
 * Shared form control primitives for settings pages.
 * All use raw HTML elements for web compat (no RN TextInput issues).
 */

import { View, Text, Pressable } from "react-native";

// ---------------------------------------------------------------------------
// Section card
// ---------------------------------------------------------------------------
export function Section({ title, description, action, children }: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <View className="gap-4">
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <View>
          <Text className="text-text text-sm font-semibold">{title}</Text>
          {description && (
            <Text className="text-text-dim text-xs mt-0.5">{description}</Text>
          )}
        </View>
        {action}
      </View>
      {children}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Form row (label + control + description)
// ---------------------------------------------------------------------------
export function FormRow({ label, description, children }: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ color: "#999", fontSize: 12, fontWeight: 500 }}>{label}</label>
      {children}
      {description && (
        <div style={{ color: "#555", fontSize: 11 }}>{description}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Text / number input
// ---------------------------------------------------------------------------
const inputStyle: React.CSSProperties = {
  background: "#111",
  border: "1px solid #333",
  borderRadius: 8,
  padding: "8px 12px",
  color: "#e5e5e5",
  fontSize: 16,
  width: "100%",
  outline: "none",
  transition: "border-color 0.15s",
};

export function TextInput({ value, onChangeText, placeholder, type = "text", style }: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  type?: string;
  style?: React.CSSProperties;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChangeText(e.target.value)}
      placeholder={placeholder}
      style={{ ...inputStyle, ...style }}
      onFocus={(e) => { e.target.style.borderColor = "#3b82f6"; }}
      onBlur={(e) => { e.target.style.borderColor = "#333"; }}
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
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{ ...inputStyle, cursor: "pointer", ...style }}
      onFocus={(e) => { (e.target as HTMLSelectElement).style.borderColor = "#3b82f6"; }}
      onBlur={(e) => { (e.target as HTMLSelectElement).style.borderColor = "#333"; }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Toggle switch
// ---------------------------------------------------------------------------
export function Toggle({ value, onChange, label, description }: {
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <div
      onClick={() => onChange(!value)}
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "4px 0",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {/* Custom toggle track */}
      <div style={{
        width: 36,
        height: 20,
        borderRadius: 10,
        background: value ? "#3b82f6" : "#333",
        position: "relative",
        flexShrink: 0,
        marginTop: 1,
        transition: "background 0.15s",
      }}>
        <div style={{
          width: 16,
          height: 16,
          borderRadius: 8,
          background: "#e5e5e5",
          position: "absolute",
          top: 2,
          left: value ? 18 : 2,
          transition: "left 0.15s",
        }} />
      </div>
      <div>
        <div style={{ fontSize: 13, color: "#e5e5e5" }}>{label}</div>
        {description && (
          <div style={{ fontSize: 11, color: "#666", marginTop: 2 }}>{description}</div>
        )}
      </div>
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
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, opacity: disabled ? 0.4 : 1 }}>
      <span style={{ fontSize: 11, color: "#666", minWidth: 24, textAlign: "right" }}>{min}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: "#3b82f6", cursor: disabled ? "not-allowed" : "pointer" }}
      />
      <span style={{ fontSize: 11, color: "#666", minWidth: 24 }}>{max}</span>
      <span style={{
        fontSize: 12, color: "#e5e5e5", fontWeight: 600, minWidth: 40, textAlign: "right",
        fontFamily: "monospace",
      }}>
        {value}
      </span>
      {defaultValue != null && (
        <button
          onClick={() => onChange(defaultValue)}
          disabled={disabled}
          style={{
            fontSize: 10, color: "#666", background: "#1a1a1a", border: "1px solid #333",
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
export function Row({ children, gap = 12 }: { children: React.ReactNode; gap?: number }) {
  return (
    <div style={{ display: "flex", gap }}>{children}</div>
  );
}

export function Col({ children, flex = 1 }: { children: React.ReactNode; flex?: number }) {
  return (
    <div style={{ flex, minWidth: 0 }}>{children}</div>
  );
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------
export function TabBar({ tabs, active, onChange }: {
  tabs: { key: string; label: string }[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            style={{
              padding: "5px 12px",
              fontSize: 12,
              fontWeight: 500,
              border: "1px solid",
              borderColor: isActive ? "#3b82f6" : "#333",
              borderRadius: 6,
              background: isActive ? "#3b82f6" : "transparent",
              color: isActive ? "#fff" : "#999",
              cursor: "pointer",
              whiteSpace: "nowrap",
              transition: "all 0.15s",
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
  return (
    <div style={{ padding: 32, textAlign: "center", color: "#555", fontSize: 13 }}>
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
