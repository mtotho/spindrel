import { useState } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useHudData, type ActiveHud } from "@/src/api/hooks/useChatHud";
import { HudItemRenderer } from "./HudItemRenderer";
import { resolveHudIcon } from "./hudIcons";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";

/**
 * Collapsible panel on the right side of chat.
 * Supports either data-driven cards (endpoint) or iframe (iframe_path).
 */
export function HudSidePanel({ hud }: { hud: ActiveHud }) {
  const t = useThemeTokens();
  const [collapsed, setCollapsed] = useState(hud.widget.collapsed_by_default !== false);
  const width = hud.widget.width ?? 320;

  const isIframe = !!hud.widget.iframe_path;
  const { data } = useHudData(
    hud.integrationId,
    isIframe ? undefined : hud.widget.endpoint,
    hud.widget.poll_interval ?? 60,
    !isIframe,
  );

  const queryKey = ["hud-data", hud.integrationId, hud.widget.endpoint ?? ""];
  const LabelIcon = resolveHudIcon(hud.widget.icon);

  if (collapsed) {
    return (
      <Pressable
        onPress={() => setCollapsed(false)}
        style={{
          width: 28,
          alignItems: "center",
          justifyContent: "center",
          borderLeftWidth: 1,
          borderLeftColor: t.surfaceBorder,
          backgroundColor: t.surfaceRaised,
        }}
      >
        <ChevronLeft size={14} color={t.textDim} />
        <Text style={{
          fontSize: 10,
          color: t.textDim,
          writingDirection: "ltr",
          transform: [{ rotate: "-90deg" }],
          marginTop: 8,
          width: 80,
          textAlign: "center",
        }}>
          {hud.widget.label ?? hud.widget.id}
        </Text>
      </Pressable>
    );
  }

  return (
    <View style={{
      width,
      borderLeftWidth: 1,
      borderLeftColor: t.surfaceBorder,
      backgroundColor: t.surfaceRaised,
    }}>
      {/* Header */}
      <View style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: 12,
        paddingVertical: 8,
        borderBottomWidth: 1,
        borderBottomColor: t.surfaceBorder,
      }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <LabelIcon size={13} color={t.textDim} />
          <Text style={{ fontSize: 12, fontWeight: "600", color: t.text }}>
            {hud.widget.label ?? hud.widget.id}
          </Text>
        </View>
        <Pressable onPress={() => setCollapsed(true)}>
          <ChevronRight size={14} color={t.textDim} />
        </Pressable>
      </View>

      {/* Content */}
      {isIframe && Platform.OS === "web" ? (
        <IframeContent integrationId={hud.integrationId} iframePath={hud.widget.iframe_path!} />
      ) : data?.visible ? (
        <View style={{ padding: 12, gap: 8 }}>
          {data.items.map((item, i) => (
            <HudItemRenderer key={i} item={item} hudQueryKey={queryKey} />
          ))}
        </View>
      ) : (
        <View style={{ padding: 12 }}>
          <Text style={{ fontSize: 12, color: t.textDim }}>No data</Text>
        </View>
      )}
    </View>
  );
}

function IframeContent({ integrationId, iframePath }: { integrationId: string; iframePath: string }) {
  const { serverUrl } = useAuthStore.getState();
  const token = getAuthToken();
  const src = `${serverUrl}/integrations/${integrationId}${iframePath}${iframePath.includes("?") ? "&" : "?"}tkn=${encodeURIComponent(token || "")}`;

  return (
    <iframe
      src={src}
      style={{
        border: "none",
        width: "100%",
        flex: 1,
        minHeight: 300,
      }}
    />
  );
}
