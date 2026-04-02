import { useEffect, useRef, useState } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { useRouter, usePathname } from "expo-router";
import { useShallow } from "zustand/react/shallow";
import { Loader2 } from "lucide-react";
import { useChatStore } from "../../stores/chat";
import { useChannels } from "../../api/hooks/useChannels";
import { useThemeTokens } from "../../theme/tokens";

export function StreamingToast() {
  const streamingIds = useChatStore(
    useShallow((s) =>
      Object.entries(s.channels)
        .filter(([, ch]) => ch.isStreaming)
        .map(([id]) => id),
    ),
  );
  const { data: channels } = useChannels();
  const pathname = usePathname();
  const router = useRouter();
  const t = useThemeTokens();

  // Track visibility for CSS transition
  const [visible, setVisible] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Find first streaming channel that the user is NOT currently viewing
  const backgroundStreamId = streamingIds.find(
    (id) => !pathname.includes(id),
  );

  const channel = backgroundStreamId
    ? channels?.find((ch) => ch.id === backgroundStreamId)
    : null;

  const displayName = channel?.display_name || channel?.name || channel?.client_id;

  // Preserve last valid values so exit animation doesn't flash to fallback text
  const lastRef = useRef({ id: backgroundStreamId, name: displayName });
  if (backgroundStreamId) {
    lastRef.current = { id: backgroundStreamId, name: displayName };
  }
  const shownId = backgroundStreamId ?? lastRef.current.id;
  const shownName = backgroundStreamId ? displayName : lastRef.current.name;

  // Mount/unmount with transition
  useEffect(() => {
    if (backgroundStreamId) {
      setMounted(true);
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
      const timer = setTimeout(() => setMounted(false), 200);
      return () => clearTimeout(timer);
    }
  }, [backgroundStreamId]);

  if (!mounted || Platform.OS !== "web") return null;

  return (
    <View
      style={{
        position: "absolute",
        bottom: 16,
        left: 0,
        right: 0,
        alignItems: "center",
        zIndex: 50,
        pointerEvents: "box-none",
      }}
    >
      <Pressable
        onPress={() => {
          if (shownId) {
            router.push(`/channels/${shownId}` as any);
          }
        }}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 16,
          paddingVertical: 10,
          borderRadius: 999,
          backgroundColor: t.surfaceRaised,
          borderWidth: 1,
          borderColor: t.accentBorder,
          opacity: visible ? 1 : 0,
          transform: [{ translateY: visible ? 0 : 8 }],
          transitionProperty: "opacity, transform",
          transitionDuration: "200ms",
          transitionTimingFunction: "ease-out",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        }}
      >
        <Loader2
          size={14}
          color={t.accent}
          className="animate-spin"
        />
        <Text style={{ fontSize: 13, color: t.textMuted }}>
          Processing in{" "}
          <Text style={{ color: t.accent, fontWeight: "600" }}>
            #{shownName ?? "channel"}
          </Text>
          ...
        </Text>
      </Pressable>
    </View>
  );
}
