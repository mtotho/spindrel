import { useState } from "react";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useHashTab } from "@/src/hooks/useHashTab";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { OverviewTab } from "./OverviewTab";
import { DreamingTab } from "./DreamingTab";
import { SkillsTab } from "./SkillsTab";

const TABS = ["Overview", "Dreaming", "Skills"] as const;
type Tab = (typeof TABS)[number];

const TIME_RANGES = [
  { label: "24h", days: 1 },
  { label: "3d", days: 3 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "60d", days: 60 },
  { label: "All", days: 0 },
] as const;

export default function LearningCenterPage() {
  const t = useThemeTokens();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isMobile = width < 768;
  const [tab, setTab] = useHashTab<Tab>("Overview", TABS);
  const [days, setDays] = useState(7);

  const showTimeRange = tab === "Overview" || tab === "Skills";

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Learning Center" subtitle="Memory, dreaming & skills" />

      {/* Tab bar + time range */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
        borderBottom: `1px solid ${t.surfaceOverlay}`,
        padding: isMobile ? "0 12px" : "0 20px",
      }}>
        <div style={{ display: "flex", flexDirection: "row", gap: 0 }}>
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

        {/* Time range pills */}
        {showTimeRange && (
          <div style={{
            display: "flex", flexDirection: "row", gap: 2, padding: "2px",
            borderRadius: 6, background: t.surfaceOverlay,
          }}>
            {TIME_RANGES.map((r) => (
              <button
                key={r.label}
                onClick={() => setDays(r.days)}
                style={{
                  padding: "3px 8px",
                  fontSize: 10,
                  fontWeight: days === r.days ? 700 : 400,
                  color: days === r.days ? t.text : t.textDim,
                  background: days === r.days ? t.surfaceRaised : "transparent",
                  border: days === r.days ? `1px solid ${t.surfaceBorder}` : "1px solid transparent",
                  borderRadius: 4,
                  cursor: "pointer",
                  letterSpacing: 0.3,
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab content */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        <div style={{ padding: isMobile ? 12 : 20 }}>
          {tab === "Overview" && <OverviewTab days={days} />}
          {tab === "Dreaming" && <DreamingTab />}
          {tab === "Skills" && <SkillsTab days={days} />}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
