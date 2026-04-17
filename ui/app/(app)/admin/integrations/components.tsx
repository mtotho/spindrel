import { useThemeTokens } from "@/src/theme/tokens";
import type { IntegrationEnvVar } from "@/src/api/hooks/useIntegrations";
import { Check, X } from "lucide-react";

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export const STATUS_COLORS: Record<string, { dot: string; label: string; bg: string }> = {
  enabled: { dot: "#22c55e", label: "Enabled", bg: "rgba(34,197,94,0.12)" },
  needs_setup: { dot: "#eab308", label: "Needs Setup", bg: "rgba(234,179,8,0.12)" },
  available: { dot: "#6b7280", label: "Available", bg: "rgba(107,114,128,0.12)" },
};

export function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.available;
  return (
    <span
      style={{
        display: "inline-flex", flexDirection: "row",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.dot,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: 4,
          background: c.dot,
          flexShrink: 0,
        }}
      />
      {c.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Capability badge
// ---------------------------------------------------------------------------

export function CapBadge({ label, active }: { label: string; active: boolean }) {
  const t = useThemeTokens();
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: "1px 6px",
        borderRadius: 3,
        background: active ? t.accentSubtle : "transparent",
        color: active ? t.accent : t.surfaceBorder,
        border: `1px solid ${active ? t.accentSubtle : t.surfaceBorder}`,
      }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Env var pill
// ---------------------------------------------------------------------------

export function EnvVarPill({ v }: { v: IntegrationEnvVar }) {
  const t = useThemeTokens();
  const isGreen = v.is_set;
  const isRed = !v.is_set && v.required;
  const bg = isGreen
    ? "rgba(34,197,94,0.1)"
    : isRed
      ? "rgba(239,68,68,0.1)"
      : "rgba(107,114,128,0.08)";
  const fg = isGreen ? "#22c55e" : isRed ? "#ef4444" : "#6b7280";

  return (
    <span
      title={v.description + (v.default ? ` (default: ${v.default})` : "")}
      style={{
        display: "inline-flex", flexDirection: "row",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 500,
        background: bg,
        color: fg,
        fontFamily: "monospace",
      }}
    >
      {isGreen ? <Check size={10} /> : isRed ? <X size={10} /> : null}
      {v.key}
      {v.default && !isRed && (
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "sans-serif" }}>
          {v.default}
        </span>
      )}
      {!v.required && !v.default && (
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "sans-serif" }}>
          opt
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatUptime(seconds: number | null): string {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
