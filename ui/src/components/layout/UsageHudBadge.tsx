import { useState, useRef, useEffect, useCallback, forwardRef } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { DollarSign } from "lucide-react";
import { useUsageForecast } from "../../api/hooks/useUsageForecast";
import { useSpikeStatus } from "../../api/hooks/useSpikeAlerts";
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

export function UsageHudBadge({ collapsed }: { collapsed: boolean }) {
  const { data, isLoading, isError } = useUsageForecast();
  const { data: spikeData } = useSpikeStatus();
  const enabled = useUsageHudStore((s) => s.enabled);
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [popoverPos, setPopoverPos] = useState<{
    left: number;
    bottom: number;
  } | null>(null);

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

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        anchorRef.current &&
        !(anchorRef.current as HTMLElement).contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Hidden by user preference
  if (!enabled) return null;

  // Loading, error, or no data -- always show a dim placeholder
  if (isLoading || isError || !data) {
    const dimColor = t.textDim;
    if (collapsed) {
      return (
        <div>
          <Link to="/admin/usage">
            <button
              className="sidebar-icon-btn"
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                width: 44,
                height: 44,
                opacity: isLoading ? 0.3 : 0.5,
                borderRadius: 8,
                border: "none",
                background: "transparent",
                cursor: "pointer",
                padding: 0,
              }}
              aria-label={
                isLoading ? "Loading usage" : "Usage forecast unavailable"
              }
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: dimColor,
                  fontVariant: "tabular-nums",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {isLoading ? "$\u2026" : "$--"}
              </span>
            </button>
          </Link>
        </div>
      );
    }
    return (
      <div>
        <Link to="/admin/usage">
          <button
            className="sidebar-nav-item"
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              borderRadius: 6,
              paddingLeft: 12,
              paddingRight: 12,
              paddingTop: 8,
              paddingBottom: 8,
              opacity: isLoading ? 0.3 : 0.5,
              border: "none",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            <DollarSign size={14} color={dimColor} />
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: dimColor,
                fontVariant: "tabular-nums",
              }}
            >
              {isLoading ? "$\u2026" : "$-- today"}
            </span>
          </button>
        </Link>
      </div>
    );
  }

  const isSpiking = spikeData?.enabled && spikeData?.spiking;

  const baseColor =
    data.limits.length > 0 ? statusColor(data.limits, t) : t.success;
  // Spike overrides everything to danger
  const color = isSpiking ? t.danger : baseColor;
  const worstLimit =
    data.limits.length > 0
      ? data.limits.reduce((a, b) => (b.percentage > a.percentage ? b : a))
      : null;

  const popover =
    open && popoverPos
      ? createPortal(
          <PopoverContent
            ref={popoverRef}
            data={data}
            t={t}
            color={color}
            worstLimit={worstLimit}
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
        <div ref={anchorRef}>
          <button
            className="sidebar-icon-btn"
            onClick={() => (open ? setOpen(false) : openPopover())}
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              width: 44,
              height: 44,
              position: "relative",
              borderRadius: 8,
              border: "none",
              background: "transparent",
              cursor: "pointer",
              padding: 0,
            }}
            aria-label="Usage forecast"
          >
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color,
                fontVariant: "tabular-nums",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {fmt(data.daily_spend)}
            </span>
            {isSpiking && <SpikeDot t={t} />}
          </button>
        </div>
        {popover}
      </>
    );
  }

  // --- Expanded sidebar: row with progress ---
  return (
    <>
      <div ref={anchorRef}>
        <button
          className="sidebar-nav-item"
          onClick={() => (open ? setOpen(false) : openPopover())}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            borderRadius: 6,
            paddingLeft: 12,
            paddingRight: 12,
            paddingTop: 8,
            paddingBottom: 8,
            position: "relative",
            border: "none",
            background: "transparent",
            cursor: "pointer",
            width: "100%",
            textAlign: "left",
          }}
        >
          <DollarSign size={14} color={color} />
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color,
                  fontVariant: "tabular-nums",
                }}
              >
                {fmt(data.daily_spend)} today
              </span>
              {isSpiking ? (
                <span style={{ fontSize: 10, fontWeight: 700, color: t.danger }}>
                  SPIKE {spikeData?.spike_ratio != null ? `${spikeData.spike_ratio.toFixed(1)}x` : ""}
                </span>
              ) : worstLimit ? (
                <span style={{ fontSize: 10, color: t.textDim }}>
                  {Math.round(worstLimit.percentage)}%
                </span>
              ) : null}
            </div>
            {worstLimit && (
              <div
                style={{
                  height: 3,
                  borderRadius: 2,
                  backgroundColor: t.surfaceBorder,
                }}
              >
                <div
                  style={{
                    height: 3,
                    borderRadius: 2,
                    backgroundColor: color,
                    width: `${Math.min(worstLimit.percentage, 100)}%`,
                  }}
                />
              </div>
            )}
          </div>
        </button>
      </div>
      {popover}
    </>
  );
}

// ---------------------------------------------------------------------------
// Popover (rendered via portal at document.body)
// ---------------------------------------------------------------------------

