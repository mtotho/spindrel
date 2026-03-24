import { View } from "react-native";
import { Slot } from "expo-router";
import { Sidebar } from "./Sidebar";
import { DetailPanel } from "./DetailPanel";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";

export function AppShell() {
  const columns = useResponsiveColumns();
  const hasDetail = useUIStore((s) => s.detailPanel.type !== null);

  return (
    <View className="flex-1 flex-row bg-surface">
      {/* Sidebar — hidden on single column (mobile) */}
      {columns !== "single" && <Sidebar />}

      {/* Center content — always visible */}
      <View className="flex-1 min-w-0">
        <Slot />
      </View>

      {/* Detail panel — only on triple column when active */}
      {columns === "triple" && hasDetail && <DetailPanel />}
    </View>
  );
}
