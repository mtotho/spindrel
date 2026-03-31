import { useMemo } from "react";
import { View, Text, Pressable } from "react-native";
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
    if (group === "Model Elevation") {
      return bots.filter(
        (b) =>
          b.elevation_enabled != null ||
          b.elevation_threshold != null ||
          b.elevated_model
      );
    }
    return [];
  }, [bots, group]);

  if (!overrides.length) return null;

  const sectionHash = group === "Attachments" ? "attachments" : "elevation";

  return (
    <View style={{ marginTop: 20, gap: 8 }}>
      <Text style={{ fontSize: 13, fontWeight: "600", color: t.text }}>
        Bots with Overrides
      </Text>
      <Text style={{ fontSize: 11, color: t.textDim, lineHeight: 17 }}>
        These bots override one or more {group.toLowerCase()} settings.
      </Text>
      <View style={{ gap: 6 }}>
        {overrides.map((bot) => (
          <Pressable
            key={bot.id}
            onPress={() =>
              router.push(`/admin/bots/${bot.id}#${sectionHash}` as any)
            }
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              backgroundColor: t.surfaceRaised,
              borderRadius: 8,
              borderWidth: 1,
              borderColor: t.surfaceOverlay,
              padding: 12,
            }}
          >
            <View>
              <Text
                style={{ color: t.text, fontSize: 13, fontWeight: "500" }}
              >
                {bot.name}
              </Text>
              <Text
                style={{
                  color: t.textDim,
                  fontSize: 10,
                  fontFamily: "monospace",
                  marginTop: 2,
                }}
              >
                {bot.id}
              </Text>
            </View>
            <ChevronRight size={14} color={t.textDim} />
          </Pressable>
        ))}
      </View>
    </View>
  );
}
