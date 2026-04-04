import { View, Text, ScrollView } from "react-native";
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
      <View style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: compact ? 12 : 16,
        paddingVertical: 4,
        gap: 8,
        borderBottomWidth: 1,
        borderBottomColor: t.surfaceBorder,
        backgroundColor: t.surfaceRaised,
      }}>
        {[80, 60, 50].map((w, i) => (
          <View key={i} style={{
            width: w,
            height: 18,
            borderRadius: 9,
            backgroundColor: t.surfaceOverlay,
          }} />
        ))}
      </View>
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
        <Text style={{ fontSize: 10, color: t.textDim, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 }}>
          {hud.widget.label}
        </Text>
      )}
      <View style={{ width: 1, height: 12, backgroundColor: t.surfaceBorder, marginHorizontal: 2 }} />
      {data.items.map((item, i) => (
        <HudItemRenderer key={i} item={item} hudQueryKey={queryKey} />
      ))}
      {agoText && (
        <>
          <View style={{ flex: 1 }} />
          <Text style={{ fontSize: 9, color: t.textDim, opacity: 0.6, fontVariant: ["tabular-nums"] }}>
            {agoText}
          </Text>
        </>
      )}
    </>
  );

  if (compact) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={{
          flexShrink: 0,
          maxHeight: 28,
          borderBottomWidth: 1,
          borderBottomColor: t.surfaceBorder,
          backgroundColor: t.surfaceRaised,
        }}
        contentContainerStyle={{
          paddingHorizontal: 12,
          paddingVertical: 4,
          gap: 6,
          alignItems: "center",
          flexDirection: "row",
        }}
      >
        {items}
      </ScrollView>
    );
  }

  return (
    <View style={{
      flexDirection: "row",
      alignItems: "center",
      paddingHorizontal: 16,
      paddingVertical: 4,
      gap: 6,
      flexWrap: "wrap",
      borderBottomWidth: 1,
      borderBottomColor: t.surfaceBorder,
      backgroundColor: t.surfaceRaised,
    }}>
      {items}
    </View>
  );
}