const PopoverContent = forwardRef<
  HTMLDivElement,
  {
    data: NonNullable<ReturnType<typeof useUsageForecast>["data"]>;
    t: ReturnType<typeof useThemeTokens>;
    color: string;
    worstLimit: LimitForecast | null;
    onClose: () => void;
    pos: { left: number; bottom: number };
  }
>(function PopoverContent({ data, t, color, worstLimit, onClose, pos }, ref) {
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
      <div
        style={{
          display: "flex", flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <span
          style={{
            fontWeight: 700,
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: 0.5,
            color: t.textDim,
          }}
        >
          Usage Forecast
        </span>
      </div>

      {/* Today's spend */}
      <ForecastRow
        label="Today"
        value={fmt(data.daily_spend)}
        valueColor={color}
        t={t}
      />
      <ForecastRow
        label="Projected daily"
        value={fmt(data.projected_daily)}
        valueColor={t.textMuted}
        t={t}
      />
      {data.monthly_spend > 0 && (
        <ForecastRow
          label="This month"
          value={fmt(data.monthly_spend)}
          valueColor={t.textMuted}
          t={t}
        />
      )}

      {/* Limit bar */}
      {worstLimit && (
        <div style={{ margin: "8px 0" }}>
          <div
            style={{
              display: "flex", flexDirection: "row",
              justifyContent: "space-between",
              marginBottom: 3,
            }}
          >
            <span style={{ color: t.textDim, fontSize: 10 }}>
              {worstLimit.scope_type}: {worstLimit.scope_value} (
              {worstLimit.period})
            </span>
            <span style={{ color: t.textDim, fontSize: 10 }}>
              {fmt(worstLimit.current_spend)} / {fmt(worstLimit.limit_usd)}
            </span>
          </div>
          <div
            style={{
              height: 4,
              borderRadius: 2,
              backgroundColor: t.surfaceBorder,
            }}
          >
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
          <div
            style={{
              display: "flex", flexDirection: "row",
              justifyContent: "space-between",
              marginTop: 2,
            }}
          >
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
      <div
        style={{
          borderTop: `1px solid ${t.surfaceBorder}`,
          margin: "8px 0",
        }}
      />

      {/* Components breakdown */}
      {data.components.map((c: ForecastComponent) => (
        <div
          key={c.source}
          style={{
            display: "flex", flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "2px 0",
          }}
        >
          <span style={{ color: t.textMuted, fontSize: 11 }}>
            {c.label}
            {c.count != null && (
              <span style={{ color: t.textDim, fontSize: 10 }}>
                {" "}
                ({c.count})
              </span>
            )}
          </span>
          <span
            style={{ fontSize: 11, color: t.text, fontVariant: "tabular-nums" }}
          >
            {fmt(c.daily_cost)}/d
          </span>
        </div>
      ))}

      {/* Spike alert indicator */}
      <SpikeIndicator t={t} />

      {/* Footer link */}
      <div
        style={{
          borderTop: `1px solid ${t.surfaceBorder}`,
          marginTop: 8,
          paddingTop: 8,
        }}
      >
        <Link to="/admin/usage">
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontSize: 11,
              color: t.accent,
            }}
          >
            View details →
          </button>
        </Link>
      </div>
    </div>
  );
});

function SpikeIndicator({ t }: { t: ReturnType<typeof useThemeTokens> }) {
  const { data } = useSpikeStatus();
  if (!data) return null;

  const dotColor = !data.enabled ? t.textDim : data.spiking ? t.danger : t.success;
  const label = !data.enabled
    ? "Spike Alert: Off"
    : data.spiking
      ? `Spike Alert: ACTIVE (${data.spike_ratio?.toFixed(1) ?? "?"}x)`
      : `Spike Alert: OK${data.spike_ratio != null ? ` (${data.spike_ratio.toFixed(1)}x)` : ""}`;

  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 6,
        padding: "4px 0",
        borderTop: `1px solid ${t.surfaceBorder}`,
        marginTop: 4,
        paddingTop: 6,
      }}
    >
      <div
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          backgroundColor: dotColor,
          flexShrink: 0,
          ...(data.spiking ? { boxShadow: `0 0 4px ${t.danger}` } : {}),
        }}
      />
      <span style={{ fontSize: 10, color: data.spiking ? t.danger : t.textDim }}>
        {label}
      </span>
    </div>
  );
}

function SpikeDot({ t }: { t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div
      style={{
        position: "absolute",
        top: 6,
        right: 6,
        width: 7,
        height: 7,
        borderRadius: 4,
        backgroundColor: t.danger,
        boxShadow: `0 0 4px ${t.danger}`,
        animation: "spike-pulse 1.5s ease-in-out infinite",
      }}
    />
  );
}

function ForecastRow({
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
    <div
      style={{
        display: "flex", flexDirection: "row",
        justifyContent: "space-between",
        padding: "2px 0",
      }}
    >
      <span style={{ color: t.textDim, fontSize: 11 }}>{label}</span>
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: valueColor,
          fontVariant: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
  );
}
