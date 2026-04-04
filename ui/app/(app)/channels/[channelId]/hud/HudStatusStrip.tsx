import { useThemeTokens } from "@/src/theme/tokens";
import { useHudData, type ActiveHud } from "@/src/api/hooks/useChatHud";
import { HudItemRenderer } from "./HudItemRenderer";
import { resolveHudIcon } from "./hudIcons";

/**
 * Horizontal pill row below the ActiveBadgeBar.
 * Polls a HUD endpoint and renders badges/actions inline.
 */
export function HudStatusStrip({ hud, compact }: { hud: ActiveHud; compact?: boolean }) {
  const t = useThemeTokens();
  const { data, isLoading, dataUpdatedAt } = useHudData(
    hud.integrationId,
    hud.widget.endpoint,
    hud.widget.poll_interval ?? 60,
  );

  // Loading skeleton on first fetch
  if (isLoading && !data) {
    return (
      <div style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        padding: compact ? "4px 12px" : "4px 16px",
        gap: 8,
        borderBottom: `1px solid ${t.surfaceBorder}`,
        backgroundColor: t.surfaceRaised,
      }}>
        {[80, 60, 50].map((w, i) => (
          <div key={i} style={{
            width: w,
            height: 18,
            borderRadius: 9,
            backgroundColor: t.surfaceOverlay,
          }} />
        ))}
      </div>
    );
  }

  if (!data?.visible || !data.items.length) return null;

  const LabelIcon = resolveHudIcon(hud.widget.icon);
  const queryKey = ["hud-data", hud.integrationId, hud.widget.endpoint ?? ""];

  // Freshness: how many seconds since last successful fetch
  const agoSec = dataUpdatedAt ? Math.floor((Date.now() - dataUpdatedAt) / 1000) : null;
  const agoText = agoSec != null && agoSec > 5
    ? agoSec < 60 ? `${agoSec}s ago` : `${Math.floor(agoSec / 60)}m ago`
    : null;

  const items = (
    <>
      <LabelIcon size={11} color={t.textDim} />
      {hud.widget.label && (
        <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>
          {hud.widget.label}
        </span>
      )}
      <div style={{ width: 1, height: 12, backgroundColor: t.surfaceBorder, margin: "0 2px" }} />
      {data.items.map((item, i) => (
        <HudItemRenderer key={i} item={item} hudQueryKey={queryKey} />
      ))}
      {agoText && (
        <>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 9, color: t.textDim, opacity: 0.6, fontVariantNumeric: "tabular-nums" }}>
            {agoText}
          </span>
        </>
      )}
    </>
  );

  if (compact) {
    return (
      <div
        className="hide-scrollbar"
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          overflowX: "auto",
          flexShrink: 0,
          maxHeight: 28,
          padding: "4px 12px",
          gap: 6,
          borderBottom: `1px solid ${t.surfaceBorder}`,
          backgroundColor: t.surfaceRaised,
        }}
      >
        {items}
      </div>
    );
  }

  return (
    <div style={{
      display: "flex",
      flexDirection: "row",
      alignItems: "center",
      padding: "4px 16px",
      gap: 6,
      flexWrap: "wrap",
      borderBottom: `1px solid ${t.surfaceBorder}`,
      backgroundColor: t.surfaceRaised,
    }}>
      {items}
    </div>
  );
}
