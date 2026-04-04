import { View, Text, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { resolveHudIcon, variantColor, variantBg } from "./hudIcons";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import type { HudItem, HudOnClick } from "@/src/types/api";
import { useState, useCallback } from "react";

function useOnClickHandler(onClick: HudOnClick | undefined, hudQueryKey?: string[]) {
  const router = useRouter();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<string | null>(null);

  const executeAction = useCallback(async () => {
    if (!onClick || onClick.type !== "action" || !onClick.endpoint) return;
    setBusy(true);
    try {
      await apiFetch(onClick.endpoint, {
        method: onClick.method || "POST",
        ...(onClick.body ? { body: JSON.stringify(onClick.body) } : {}),
      });
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
  }, [onClick, hudQueryKey, qc]);

  if (!onClick) return { handler: undefined, busy, error, pendingConfirm, setPendingConfirm, executeAction };

  const handler = async () => {
    setError(null);
    if (onClick.type === "link" && onClick.href) {
      router.push(onClick.href as any);
    } else if (onClick.type === "action" && onClick.endpoint) {
      if (onClick.confirm) {
        setPendingConfirm(onClick.confirm);
        return;
      }
      await executeAction();
    } else if (onClick.type === "refresh") {
      if (hudQueryKey) {
        qc.invalidateQueries({ queryKey: hudQueryKey });
      }
    }
  };

  return { handler, busy, error, pendingConfirm, setPendingConfirm, executeAction };
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
  const { handler, busy, error, pendingConfirm, setPendingConfirm, executeAction } =
    useOnClickHandler(item.on_click, hudQueryKey);

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
      <ConfirmDialog
        open={pendingConfirm !== null}
        title="Confirm Action"
        message={pendingConfirm ?? ""}
        confirmLabel="Continue"
        variant="warning"
        onConfirm={() => {
          setPendingConfirm(null);
          executeAction();
        }}
        onCancel={() => setPendingConfirm(null)}
      />
    </View>
  );
}

export function HudDivider({ vertical }: { vertical?: boolean }) {
  const t = useThemeTokens();
  if (vertical) {
    return (
      <View style={{
        height: 1,
        backgroundColor: t.surfaceBorder,
        marginVertical: 4,
      }} />
    );
  }
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

export function HudGroup({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  const t = useThemeTokens();
  return (
    <View style={{ gap: 4 }}>
      {item.label && (
        <Text style={{ fontSize: 11, fontWeight: "600", color: t.text }} numberOfLines={1}>
          {item.label}
        </Text>
      )}
      {item.items && item.items.length > 0 && (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
          {item.items.map((child, i) => (
            <HudItemRenderer key={i} item={child} hudQueryKey={hudQueryKey} />
          ))}
        </View>
      )}
    </View>
  );
}

export function HudItemRenderer({ item, hudQueryKey, vertical }: { item: HudItem; hudQueryKey?: string[]; vertical?: boolean }) {
  switch (item.type) {
    case "badge":
      return <HudBadge item={item} hudQueryKey={hudQueryKey} />;
    case "action":
      return <HudAction item={item} hudQueryKey={hudQueryKey} />;
    case "divider":
      return <HudDivider vertical={vertical} />;
    case "text":
      return <HudText item={item} />;
    case "progress":
      return <HudProgress item={item} />;
    case "group":
      return <HudGroup item={item} hudQueryKey={hudQueryKey} />;
    default:
      return null;
  }
}
