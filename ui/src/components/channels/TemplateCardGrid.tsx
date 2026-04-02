import { View, Text, Pressable } from "react-native";
import { FileText, File, Plug } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { prettyIntegrationName } from "../../utils/format";
import type { PromptTemplate } from "../../types/api";

/** Extract workspace file names from template content (e.g., `**repos.md**`). */
function parseFiles(content: string): string[] {
  const matches = content.match(/\*\*(\w[\w-]*\.md)\*\*/g);
  if (!matches) return [];
  return matches
    .map((m) => m.replace(/\*\*/g, ""))
    .filter((f) => f !== "notes.md"); // skip generic notes file
}

interface TemplateCardGridProps {
  templates: PromptTemplate[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  highlightIntegrations?: string[];
  /** Hide the "skip" card (e.g., in onboarding contexts). */
  hideSkip?: boolean;
}

export function TemplateCardGrid({ templates, selectedId, onSelect, highlightIntegrations, hideSkip }: TemplateCardGridProps) {
  const t = useThemeTokens();

  return (
    <View style={{ gap: 10 }}>
      {/* Skip option */}
      {!hideSkip && (
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
      )}

      {templates.map((tpl) => {
        const selected = selectedId === tpl.id;
        const integrationTags = (tpl.tags ?? []).filter((tag) => tag.startsWith("integration:"));
        const isRecommended = highlightIntegrations?.length
          ? integrationTags.some((tag) =>
              highlightIntegrations.some((int) => tag === `integration:${int}`),
            )
          : false;
        const files = parseFiles(tpl.content);

        return (
          <Pressable
            key={tpl.id}
            onPress={() => onSelect(tpl.id)}
            style={{
              borderWidth: 1,
              borderColor: selected ? t.accent : isRecommended ? t.success + "50" : t.surfaceBorder,
              backgroundColor: selected ? t.accent + "10" : isRecommended ? t.success + "06" : "transparent",
              borderRadius: 10,
              padding: 14,
              gap: 6,
            }}
          >
            {/* Header row */}
            <View className="flex-row items-center gap-2">
              <FileText size={16} color={selected ? t.accent : isRecommended ? t.success : t.textMuted} />
              <Text
                style={{
                  flex: 1,
                  fontSize: 14,
                  fontWeight: "600",
                  color: selected ? t.accent : t.text,
                }}
                numberOfLines={1}
              >
                {tpl.name}
              </Text>
              {isRecommended && (
                <View style={{ backgroundColor: t.success + "20", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 }}>
                  <Text style={{ fontSize: 10, color: t.success, fontWeight: "600" }}>Recommended</Text>
                </View>
              )}
            </View>

            {/* Description */}
            {tpl.description && (
              <Text style={{ fontSize: 12, color: t.textMuted, lineHeight: 17 }} numberOfLines={2}>
                {tpl.description}
              </Text>
            )}

            {/* What you get: file list + integration tags */}
            {(files.length > 0 || integrationTags.length > 0) && (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 2 }}>
                {/* Workspace files */}
                {files.slice(0, 4).map((f) => (
                  <View
                    key={f}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 3,
                      backgroundColor: t.surfaceOverlay,
                      paddingHorizontal: 6,
                      paddingVertical: 2,
                      borderRadius: 4,
                    }}
                  >
                    <File size={9} color={t.textDim} />
                    <Text style={{ fontSize: 10, color: t.textDim }}>{f.replace(".md", "")}</Text>
                  </View>
                ))}
                {files.length > 4 && (
                  <Text style={{ fontSize: 10, color: t.textDim, alignSelf: "center" }}>
                    +{files.length - 4} more
                  </Text>
                )}

                {/* Integration tags */}
                {integrationTags.map((tag) => {
                  const slug = tag.replace("integration:", "");
                  return (
                    <View
                      key={tag}
                      style={{
                        flexDirection: "row",
                        alignItems: "center",
                        gap: 3,
                        backgroundColor: isRecommended ? t.success + "15" : t.surfaceBorder,
                        paddingHorizontal: 6,
                        paddingVertical: 2,
                        borderRadius: 4,
                      }}
                    >
                      <Plug size={9} color={isRecommended ? t.success : t.textDim} />
                      <Text style={{ fontSize: 10, color: isRecommended ? t.success : t.textDim, fontWeight: "500" }}>
                        {prettyIntegrationName(slug)}
                      </Text>
                    </View>
                  );
                })}
              </View>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}
