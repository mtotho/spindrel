import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
export const TIME_PRESETS: { label: string; value: string }[] = [
  { label: "1h", value: "1h" },
  { label: "12h", value: "12h" },
  { label: "24h", value: "24h" },
  { label: "48h", value: "48h" },
  { label: "7d", value: "7d" },
  { label: "30d", value: "30d" },
];

export const TABS = ["Overview", "Forecast", "Logs", "Charts", "Limits", "Alerts"] as const;
export type Tab = (typeof TABS)[number];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
export function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function fmtBucketLabel(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

// ---------------------------------------------------------------------------
// Shared filter bar styles
// ---------------------------------------------------------------------------
export function useSelectStyle(): React.CSSProperties {
  const t = useThemeTokens();
  return {
    background: t.surfaceRaised,
    color: t.textMuted,
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 6,
    padding: "5px 10px",
    fontSize: 12,
    outline: "none",
  };
}
