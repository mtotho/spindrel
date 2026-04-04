import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { resolveHudIcon } from "./hudIcons";
import type { ActiveHud } from "@/src/api/hooks/useChatHud";

/**
 * Floating action button in the bottom-right of the message area.
 * Static button from the manifest — no polling, just on_click.
 * Optionally shows a badge count dot from badge_endpoint.
 */
export function HudFloatingAction({ hud }: { hud: ActiveHud }) {
  const t = useThemeTokens();
  const router = useRouter();
  const Icon = resolveHudIcon(hud.widget.icon);

  const { data: badgeData } = useQuery({
    queryKey: ["hud-badge", hud.integrationId, hud.widget.badge_endpoint],
    queryFn: () =>
      apiFetch<{ count: number }>(
        `/integrations/${hud.integrationId}${hud.widget.badge_endpoint}`
      ),
    enabled: !!hud.widget.badge_endpoint,
    refetchInterval: 60_000,
  });

  const onClick = hud.widget.on_click;
  const handleClick = () => {
    if (onClick?.type === "link" && onClick.href) {
      router.push(onClick.href as any);
    }
  };

  return (
    <button
      onClick={handleClick}
      className="hud-fab"
      aria-label={hud.widget.label ?? "Open HUD action"}
      style={{
        position: "absolute",
        bottom: 16,
        right: 16,
        width: 44,
        height: 44,
        borderRadius: 22,
        backgroundColor: t.accent,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        border: "none",
        boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
        cursor: "pointer",
        zIndex: 10,
        padding: 0,
      }}
    >
      <Icon size={20} color="#fff" />
      {badgeData?.count != null && badgeData.count > 0 && (
        <span style={{
          position: "absolute",
          top: -2,
          right: -2,
          minWidth: 18,
          height: 18,
          borderRadius: 9,
          backgroundColor: t.danger,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 4px",
          fontSize: 10,
          color: "#fff",
          fontWeight: 700,
        }}>
          {badgeData.count > 99 ? "99+" : badgeData.count}
        </span>
      )}
    </button>
  );
}
