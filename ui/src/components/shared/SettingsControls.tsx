/**
 * Shared settings control components.
 * Companion to FormControls — keeps FormControls focused on form primitives.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";

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
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          minHeight: 44,
          paddingLeft: 4,
          paddingRight: 4,
          background: "transparent",
          border: "none",
          cursor: "pointer",
        }}
      >
        {open ? (
          <ChevronDown size={14} color={t.textMuted} />
        ) : (
          <ChevronRight size={14} color={t.textMuted} />
        )}
        <span style={{ color: t.textMuted, fontSize: 13, fontWeight: 600 }}>
          {title}
        </span>
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
  const t = useThemeTokens();

  const minHeight = size === "small" ? 36 : 44;
  const fontSize = size === "small" ? 12 : 13;
  const px = size === "small" ? 12 : 20;

  const variantStyles: Record<
    ButtonVariant,
    { bg: string; color: string; border?: string }
  > = {
    primary: { bg: t.accent, color: "#fff" },
    secondary: {
      bg: "transparent",
      color: t.textMuted,
      border: `1px solid ${t.surfaceBorder}`,
    },
    danger: {
      bg: "transparent",
      color: t.danger,
      border: `1px solid ${t.dangerBorder}`,
    },
    ghost: { bg: "transparent", color: t.textMuted },
  };

  const v = variantStyles[variant];

  return (
    <button
      onClick={disabled ? undefined : onPress}
      disabled={disabled}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        paddingLeft: px,
        paddingRight: px,
        minHeight,
        borderRadius: 8,
        fontSize,
        fontWeight: 600,
        cursor: disabled ? "default" : "pointer",
        background: v.bg,
        color: v.color,
        border: v.border ?? "none",
        opacity: disabled ? 0.5 : 1,
        transition: "opacity 0.12s",
        flexShrink: 0,
      }}
    >
      {icon}
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// StatusBadge — consistent badge with variant colors
// ---------------------------------------------------------------------------
type BadgeVariant =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral"
  | "purple"
  | "skipped";

const BADGE_COLORS: Record<
  BadgeVariant,
  (t: ReturnType<typeof useThemeTokens>) => {
    bg: string;
    fg: string;
  }
> = {
  success: (t) => ({ bg: t.successSubtle, fg: t.success }),
  warning: (t) => ({ bg: t.warningSubtle, fg: t.warningMuted }),
  danger: (t) => ({ bg: t.dangerSubtle, fg: t.danger }),
  info: (t) => ({ bg: t.accentMuted, fg: t.accent }),
  neutral: (t) => ({ bg: t.surfaceBorder, fg: t.textMuted }),
  purple: (t) => ({ bg: t.purpleSubtle, fg: t.purple }),
  // Intentionally not-run: dimmed purple to read as "dreaming-related, but
  // didn't execute this cycle". Distinct from neutral (pending/running).
  skipped: (t) => ({ bg: t.surfaceOverlay, fg: t.purpleMuted }),
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
  const t = useThemeTokens();
  const colors = customColors ?? BADGE_COLORS[variant](t);

  return (
    <span
      style={{
        display: "inline-block",
        fontSize: 10,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 4,
        background: colors.bg,
        color: colors.fg,
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// InfoBanner — warning / info / danger / success boxes
// ---------------------------------------------------------------------------
type BannerVariant = "warning" | "info" | "danger" | "success";

export function InfoBanner({
  variant = "info",
  icon,
  children,
}: {
  variant?: BannerVariant;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useThemeTokens();

  const variantStyles: Record<
    BannerVariant,
    { bg: string; border: string; color: string }
  > = {
    warning: {
      bg: t.warningSubtle,
      border: t.warningBorder,
      color: t.warningMuted,
    },
    info: { bg: t.accentSubtle, border: t.accentBorder, color: t.textMuted },
    danger: { bg: t.dangerSubtle, border: t.dangerBorder, color: t.danger },
    success: {
      bg: t.successSubtle,
      border: t.successBorder,
      color: t.success,
    },
  };

  const v = variantStyles[variant];

  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: 8,
        background: v.bg,
        border: `1px solid ${v.border}`,
        fontSize: 11,
        lineHeight: "1.5",
        color: v.color,
        display: "flex", flexDirection: "row",
        gap: 8,
        alignItems: "flex-start",
      }}
    >
      {icon && (
        <span style={{ flexShrink: 0, marginTop: 1 }}>{icon}</span>
      )}
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
}
