import { useState } from "react";
import { View, Text, Pressable, ScrollView } from "react-native";
import { FileText, File, Pencil, RotateCcw, Save, BookTemplate, X, Sparkles, Plug } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { prettyIntegrationName } from "../../utils/format";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import { PromptTemplateLink } from "./PromptTemplateLink";
import { SaveAsTemplateModal } from "./SaveAsTemplateModal";

/** Extract workspace file names from template content (e.g., `**repos.md**`). */
function parseFiles(content: string): string[] {
  const matches = content.match(/\*\*(\w[\w-]*\.md)\*\*/g);
  if (!matches) return [];
  return matches
    .map((m) => m.replace(/\*\*/g, ""))
    .filter((f) => f !== "notes.md");
}

function getIntegrationSlug(sourcePath?: string | null): string | null {
  if (!sourcePath) return null;
  const match = sourcePath.match(/integrations\/([^/]+)\//);
  return match?.[1] ?? null;
}

interface Props {
  templateId: string | null | undefined;
  schemaContent: string | null | undefined;
  onTemplateChange: (id: string | null) => void;
  onContentChange: (content: string | null) => void;
  /** When set, templates with this tag get a "Recommended" badge in the picker */
  highlightTag?: string;
  /** Human-readable name of the active integration (e.g. "Mission Control") */
  activeIntegrationName?: string;
}

export function WorkspaceSchemaEditor({
  templateId,
  schemaContent,
  onTemplateChange,
  onContentChange,
  highlightTag,
  activeIntegrationName,
}: Props) {
  const t = useThemeTokens();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const { data: templates } = usePromptTemplates(undefined, "workspace_schema");
  const linkedTemplate = templates?.find((tpl) => tpl.id === templateId);

  // Effective content: override > template > empty
  const effectiveContent = schemaContent || linkedTemplate?.content || "";
  const hasOverride = !!schemaContent;
  const hasTemplate = !!templateId && !!linkedTemplate;

  // Preview line limit — expanded shows all
  const PREVIEW_LINES = 15;
  const contentLines = effectiveContent.split("\n");
  const isLong = contentLines.length > PREVIEW_LINES;
  const displayContent = expanded || !isLong
    ? effectiveContent
    : contentLines.slice(0, PREVIEW_LINES).join("\n") + "\n...";

  const handleCustomize = () => {
    setDraft(effectiveContent);
    setEditing(true);
  };

  const handleCancel = () => {
    setEditing(false);
  };

  const handleSave = () => {
    onContentChange(draft);
    setEditing(false);
  };

  const handleResetToTemplate = () => {
    onContentChange(null);
    setEditing(false);
  };

  const handleTemplateLink = (id: string) => {
    onTemplateChange(id);
    // Clear any override when linking a new template
    if (schemaContent) {
      onContentChange(null);
    }
  };

  const handleTemplateUnlink = () => {
    onTemplateChange(null);
    // Also clear override
    if (schemaContent) {
      onContentChange(null);
    }
  };

  // No template linked — show suggestions (if any) + fallback picker
  if (!hasTemplate && !hasOverride) {
    const suggested = highlightTag
      ? (templates ?? []).filter(
          (tpl) => tpl.tags?.includes(highlightTag) && tpl.source_type !== "workspace_file"
        )
      : [];

    return (
      <View>
        {suggested.length > 0 && (
          <View style={{ marginBottom: 8 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 6 }}>
              <Sparkles size={12} color={t.success} />
              <Text style={{ fontSize: 11, fontWeight: "600", color: t.textDim }}>
                {activeIntegrationName
                  ? `Compatible with ${activeIntegrationName}`
                  : "Suggested templates"}
              </Text>
            </View>
            <View style={{ gap: 6 }}>
              {suggested.map((tpl) => {
                const slug = getIntegrationSlug(tpl.source_path);
                const files = parseFiles(tpl.content);
                return (
                  <Pressable
                    key={tpl.id}
                    onPress={() => handleTemplateLink(tpl.id)}
                    style={{
                      borderWidth: 1,
                      borderColor: t.success + "40",
                      borderLeftWidth: 3,
                      borderLeftColor: t.success,
                      borderRadius: 6,
                      padding: 10,
                      backgroundColor: t.success + "06",
                    }}
                  >
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <FileText size={14} color={t.success} />
                      <Text style={{ fontSize: 12, fontWeight: "600", color: t.text, flex: 1 }}>
                        {tpl.name}
                      </Text>
                      {activeIntegrationName && (
                        <View style={{
                          backgroundColor: t.success + "18",
                          paddingHorizontal: 6,
                          paddingVertical: 2,
                          borderRadius: 3,
                        }}>
                          <Text style={{ fontSize: 9, fontWeight: "600", color: t.success }}>
                            Recommended
                          </Text>
                        </View>
                      )}
                    </View>
                    {tpl.description && (
                      <Text
                        numberOfLines={2}
                        style={{ fontSize: 11, color: t.textMuted, marginTop: 3, lineHeight: 16 }}
                      >
                        {tpl.description}
                      </Text>
                    )}
                    {/* File preview chips + provenance */}
                    {(files.length > 0 || slug) && (
                      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                        {files.slice(0, 4).map((f) => (
                          <View
                            key={f}
                            style={{
                              flexDirection: "row",
                              alignItems: "center",
                              gap: 3,
                              backgroundColor: t.surfaceOverlay,
                              paddingHorizontal: 5,
                              paddingVertical: 2,
                              borderRadius: 3,
                            }}
                          >
                            <File size={8} color={t.textDim} />
                            <Text style={{ fontSize: 9, color: t.textDim }}>{f.replace(".md", "")}</Text>
                          </View>
                        ))}
                        {files.length > 4 && (
                          <Text style={{ fontSize: 9, color: t.textDim, alignSelf: "center" }}>
                            +{files.length - 4}
                          </Text>
                        )}
                        {slug && (
                          <View style={{
                            flexDirection: "row",
                            alignItems: "center",
                            gap: 3,
                            backgroundColor: t.success + "12",
                            paddingHorizontal: 5,
                            paddingVertical: 2,
                            borderRadius: 3,
                            marginLeft: "auto",
                          }}>
                            <Plug size={8} color={t.success} />
                            <Text style={{ fontSize: 9, color: t.success, fontWeight: "500" }}>
                              {prettyIntegrationName(slug)}
                            </Text>
                          </View>
                        )}
                      </View>
                    )}
                  </Pressable>
                );
              })}
            </View>
            {/* Divider before other templates */}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, marginBottom: 2 }}>
              <Text style={{ fontSize: 10, fontWeight: "600", color: t.textDim }}>Other templates</Text>
              <View style={{ flex: 1, height: 1, backgroundColor: t.surfaceBorder }} />
            </View>
          </View>
        )}
        {suggested.length === 0 && activeIntegrationName && (
          <Text style={{ fontSize: 11, color: t.textDim, marginBottom: 6, fontStyle: "italic" }}>
            No templates found compatible with {activeIntegrationName}. You can link any template below.
          </Text>
        )}
        <PromptTemplateLink
          templateId={null}
          onLink={handleTemplateLink}
          onUnlink={handleTemplateUnlink}
          category="workspace_schema"
          highlightTag={highlightTag}
          highlightLabel={activeIntegrationName}
        />
      </View>
    );
  }

  return (
    <View>
      {/* Template picker row */}
      <PromptTemplateLink
        templateId={templateId ?? null}
        onLink={handleTemplateLink}
        onUnlink={handleTemplateUnlink}
        category="workspace_schema"
        highlightTag={highlightTag}
        highlightLabel={activeIntegrationName}
      />

      {/* Compatibility badge */}
      {hasTemplate && activeIntegrationName && highlightTag && (
        linkedTemplate.tags?.includes(highlightTag) ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
            <Text style={{ fontSize: 10, color: t.success, fontWeight: "600" }}>
              {"✓"} Compatible with {activeIntegrationName}
            </Text>
          </View>
        ) : (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
            <Text style={{ fontSize: 10, color: t.warning, fontWeight: "600" }}>
              {"⚠"} Not marked as compatible with {activeIntegrationName}
            </Text>
          </View>
        )
      )}

      {/* Template description */}
      {hasTemplate && linkedTemplate.description && !hasOverride && (
        <Text style={{ color: t.textDim, fontSize: 12, lineHeight: 18, marginTop: 4 }}>
          {linkedTemplate.description}
        </Text>
      )}

      {/* File preview chips for linked template */}
      {hasTemplate && !hasOverride && (() => {
        const files = parseFiles(linkedTemplate.content);
        if (files.length === 0) return null;
        return (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
            {files.slice(0, 5).map((f) => (
              <View
                key={f}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 3,
                  backgroundColor: t.surfaceOverlay,
                  paddingHorizontal: 5,
                  paddingVertical: 2,
                  borderRadius: 3,
                }}
              >
                <File size={8} color={t.textDim} />
                <Text style={{ fontSize: 9, color: t.textDim }}>{f.replace(".md", "")}</Text>
              </View>
            ))}
            {files.length > 5 && (
              <Text style={{ fontSize: 9, color: t.textDim, alignSelf: "center" }}>
                +{files.length - 5} more
              </Text>
            )}
          </View>
        );
      })()}

      {hasOverride && (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2, marginBottom: 4 }}>
          <Pencil size={10} color={t.warning} />
          <Text style={{ fontSize: 10, color: t.warning, fontWeight: "600" }}>Customized for this channel</Text>
        </View>
      )}

      {/* Blueprint card */}
      <View
        style={{
          marginTop: 8,
          borderLeftWidth: 3,
          borderLeftColor: hasOverride ? t.warning : t.accent,
          borderRadius: 6,
          backgroundColor: t.surfaceOverlay,
          padding: 12,
        }}
      >
        {/* Label */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 }}>
          <FileText size={12} color={t.textDim} />
          <Text style={{ fontSize: 10, fontWeight: "700", color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Template
          </Text>
        </View>

        {editing ? (
          <>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              style={{
                width: "100%",
                minHeight: 200,
                background: t.inputBg,
                border: `1px solid ${t.inputBorder}`,
                borderRadius: 4,
                padding: 10,
                fontSize: 12,
                fontFamily: "monospace",
                color: t.inputText,
                resize: "vertical" as const,
                outline: "none",
                lineHeight: "1.5",
              }}
            />
            <View style={{ flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <ActionButton
                icon={<Save size={11} />}
                label="Save"
                color={t.accent}
                onPress={handleSave}
                t={t}
              />
              <ActionButton
                icon={<X size={11} />}
                label="Cancel"
                color={t.textDim}
                onPress={handleCancel}
                t={t}
              />
              {hasTemplate && (
                <ActionButton
                  icon={<RotateCcw size={11} />}
                  label="Reset to Template"
                  color={t.textDim}
                  onPress={handleResetToTemplate}
                  t={t}
                />
              )}
              <ActionButton
                icon={<BookTemplate size={11} />}
                label="Save as New Template..."
                color={t.textDim}
                onPress={() => setShowSaveModal(true)}
                t={t}
              />
            </View>
          </>
        ) : (
          <>
            <Text
              style={{
                fontSize: 12,
                fontFamily: "monospace",
                color: t.text,
                lineHeight: 18,
              } as any}
            >
              {displayContent}
            </Text>
            {isLong && (
              <Pressable onPress={() => setExpanded(!expanded)} style={{ marginTop: 4 }}>
                <Text style={{ fontSize: 11, color: t.accent, fontWeight: "500" }}>
                  {expanded ? "Show less" : `Show all (${contentLines.length} lines)`}
                </Text>
              </Pressable>
            )}
            <View style={{ flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <ActionButton
                icon={<Pencil size={11} />}
                label={hasOverride ? "Edit" : "Customize for this channel"}
                color={t.textDim}
                onPress={handleCustomize}
                t={t}
              />
              {hasOverride && hasTemplate && (
                <ActionButton
                  icon={<RotateCcw size={11} />}
                  label="Reset to Template"
                  color={t.textDim}
                  onPress={handleResetToTemplate}
                  t={t}
                />
              )}
              {hasOverride && (
                <ActionButton
                  icon={<BookTemplate size={11} />}
                  label="Save as New Template..."
                  color={t.textDim}
                  onPress={() => setShowSaveModal(true)}
                  t={t}
                />
              )}
            </View>
          </>
        )}
      </View>

      {showSaveModal && (
        <SaveAsTemplateModal
          content={editing ? draft : effectiveContent}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </View>
  );
}

function ActionButton({
  icon,
  label,
  color,
  onPress,
  t,
}: {
  icon: React.ReactNode;
  label: string;
  color: string;
  onPress: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 8,
        paddingVertical: 4,
        borderRadius: 4,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
      }}
    >
      {icon}
      <Text style={{ fontSize: 11, color, fontWeight: "500" }}>{label}</Text>
    </Pressable>
  );
}
