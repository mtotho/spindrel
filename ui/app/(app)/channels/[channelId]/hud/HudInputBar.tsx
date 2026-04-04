import { useThemeTokens } from "@/src/theme/tokens";
import { useHudData, type ActiveHud } from "@/src/api/hooks/useChatHud";
import { HudItemRenderer } from "./HudItemRenderer";

/**
 * Action button row above message input, in the same zone as ActiveWorkflowStrip.
 * Polls a HUD endpoint and renders action buttons.
 */
export function HudInputBar({ hud }: { hud: ActiveHud }) {
  const t = useThemeTokens();
  const { data } = useHudData(
    hud.integrationId,
    hud.widget.endpoint,
    hud.widget.poll_interval ?? 60,
  );

  if (!data?.visible || !data.items.length) return null;

  const queryKey = ["hud-data", hud.integrationId, hud.widget.endpoint ?? ""];

  return (
    <div style={{
      display: "flex",
      flexDirection: "row",
      alignItems: "center",
      padding: "4px 12px",
      gap: 6,
      flexWrap: "wrap",
      borderTop: `1px solid ${t.surfaceBorder}`,
      backgroundColor: t.surfaceRaised,
    }}>
      {hud.widget.label && (
        <span style={{ fontSize: 10, color: t.textDim, fontWeight: 600, marginRight: 2 }}>
          {hud.widget.label}
        </span>
      )}
      {data.items.map((item, i) => (
        <HudItemRenderer key={i} item={item} hudQueryKey={queryKey} />
      ))}
    </div>
  );
}
