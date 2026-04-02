import { View, Text, Pressable } from "react-native";
import { FileText, Plug } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import type { PromptTemplate } from "../../types/api";

interface TemplateCardGridProps {
  templates: PromptTemplate[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  highlightIntegrations?: string[];
}

export function TemplateCardGrid({ templates, selectedId, onSelect, highlightIntegrations }: TemplateCardGridProps) {
  const t = useThemeTokens();

  return (
    <View style={{ gap: 10 }}>
      {/* Skip option */}
      <Pressable
        onPress={() => onSelect(null)}
        style={{
          borderWidth: 1,
          borderColor: selectedId === null ? t.accent : t.surfaceBorder,
          backgroundColor: selectedId === null ? t.accent + "10" : "transparent",
          borderRadius: 10,
          padding: 14,
        }}
      >
        <Text className="text-text-muted text-sm">Skip — no workspace</Text>
      </Pressable>

      {templates.map((tpl) => {
        const selected = selectedId === tpl.id;
        const integrationTags = (tpl.tags ?? []).filter((tag) => tag.startsWith("integration:"));
        const isRecommended = highlightIntegrations?.length
          ? integrationTags.some((tag) =>
              highlightIntegrations.some((int) => tag === `integration:${int}`),
            )
          : false;

        return (
          <Pressable
            key={tpl.id}
            onPress={() => onSelect(tpl.id)}
            style={{
              borderWidth: 1,
              borderColor: selected ? t.accent : isRecommended ? t.warning + "60" : t.surfaceBorder,
              backgroundColor: selected ? t.accent + "10" : "transparent",
              borderRadius: 10,
              padding: 14,
              gap: 6,
            }}
          >
            <View className="flex-row items-center gap-2">
              <FileText size={16} color={selected ? t.accent : t.textMuted} />
              <Text className={`text-sm font-medium ${selected ? "text-accent" : "text-text"}`} style={{ flex: 1 }}>
                {tpl.name}
              </Text>
              {isRecommended && (
                <View style={{ backgroundColor: t.warning + "20", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 }}>
                  <Text style={{ fontSize: 10, color: t.warning, fontWeight: "600" }}>Recommended</Text>
                </View>
              )}
            </View>
            {tpl.description && (
              <Text className="text-text-muted text-xs" numberOfLines={2}>
                {tpl.description}
              </Text>
            )}
            {integrationTags.length > 0 && (
              <View className="flex-row flex-wrap gap-1" style={{ marginTop: 2 }}>
                {integrationTags.map((tag) => (
                  <View
                    key={tag}
                    style={{
                      backgroundColor: t.surfaceBorder,
                      paddingHorizontal: 6,
                      paddingVertical: 1,
                      borderRadius: 3,
                    }}
                  >
                    <Text style={{ fontSize: 10, color: t.textDim }}>
                      {tag.replace("integration:", "")}
                    </Text>
                  </View>
                ))}
              </View>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}
