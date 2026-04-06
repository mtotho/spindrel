import { Info } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

export function MemoryHygieneGroupBanner() {
  const t = useThemeTokens();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        gap: 10,
        backgroundColor: "rgba(139,92,246,0.08)",
        border: "1px solid rgba(139,92,246,0.25)",
        borderRadius: 8,
        padding: 12,
        marginBottom: 4,
      }}
    >
      <Info
        size={15}
        color="#8b5cf6"
        style={{ marginTop: 1, flexShrink: 0 }}
      />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#8b5cf6" }}>
          What is Memory Hygiene?
        </span>
        <span style={{ fontSize: 11, color: t.textMuted, lineHeight: "17px" }}>
          A periodic background task for bots using workspace-files memory. Each
          run, the bot reviews all its channels, curates MEMORY.md (pruning stale
          facts, detecting contradictions), promotes stable facts from daily logs,
          generates cross-channel reflections, and consolidates skills. The{" "}
          <strong style={{ color: t.text }}>Memory Size Nudge</strong> is a
          separate per-turn check — when MEMORY.md gets too long, the bot sees a
          reminder to keep it concise. Run history is visible in each bot's Memory
          tab.
        </span>
      </div>
    </div>
  );
}
