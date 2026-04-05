import { useMemo } from "react";
import { ChevronRight } from "lucide-react";
import { useRouter } from "expo-router";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";

export function BotOverridesList({ group }: { group: string }) {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: bots } = useAdminBots();

  const overrides = useMemo(() => {
    if (!bots) return [];
    if (group === "Attachments") {
      return bots.filter(
        (b) =>
          b.attachment_summarization_enabled != null ||
          b.attachment_summary_model ||
          b.attachment_text_max_chars != null ||
          b.attachment_vision_concurrency != null
      );
    }
    return [];
  }, [bots, group]);

  if (!overrides.length) return null;

  const sectionHash = "attachments";

  return (
    <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
        Bots with Overrides
      </span>
      <span style={{ fontSize: 11, color: t.textDim, lineHeight: "17px" }}>
        These bots override one or more {group.toLowerCase()} settings.
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {overrides.map((bot) => (
          <button
            key={bot.id}
            onClick={() =>
              router.push(`/admin/bots/${bot.id}#${sectionHash}` as any)
            }
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              backgroundColor: t.surfaceRaised,
              borderRadius: 8,
              border: `1px solid ${t.surfaceOverlay}`,
              padding: 12,
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            <div>
              <span
                style={{ color: t.text, fontSize: 13, fontWeight: 500, display: "block" }}
              >
                {bot.name}
              </span>
              <span
                style={{
                  color: t.textDim,
                  fontSize: 10,
                  fontFamily: "monospace",
                  marginTop: 2,
                  display: "block",
                }}
              >
                {bot.id}
              </span>
            </div>
            <ChevronRight size={14} color={t.textDim} />
          </button>
        ))}
      </div>
    </div>
  );
}
