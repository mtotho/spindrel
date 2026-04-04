import { useRouter } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";

const TABS = [
  { key: "agent", label: "Agent Logs", href: "/admin/logs" },
  { key: "traces", label: "Traces", href: "/admin/logs/traces" },
  { key: "server", label: "Server Logs", href: "/admin/logs/server" },
  { key: "fallbacks", label: "Fallbacks", href: "/admin/logs/fallbacks" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function LogsTabBar({ active }: { active: TabKey }) {
  const t = useThemeTokens();
  const router = useRouter();

  return (
    <div
      style={{
        display: "flex",
        gap: 4,
        padding: "8px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
      }}
    >
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            onClick={() => router.push(tab.href as any)}
            style={{
              padding: "6px 14px",
              fontSize: 13,
              fontWeight: isActive ? 600 : 400,
              color: isActive ? t.text : t.textMuted,
              background: isActive ? t.surfaceRaised : "transparent",
              border: `1px solid ${isActive ? t.surfaceBorder : "transparent"}`,
              borderRadius: 6,
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
