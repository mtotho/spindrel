import { View, Text, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { resolveHudIcon, variantColor, variantBg } from "./hudIcons";
import type { HudItem, HudOnClick } from "@/src/types/api";
import { useState } from "react";

function useOnClickHandler(onClick: HudOnClick | undefined, hudQueryKey?: string[]) {
  const router = useRouter();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!onClick) return { handler: undefined, busy, error };

  const handler = async () => {
    setError(null);
    if (onClick.type === "link" && onClick.href) {
      router.push(onClick.href as any);
    } else if (onClick.type === "action" && onClick.endpoint) {
      if (onClick.confirm && !window.confirm(onClick.confirm)) return;
      setBusy(true);
      try {
        await apiFetch(onClick.endpoint, {
          method: onClick.method || "POST",
          ...(onClick.body ? { body: JSON.stringify(onClick.body) } : {}),
        });
        // Immediately re-fetch HUD data so the UI reflects the action
        if (hudQueryKey) {
          await qc.invalidateQueries({ queryKey: hudQueryKey });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Action failed";
        setError(msg);
        console.error("HUD action failed:", err);
      } finally {
        setBusy(false);
      }
    } else if (onClick.type === "refresh") {
      if (hudQueryKey) {
        qc.invalidateQueries({ queryKey: hudQueryKey });
      }
    }
  };

  return { handler, busy, error };
}

export function HudBadge({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  const bg = variantBg(item.variant, t);
  const Icon = resolveHudIcon(item.icon);
  const { handler } = useOnClickHandler(item.on_click, hudQueryKey);

  const content = (
    <View style={{
      flexDirection: "row",
      alignItems: "center",
      gap: 4,
      paddingHorizontal: 8,
      paddingVertical: 2,
      borderRadius: 10,
      backgroundColor: bg,
    }}>
      <Icon size={11} color={color} />
      {item.label && (
        <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "500" }}>
          {item.label}
        </Text>
      )}
      {item.value && (
        <Text style={{ fontSize: 11, color, fontWeight: "600", fontVariant: ["tabular-nums"] }}>
          {item.value}
        </Text>
      )}
    </View>
  );

  if (handler) {
    return <Pressable onPress={handler}>{content}</Pressable>;
  }
  return content;
}

export function HudAction({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  const bg = variantBg(item.variant, t);
  const Icon = resolveHudIcon(item.icon);
  const { handler, busy, error } = useOnClickHandler(item.on_click, hudQueryKey);

  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <Pressable
        onPress={handler}
        disabled={busy}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 4,
          paddingHorizontal: 8,
          paddingVertical: 2,
          borderRadius: 10,
          backgroundColor: bg,
          borderWidth: 1,
          borderColor: color + "33",
          opacity: busy ? 0.5 : 1,
        }}
      >
        <Icon size={11} color={color} />
        <Text style={{ fontSize: 11, color, fontWeight: "600" }}>
          {busy ? "Working..." : item.label}
        </Text>
      </Pressable>
      {error && (
        <Text style={{ fontSize: 10, color: t.danger }}>Failed</Text>
      )}
    </View>
  );
}

export function HudDivider() {
  const t = useThemeTokens();
  return (
    <View style={{
      width: 1,
      height: 14,
      backgroundColor: t.surfaceBorder,
      marginHorizontal: 2,
    }} />
  );
}

export function HudText({ item }: { item: HudItem }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  return (
    <Text style={{ fontSize: 11, color }}>
      {item.value}
    </Text>
  );
}

export function HudProgress({ item }: { item: HudItem }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  const current = Number(item.value) || 0;
  const max = Number(item.max) || 100;
  const pct = Math.min(100, Math.max(0, (current / max) * 100));

  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      {item.label && (
        <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "500" }}>
          {item.label}
        </Text>
      )}
      <View style={{
        width: 60,
        height: 4,
        borderRadius: 2,
        backgroundColor: t.surfaceOverlay,
        overflow: "hidden",
      }}>
        <View style={{
          width: `${pct}%`,
          height: "100%",
          backgroundColor: color,
          borderRadius: 2,
        }} />
      </View>
      <Text style={{ fontSize: 10, color: t.textDim, fontVariant: ["tabular-nums"] }}>
        {current}/{max}
      </Text>
    </View>
  );
}

export function HudItemRenderer({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  switch (item.type) {
    case "badge":
      return <HudBadge item={item} hudQueryKey={hudQueryKey} />;
    case "action":
      return <HudAction item={item} hudQueryKey={hudQueryKey} />;
    case "divider":
      return <HudDivider />;
    case "text":
      return <HudText item={item} />;
    case "progress":
      return <HudProgress item={item} />;
    default:
      return null;
  }
}
