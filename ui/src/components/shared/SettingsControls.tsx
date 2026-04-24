/**
 * Shared settings control components.
 * Companion to FormControls — keeps FormControls focused on form primitives.
 *
 * All token-driven via Tailwind. `useThemeTokens()` was removed in the
 * 2026-04-23 SKILL pass — if you need a new color, add a token in
 * `ui/global.css` + `ui/tailwind.config.cjs` first.
 */

import { useState } from "react";
import { AlertCircle, Check, ChevronDown, ChevronRight, Loader2, PencilLine, Search, X } from "lucide-react";

// ---------------------------------------------------------------------------
// AdvancedSection — collapsible with chevron + title, 44px touch target
// ---------------------------------------------------------------------------
export function AdvancedSection({
  title = "Advanced Settings",
  defaultOpen = false,
  children,
}: {
  title?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mt-2.5">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 min-h-[44px] px-0.5 bg-transparent text-text-muted hover:text-text transition-colors"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="text-[13px] font-semibold">{title}</span>
      </button>
      {open && children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActionButton — primary / secondary / danger / ghost variants
// ---------------------------------------------------------------------------
type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
type ButtonSize = "default" | "small";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-transparent text-accent border border-transparent hover:bg-accent/[0.08] active:bg-accent/[0.12]",
  secondary:
    "bg-transparent text-text-muted border border-transparent hover:bg-surface-overlay/60 hover:text-text",
  danger:
    "bg-transparent text-danger border border-transparent hover:bg-danger/10",
  ghost:
    "bg-transparent text-text-dim border border-transparent hover:bg-surface-overlay/50 hover:text-text-muted",
};

export function ActionButton({
  label,
  onPress,
  variant = "primary",
  size = "default",
  disabled = false,
  icon,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  icon?: React.ReactNode;
}) {
  const sizeClass =
    size === "small" ? "min-h-[34px] px-2.5 text-[12px]" : "min-h-[40px] px-3.5 text-[13px]";
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onPress}
      disabled={disabled}
      className={
        `inline-flex items-center justify-center gap-1.5 shrink-0 rounded-md font-semibold transition-colors ` +
        `disabled:cursor-default disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ` +
        `${sizeClass} ${VARIANT_CLASSES[variant]}`
      }
    >
      {icon}
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// StatusBadge — consistent badge with variant colors
//
// Per SKILL §4 Badges: `rounded-full` pill with low-opacity semantic tint.
// ---------------------------------------------------------------------------
type BadgeVariant =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral"
  | "purple"
  | "skipped";

const BADGE_CLASSES: Record<BadgeVariant, string> = {
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning-muted",
  danger: "bg-danger/10 text-danger",
  info: "bg-accent/10 text-accent",
  neutral: "bg-surface-overlay text-text-muted",
  purple: "bg-purple/10 text-purple",
  skipped: "bg-surface-overlay text-text-dim",
};

export function StatusBadge({
  label,
  variant = "neutral",
  customColors,
}: {
  label: string;
  variant?: BadgeVariant;
  customColors?: { bg: string; fg: string };
}) {
  if (customColors) {
    return (
      <span
        className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em]"
        style={{ background: customColors.bg, color: customColors.fg }}
      >
        {label}
      </span>
    );
  }
  return (
    <span
      className={
        `inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 ` +
        `text-[10px] font-semibold uppercase tracking-[0.06em] ${BADGE_CLASSES[variant]}`
      }
    >
      {label}
    </span>
  );
}

export function QuietPill({
  label,
  title,
  className = "",
  maxWidthClass = "max-w-[160px]",
}: {
  label: React.ReactNode;
  title?: string;
  className?: string;
  maxWidthClass?: string;
}) {
  return (
    <span
      title={title}
      className={
        `inline-flex shrink-0 items-center rounded-full bg-surface-overlay/35 ` +
        `px-1.5 py-px text-[9px] font-semibold uppercase leading-[14px] tracking-[0.05em] text-text-muted ` +
        `${maxWidthClass} ` +
        className
      }
    >
      <span className="truncate">{label}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// InfoBanner — warning / info / danger / success inline notes
//
// Keep these low-chrome: tonal semantic tint + text only. No semantic left
// border, outline border, gradient, or shadow.
// ---------------------------------------------------------------------------
type BannerVariant = "warning" | "info" | "danger" | "success";

const BANNER_CLASSES: Record<BannerVariant, string> = {
  warning: "bg-warning/10 text-warning-muted",
  info: "bg-accent/[0.06] text-text-muted",
  danger: "bg-danger/10 text-danger",
  success: "bg-success/10 text-success",
};

export function InfoBanner({
  variant = "info",
  icon,
  children,
}: {
  variant?: BannerVariant;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className={
        `flex items-start gap-2 rounded-md px-3.5 py-2.5 text-[12px] leading-relaxed ` +
        BANNER_CLASSES[variant]
      }
    >
      {icon && <span className="mt-px shrink-0">{icon}</span>}
      <div className="flex-1">{children}</div>
    </div>
  );
}

export type SaveStatusTone = "idle" | "dirty" | "pending" | "saved" | "error";

const PILL_CLASSES: Record<
  Exclude<SaveStatusTone, "idle">,
  { icon: React.ReactNode; cls: string }
> = {
  dirty: {
    icon: <PencilLine size={12} />,
    cls: "bg-surface-overlay border-surface-border text-text-muted",
  },
  pending: {
    icon: <Loader2 size={12} className="animate-spin" />,
    cls: "bg-accent/10 border-accent/40 text-accent",
  },
  saved: {
    icon: <Check size={12} />,
    cls: "bg-success/10 border-success/40 text-success",
  },
  error: {
    icon: <AlertCircle size={12} />,
    cls: "bg-danger/10 border-danger/40 text-danger",
  },
};

export function SaveStatusPill({
  tone,
  label,
}: {
  tone: SaveStatusTone;
  label: string;
}) {
  if (tone === "idle") return null;
  const pill = PILL_CLASSES[tone];
  return (
    <div
      className={
        `inline-flex shrink-0 items-center gap-1.5 min-h-[30px] rounded-md border px-2.5 text-[11px] font-semibold ` +
        pill.cls
      }
    >
      <span className="inline-flex items-center">{pill.icon}</span>
      <span>{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Control-surface layout primitives.
// These are intentionally low-chrome: section hierarchy is spacing +
// typography first, tonal rows second, borders only for expanded forms.
// ---------------------------------------------------------------------------
export function SettingsGroupLabel({
  label,
  count,
  icon,
  action,
}: {
  label: string;
  count?: number;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[28px] items-center gap-1.5">
      {icon}
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        {label}
      </span>
      {count != null && (
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold text-text-dim">
          {count}
        </span>
      )}
      {action && <div className="ml-auto shrink-0">{action}</div>}
    </div>
  );
}

export function SettingsSearchBox({
  value,
  onChange,
  onKeyDown,
  placeholder = "Filter...",
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={`flex min-h-[34px] items-center gap-1.5 rounded-md bg-surface-raised/50 px-2.5 text-text-dim transition-colors focus-within:bg-surface-overlay/45 focus-within:ring-2 focus-within:ring-accent/30 ${className}`}>
      <Search size={13} className="shrink-0" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear filter"
          className="inline-flex items-center p-0 text-text-dim transition-colors hover:text-text"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}

export function SettingsSegmentedControl<T extends string>({
  options,
  value,
  onChange,
  className = "",
}: {
  options: Array<{ key?: T; value?: T; label: string; count?: number; icon?: React.ReactNode }>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={`inline-flex rounded-md bg-surface-raised/40 p-1 ${className}`}>
      {options.map((option) => {
        const optionValue = (option.key ?? option.value) as T;
        const active = value === optionValue;
        return (
          <button
            key={optionValue}
            type="button"
            onClick={() => onChange(optionValue)}
            className={
              `inline-flex min-h-[30px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold transition-colors ` +
              `focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 ` +
              (active
                ? "bg-surface-overlay text-text"
                : "text-text-dim hover:bg-surface-overlay/45 hover:text-text-muted")
            }
          >
            {option.icon}
            {option.label}
            {option.count != null && option.count > 0 && (
              <span
                className={
                  `min-w-[18px] rounded-full px-1.5 py-px text-center text-[10px] font-semibold ` +
                  (active ? "bg-accent/10 text-accent" : "bg-surface-overlay text-text-dim")
                }
              >
                {option.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function SettingsControlRow({
  children,
  leading,
  title,
  description,
  meta,
  action,
  active = false,
  disabled = false,
  onClick,
  compact = false,
  className = "",
}: {
  children?: React.ReactNode;
  leading?: React.ReactNode;
  title?: React.ReactNode;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  compact?: boolean;
  className?: string;
}) {
  const classes =
    `relative w-full rounded-md px-3 ${compact ? "py-2" : "py-2.5"} text-left transition-colors ` +
    (active
      ? "bg-accent/[0.06] before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent "
      : "bg-surface-raised/40 ") +
    (disabled ? "opacity-50 " : onClick ? "cursor-pointer hover:bg-surface-overlay/45 " : "") +
    `focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 ${className}`;

  const content = children ?? (
    <div className="flex min-w-0 items-center gap-2.5">
      {leading && <div className="shrink-0 text-text-dim">{leading}</div>}
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          {title && <div className="min-w-0 truncate text-[12px] font-semibold text-text">{title}</div>}
          {meta && <div className="shrink-0 text-[10px] text-text-dim">{meta}</div>}
        </div>
        {description && <div className="mt-0.5 text-[11px] leading-snug text-text-dim">{description}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );

  if (onClick) {
    return (
      <button type="button" onClick={disabled ? undefined : onClick} disabled={disabled} className={classes}>
        {content}
      </button>
    );
  }

  return <div className={classes}>{content}</div>;
}

export function SettingsStatGrid({
  items,
}: {
  items: Array<{ label: string; value: React.ReactNode; tone?: "default" | "success" | "warning" | "danger" | "accent" }>;
}) {
  const toneClass = {
    default: "text-text",
    success: "text-success",
    warning: "text-warning-muted",
    danger: "text-danger",
    accent: "text-accent",
  } as const;
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="rounded-md bg-surface-raised/40 px-3 py-2.5">
          <div className={`font-mono text-[14px] font-semibold ${toneClass[item.tone ?? "default"]}`}>
            {item.value}
          </div>
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim/70">
            {item.label}
          </div>
        </div>
      ))}
    </div>
  );
}
