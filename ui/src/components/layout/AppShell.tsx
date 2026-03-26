import { View, Pressable } from "react-native";
import { Slot } from "expo-router";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { SystemPauseBanner } from "./SystemPauseBanner";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useSystemStatus } from "../../api/hooks/useSystemStatus";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
  const { data: status } = useSystemStatus();

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

        {/* Mobile sidebar drawer overlay */}
        {columns === "single" && mobileSidebarOpen && (
          <View style={{
            position: "absolute", top: 0, left: 0, right: 0, bottom: 0, zIndex: 100,
            flexDirection: "row",
          }}>
            <View style={{ width: 220, flexShrink: 0 }}>
              <Sidebar />
            </View>
            <Pressable
              onPress={closeMobileSidebar}
              style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.5)" }}
            />
          </View>
        )}
      </View>
    </View>
  );
}
