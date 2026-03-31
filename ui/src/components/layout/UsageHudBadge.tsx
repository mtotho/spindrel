import { useState, useRef, useEffect, useCallback } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { createPortal } from "react-dom";
import { Link } from "expo-router";
import { DollarSign, Eye, EyeOff, Gauge } from "lucide-react";
import { useUsageForecast } from "../../api/hooks/useUsageForecast";
import { useUsageHudStore } from "../../stores/usageHud";
import { useThemeTokens } from "../../theme/tokens";
import type { LimitForecast, ForecastComponent } from "../../api/hooks/useUsageForecast";

function fmt(n: number): string {
  if (n >= 100) return `$${Math.round(n)}`;
  if (n >= 10) return `$${n.toFixed(1)}`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(2)}`;
  return "$0.00";
}

function worstLimitPct(
  limits: LimitForecast[],
): { actual: number; projected: number } {
  let actual = 0;
  let projected = 0;
  for (const l of limits) {
    if (l.percentage > actual) actual = l.percentage;
    if (l.projected_percentage > projected) projected = l.projected_percentage;
  }
  return { actual, projected };
}

function statusColor(
  limits: LimitForecast[],
  t: ReturnType<typeof useThemeTokens>,
): string {
  const { actual, projected } = worstLimitPct(limits);
  if (actual > 90 || projected > 100) return t.danger;
  if (actual > 70 || projected > 90) return t.warning;
  return t.success;
}

const VISIBILITY_LABELS = {
  always: "Always visible",
  threshold: "Show at 60%+",
  never: "Hidden",
} as const;

const VISIBILITY_ICONS = {
  always: Eye,
  threshold: Gauge,
  never: EyeOff,
} as const;

export function UsageHudBadge({ collapsed }: { collapsed: boolean }) {
  const { data, isLoading } = useUsageForecast();
  const visibility = useUsageHudStore((s) => s.visibility);
  const cycleVisibility = useUsageHudStore((s) => s.cycleVisibility);
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<any>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [popoverPos, setPopoverPos] = useState<{ left: number; bottom: number } | null>(null);

  // This component uses raw HTML elements for the popover — only render on web.
  if (Platform.OS !== "web") return null;

  // Compute popover position when opening
  const openPopover = useCallback(() => {
    if (anchorRef.current) {
      const el = anchorRef.current as HTMLElement;
      const rect = el.getBoundingClientRect();
      setPopoverPos({
        left: rect.left,
        bottom: window.innerHeight - rect.top + 4,
      });
    }
    setOpen(true);
  }, []);

  // Close popover on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current && !popoverRef.current.contains(target) &&
        anchorRef.current && !(anchorRef.current as HTMLElement).contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (isLoading || !data) return null;

  // Threshold mode: hide when below thresholds
  if (visibility === "never") return null;
  if (visibility === "threshold") {
    const { actual, projected } = worstLimitPct(data.limits);
    if (actual < 60 && projected < 80) return null;
  }

  const color = data.limits.length > 0 ? statusColor(data.limits, t) : t.success;
  const worstLimit = data.limits.length > 0
    ? data.limits.reduce((a, b) => (b.percentage > a.percentage ? b : a))
    : null;

  const popover = open && popoverPos
    ? createPortal(
        <PopoverContent
          ref={popoverRef}
          data={data}
          t={t}
          color={color}
          worstLimit={worstLimit}
          cycleVisibility={cycleVisibility}
          visibility={visibility}
          onClose={() => setOpen(false)}
          pos={popoverPos}
        />,
        document.body,
      )
    : null;

  // --- Collapsed rail: icon-sized badge ---
  if (collapsed) {
    return (
      <>
        <View ref={anchorRef}>
          <Pressable
            onPress={() => open ? setOpen(false) : openPopover()}
            className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
            accessibilityLabel="Usage forecast"
          >
            <Text
              style={{ fontSize: 10, fontWeight: "700", color, fontVariant: ["tabular-nums"] as any }}
              numberOfLines={1}
            >
              {fmt(data.daily_spend)}
            </Text>
          </Pressable>
        </View>
        {popover}
      </>
    );
  }

  // --- Expanded sidebar: row with progress ---
  return (
    <>
      <View ref={anchorRef}>
        <Pressable
          onPress={() => open ? setOpen(false) : openPopover()}
          className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay"
        >
          <DollarSign size={14} color={color} />
          <View style={{ flex: 1, gap: 2 }}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text style={{ fontSize: 12, fontWeight: "600", color, fontVariant: ["tabular-nums"] as any }}>
                {fmt(data.daily_spend)} today
              </Text>
              {worstLimit && (
                <Text style={{ fontSize: 10, color: t.textDim }}>
                  {Math.round(worstLimit.percentage)}%
                </Text>
              )}
            </View>
            {worstLimit && (
              <View style={{ height: 3, borderRadius: 2, backgroundColor: t.surfaceBorder }}>
                <View
                  style={{
                    height: 3,
                    borderRadius: 2,
                    backgroundColor: color,
                    width: `${Math.min(worstLimit.percentage, 100)}%`,
                  }}
                />
              </View>
            )}
          </View>
        </Pressable>
      </View>
      {popover}
    </>
  );
}

// ---------------------------------------------------------------------------
// Popover (rendered via portal at document.body)
// ---------------------------------------------------------------------------

import { forwardRef } from "react";

const PopoverContent = forwardRef<
  HTMLDivElement,
  {
    data: NonNullable<ReturnType<typeof useUsageForecast>["data"]>;
    t: ReturnType<typeof useThemeTokens>;
    color: string;
    worstLimit: LimitForecast | null;
    cycleVisibility: () => void;
    visibility: "always" | "threshold" | "never";
    onClose: () => void;
    pos: { left: number; bottom: number };
  }
>(function PopoverContent({ data, t, color, worstLimit, cycleVisibility, visibility, onClose, pos }, ref) {
  const VisIcon = VISIBILITY_ICONS[visibility];

  return (
    <div
      ref={ref}
      style={{
        position: "fixed",
        left: pos.left,
        bottom: pos.bottom,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        padding: 14,
        minWidth: 260,
        maxWidth: 300,
        zIndex: 10000,
        fontSize: 12,
        color: t.text,
        boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontWeight: 700, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: t.textDim }}>
          Usage Forecast
        </span>
        <button
          onClick={(e) => { e.stopPropagation(); cycleVisibility(); }}
          title={VISIBILITY_LABELS[visibility]}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 2,
            display: "flex",
            alignItems: "center",
            gap: 4,
            color: t.textDim,
            fontSize: 10,
          }}
        >
          <VisIcon size={12} color={t.textDim} />
          <span>{VISIBILITY_LABELS[visibility]}</span>
        </button>
      </div>

      {/* Today's spend */}
      <Row label="Today" value={fmt(data.daily_spend)} valueColor={color} t={t} />
      <Row label="Projected daily" value={fmt(data.projected_daily)} valueColor={t.textMuted} t={t} />
      {data.monthly_spend > 0 && (
        <Row label="This month" value={fmt(data.monthly_spend)} valueColor={t.textMuted} t={t} />
      )}

      {/* Limit bar */}
      {worstLimit && (
        <div style={{ margin: "8px 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
            <span style={{ color: t.textDim, fontSize: 10 }}>
              {worstLimit.scope_type}: {worstLimit.scope_value} ({worstLimit.period})
            </span>
            <span style={{ color: t.textDim, fontSize: 10 }}>
              {fmt(worstLimit.current_spend)} / {fmt(worstLimit.limit_usd)}
            </span>
          </div>
          <div style={{ height: 4, borderRadius: 2, backgroundColor: t.surfaceBorder }}>
            <div
              style={{
                height: 4,
                borderRadius: 2,
                backgroundColor: color,
                width: `${Math.min(worstLimit.percentage, 100)}%`,
                transition: "width 0.3s",
              }}
            />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
            <span style={{ color: t.textDim, fontSize: 10 }}>
              {Math.round(worstLimit.percentage)}% used
            </span>
            <span style={{ color: t.textDim, fontSize: 10 }}>
              ~{Math.round(worstLimit.projected_percentage)}% projected
            </span>
          </div>
        </div>
      )}

      {/* Separator */}
      <div style={{ borderTop: `1px solid ${t.surfaceBorder}`, margin: "8px 0" }} />

      {/* Components breakdown */}
      {data.components.map((c: ForecastComponent) => (
        <div key={c.source} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "2px 0" }}>
          <span style={{ color: t.textMuted, fontSize: 11 }}>
            {c.label}
            {c.count != null && (
              <span style={{ color: t.textDim, fontSize: 10 }}> ({c.count})</span>
            )}
          </span>
          <span style={{ fontSize: 11, color: t.text, fontVariant: "tabular-nums" }}>
            {fmt(c.daily_cost)}/d
          </span>
        </div>
      ))}

      {/* Footer link */}
      <div style={{ borderTop: `1px solid ${t.surfaceBorder}`, marginTop: 8, paddingTop: 8 }}>
        <Link href={"/admin/usage" as any} asChild>
          <Pressable onPress={onClose}>
            <Text style={{ fontSize: 11, color: t.accent }}>
              View details →
            </Text>
          </Pressable>
        </Link>
      </div>
    </div>
  );
});

function Row({
  label,
  value,
  valueColor,
  t,
}: {
  label: string;
  value: string;
  valueColor: string;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0" }}>
      <span style={{ color: t.textDim, fontSize: 11 }}>{label}</span>
      <span style={{ fontSize: 11, fontWeight: 600, color: valueColor, fontVariant: "tabular-nums" }}>
        {value}
      </span>
    </div>
  );
}
