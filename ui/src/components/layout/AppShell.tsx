import { useEffect, useState } from "react";
import { View, Pressable, Platform } from "react-native";
import { Slot } from "expo-router";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { SystemPauseBanner } from "./SystemPauseBanner";
import { StreamingToast } from "./StreamingToast";
import { ActiveWorkflowsHud } from "./ActiveWorkflowsHud";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useChatStore } from "../../stores/chat";
import { useSystemStatus } from "../../api/hooks/useSystemStatus";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
  const { data: status } = useSystemStatus();
  const anyStreaming = useChatStore(
    (s) => Object.values(s.channels).some((ch) => ch.isStreaming),
  );

  // Warn on tab close / refresh when a stream is active (web only)
  useEffect(() => {
    if (Platform.OS !== "web" || !anyStreaming) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [anyStreaming]);

  // Keep the overlay mounted during the exit animation, then unmount
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (mobileSidebarOpen) {
      setMounted(true);
      // Trigger the "open" styles on the next frame so the transition fires
      requestAnimationFrame(() => setVisible(true));
    } else {
      setVisible(false);
      // Unmount after the exit transition completes
      const t = setTimeout(() => setMounted(false), 300);
      return () => clearTimeout(t);
    }
  }, [mobileSidebarOpen]);

  return (
    <View className="flex-1 bg-surface overflow-hidden">
      {status?.paused && <SystemPauseBanner behavior={status.pause_behavior} />}
      <View className="flex-1 flex-row overflow-hidden">
        {/* Sidebar — hidden on single column (mobile), shown as overlay when toggled */}
        {columns !== "single" && <Sidebar />}

        {/* Center content — always visible */}
        <View className="flex-1 min-w-0">
          <Slot />
        </View>

        {/* Detail panel — only on triple column when active */}
        {columns === "triple" && hasDetail && <DetailPanel />}

        {/* Streaming toast — shows when a background channel is processing */}
        <StreamingToast />

        {/* Global workflow HUD — shows when any workflow is actively running */}
        <ActiveWorkflowsHud />

        {/* Mobile sidebar drawer — always mounted during animation for smooth exit */}
        {columns === "single" && mounted && (
          <View
            pointerEvents={visible ? "auto" : "none"}
            style={{
              position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
              zIndex: 100,
              flexDirection: "row",
            }}
          >
            {/* Backdrop — fades in/out */}
            <Pressable
              onPress={closeMobileSidebar}
              style={{
                position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                backgroundColor: "rgba(0,0,0,0.6)",
                opacity: visible ? 1 : 0,
                transitionProperty: "opacity",
                transitionDuration: "250ms",
                transitionTimingFunction: "ease-out",
              }}
            />
            {/* Sidebar — slides in from left */}
            <View style={{
              flex: 1, zIndex: 1,
              transform: [{ translateX: visible ? 0 : -300 }],
              transitionProperty: "transform",
              transitionDuration: "280ms",
              transitionTimingFunction: visible
                ? "cubic-bezier(0.0, 0.0, 0.2, 1)"   // decelerate in
                : "cubic-bezier(0.4, 0.0, 1, 1)",     // accelerate out
            }}>
              <Sidebar mobile />
            </View>
          </View>
        )}
      </View>
    </View>
  );
}
