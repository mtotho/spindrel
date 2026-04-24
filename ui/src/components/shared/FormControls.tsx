/**
 * Shared form control primitives for settings pages.
 * All token-driven via Tailwind. `useThemeTokens()` was removed in the
 * 2026-04-23 SKILL pass — if you need a new color, add a token in
 * `ui/global.css` + `ui/tailwind.config.cjs` first.
 */

import { SelectDropdown } from "./SelectDropdown";

const INPUT_CLASS =
  "w-full min-h-[40px] px-3 py-2 text-sm bg-input border border-input-border rounded-md " +
  "text-text placeholder:text-text-dim " +
  "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/40 " +
  "transition-colors";

// ---------------------------------------------------------------------------
// Section — canonical content-surface block.
//
// Renders as: uppercase eyebrow label + bold title + muted description +
// children. Gets its outer breathing room from the parent scroll container's
// `gap-*`; do NOT add `mt-*` to individual sections. Per SKILL §2.2 / §6,
// sections are separated by SPACING — not borders.
// ---------------------------------------------------------------------------
export function Section({ title, description, action, children, noDivider = false }: {
  title: React.ReactNode;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  noDivider?: boolean;
}) {
  // `noDivider` is legacy API kept for compatibility; it no longer gates a
  // visual divider (there is no divider) but callers still pass it to skip
  // the small `pt-0.5` used to optically align the first section.
  const paddingTopClass = noDivider ? "pt-0" : "pt-0.5";
  return (
    <div className={`flex flex-col gap-3 ${paddingTopClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] font-semibold text-text tracking-[-0.01em]">{title}</h3>
          {description && (
            <p className="mt-1 max-w-[65ch] text-[12px] leading-relaxed text-text-dim">
              {description}
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
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
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[12px] font-medium leading-tight text-text-muted">{label}</label>
      {children}
      {description && (
        <div className="text-[12px] leading-snug text-text-dim">{description}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Text / number input
// ---------------------------------------------------------------------------
export function TextInput({ value, onChangeText, placeholder, type = "text", style, className, disabled }: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  type?: string;
  style?: React.CSSProperties;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type={type}
      value={value}
      disabled={disabled}
      onChange={(e) => onChangeText(e.target.value)}
      placeholder={placeholder}
      style={style}
      className={`${INPUT_CLASS} ${className ?? ""}`}
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
    <div className="relative w-full" style={style ? { width: style.width, minWidth: style.minWidth, maxWidth: style.maxWidth, flex: style.flex } : undefined}>
      <SelectDropdown
        value={value}
        onChange={(next) => onChange(next)}
        options={options.map((option) => ({ ...option, searchText: `${option.label} ${option.value}` }))}
        searchable={options.length > 8}
        searchPlaceholder="Filter options..."
        popoverWidth="content"
      />
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
  return (
    <div
      role="switch"
      aria-checked={value}
      tabIndex={0}
      onClick={() => onChange(!value)}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onChange(!value); } }}
      className="flex items-start gap-2.5 py-1.5 cursor-pointer select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 rounded-md"
    >
      <div
        className={`relative mt-0.5 h-5 w-[34px] shrink-0 rounded-full transition-colors ${value ? "bg-accent" : "bg-surface-border"}`}
      >
        <div
          className={`absolute top-[3px] h-3.5 w-3.5 rounded-full bg-text transition-[left] ${value ? "left-[17px]" : "left-[3px]"}`}
        />
      </div>
      {(label || description) && (
        <div className="min-w-0">
          {label && <div className="text-[13px] leading-snug text-text">{label}</div>}
          {description && (
            <div className="mt-0.5 text-[11px] leading-snug text-text-dim">{description}</div>
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
  return (
    <div className={`flex items-center gap-2.5 ${disabled ? "opacity-40" : ""}`}>
      <span className="min-w-[24px] text-right text-[11px] text-text-dim">{min}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className={`flex-1 accent-accent ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}
      />
      <span className="min-w-[24px] text-[11px] text-text-dim">{max}</span>
      <span className="min-w-[40px] text-right font-mono text-[12px] font-semibold text-text">
        {value}
      </span>
      {defaultValue != null && (
        <button
          type="button"
          onClick={() => onChange(defaultValue)}
          disabled={disabled}
          className="whitespace-nowrap rounded border border-surface-border bg-surface-raised px-1.5 py-0.5 text-[10px] text-text-dim hover:bg-surface-overlay/60 disabled:cursor-not-allowed transition-colors"
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
    <div style={{ gap }} className={`flex flex-wrap ${stack ? "flex-col" : "flex-row"}`}>{children}</div>
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
  return (
    <div
      className="flex flex-row gap-1 overflow-x-auto pb-1 pr-6 hide-scrollbar"
      style={{ WebkitOverflowScrolling: "touch", scrollSnapType: "x mandatory" }}
    >
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            type="button"
            onClick={() => onChange(tab.key)}
            className={
              `shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-[12px] transition-colors min-h-[36px] ` +
              (isActive
                ? "bg-accent/[0.08] text-accent font-semibold"
                : "bg-transparent text-text-muted font-medium hover:bg-surface-overlay/60 hover:text-text")
            }
            style={{ scrollSnapAlign: "start" }}
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
    <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-4 py-8 text-center text-[13px] text-text-dim">
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
