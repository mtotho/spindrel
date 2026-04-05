import { useEffect, useRef, useState } from "react";
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

  if (!mounted) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: 16,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        zIndex: 50,
        pointerEvents: "none",
      }}
    >
      <button
        className="streaming-toast-btn"
        onClick={() => {
          if (shownId) {
            router.push(`/channels/${shownId}` as any);
          }
        }}
        style={{
          pointerEvents: "auto",
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingLeft: 16,
          paddingRight: 16,
          paddingTop: 10,
          paddingBottom: 10,
          borderRadius: 999,
          backgroundColor: t.surfaceRaised,
          border: `1px solid ${t.accentBorder}`,
          opacity: visible ? 1 : 0,
          transform: `translateY(${visible ? 0 : 8}px)`,
          transition: "opacity 200ms ease-out, transform 200ms ease-out",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
          cursor: "pointer",
          color: "inherit",
          font: "inherit",
        }}
      >
        <Loader2
          size={14}
          color={t.accent}
          className="animate-spin"
        />
        <span style={{ fontSize: 13, color: t.textMuted }}>
          Processing in{" "}
          <span style={{ color: t.accent, fontWeight: 600 }}>
            #{shownName ?? "channel"}
          </span>
          ...
        </span>
      </button>
    </div>
  );
}
