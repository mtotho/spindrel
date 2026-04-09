import { View, useWindowDimensions } from "react-native";
import { useHashTab } from "@/src/hooks/useHashTab";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { OverviewTab } from "./OverviewTab";
import { DreamingTab } from "./DreamingTab";
import { SkillsTab } from "./SkillsTab";

const TABS = ["Overview", "Dreaming", "Skills"] as const;
type Tab = (typeof TABS)[number];

export default function LearningCenterPage() {
  const t = useThemeTokens();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const [tab, setTab] = useHashTab<Tab>("Overview", TABS);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Learning Center" subtitle="Memory, dreaming & skills" />

      {/* Tab bar */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderBottom: `1px solid ${t.surfaceOverlay}`,
          padding: isMobile ? "0 12px" : "0 20px",
        }}
      >
        {TABS.map((tabName) => (
          <button
            key={tabName}
            onClick={() => setTab(tabName)}
            style={{
              padding: "10px 16px",
              fontSize: 13,
              fontWeight: tab === tabName ? 600 : 400,
              color: tab === tabName ? t.accent : t.textMuted,
              background: "none",
              border: "none",
              borderBottom: tab === tabName ? `2px solid ${t.accent}` : "2px solid transparent",
              cursor: "pointer",
            }}
          >
            {tabName}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        <div style={{ padding: isMobile ? 12 : 20 }}>
          {tab === "Overview" && <OverviewTab />}
          {tab === "Dreaming" && <DreamingTab />}
          {tab === "Skills" && <SkillsTab />}
        </div>
      </RefreshableScrollView>
    </View>
  );
}
