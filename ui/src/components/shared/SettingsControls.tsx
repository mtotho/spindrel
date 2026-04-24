/**
 * Shared settings control components.
 * Companion to FormControls — keeps FormControls focused on form primitives.
 *
 * All token-driven via Tailwind. `useThemeTokens()` was removed in the
 * 2026-04-23 SKILL pass — if you need a new color, add a token in
 * `ui/global.css` + `ui/tailwind.config.cjs` first.
 */

import { useState } from "react";
import { AlertCircle, Check, ChevronDown, ChevronRight, Loader2, PencilLine } from "lucide-react";

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

// Primary action buttons use the signature Spindrel gradient
// (`linear-gradient(135deg, accent, purple)` — see `MessageInput.tsx:887`).
// This is the same treatment as the composer send arrow: it carries brand
// personality on destructive/confirm CTAs without needing bright color.
const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-br from-accent to-purple text-white border-transparent " +
    "shadow-[0_6px_18px_-6px_rgba(59,130,246,0.45)] hover:brightness-110 active:brightness-95",
  secondary:
    "bg-surface-raised text-text border border-surface-border hover:bg-surface-overlay/60",
  danger:
    "bg-danger/10 text-danger border border-danger/40 hover:bg-danger/15",
  ghost:
    "bg-transparent text-text-muted border border-surface-border hover:bg-surface-overlay/60",
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

// ---------------------------------------------------------------------------
// InfoBanner — warning / info / danger / success boxes
//
// Per SKILL §4 Banners: single left-border accent in semantic token + muted
// body text; no outline border, no bg gradient, no shadow.
// ---------------------------------------------------------------------------
type BannerVariant = "warning" | "info" | "danger" | "success";

const BANNER_CLASSES: Record<BannerVariant, string> = {
  warning: "border-warning/60 bg-warning/10 text-warning-muted",
  info: "border-accent/50 bg-accent/[0.06] text-text-muted",
  danger: "border-danger/60 bg-danger/10 text-danger",
  success: "border-success/60 bg-success/10 text-success",
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
        `flex items-start gap-2 rounded-md border-l-2 px-3.5 py-2.5 text-[12px] leading-relaxed ` +
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
