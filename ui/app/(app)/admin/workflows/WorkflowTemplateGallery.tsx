/**
 * Template gallery shown on the "new workflow" page before the blank form.
 * Displays file-based workflows as reusable starting points.
 */
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWorkflowTemplates } from "@/src/api/hooks/useWorkflows";
import { Zap, ClipboardPaste, Plus } from "lucide-react";
import type { Workflow } from "@/src/types/api";

interface Props {
  onSelectTemplate: (template: Partial<Workflow>) => void;
  onStartBlank: () => void;
  onImportYaml: () => void;
}

export function WorkflowTemplateGallery({ onSelectTemplate, onStartBlank, onImportYaml }: Props) {
  const t = useThemeTokens();
  const { data: templates, isLoading } = useWorkflowTemplates();

  return (
    <View style={{ gap: 16 }}>
      <View style={{ gap: 4 }}>
        <Text style={{ color: t.text, fontSize: 18, fontWeight: "700" }}>
          Create a Workflow
        </Text>
        <Text style={{ color: t.textMuted, fontSize: 13 }}>
          Start from a template, import YAML, or build from scratch.
        </Text>
      </View>

      {isLoading ? (
        <View style={{ alignItems: "center", padding: 32 }}>
          <ActivityIndicator color={t.accent} />
        </View>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
          gap: 12,
        }}>
          {/* Templates */}
          {(!templates || templates.length === 0) && (
            <div style={{
              gridColumn: "1 / -1",
              padding: "8px 0",
              fontSize: 12,
              color: t.textDim,
            }}>
              No templates found. Add YAML files to <code style={{ fontSize: 11 }}>workflows/</code> to see them here.
            </div>
          )}
          {templates?.map((tmpl) => (
            <TemplateCard
              key={tmpl.id}
              template={tmpl}
              onSelect={() => onSelectTemplate({
                id: `${tmpl.id}-custom`,
                name: `${tmpl.name} (copy)`,
                description: tmpl.description || "",
                steps: tmpl.steps || [],
                params: tmpl.params || {},
                defaults: tmpl.defaults || {},
                secrets: tmpl.secrets || [],
                triggers: tmpl.triggers || {},
                tags: tmpl.tags || [],
                session_mode: tmpl.session_mode || "isolated",
              })}
              t={t}
            />
          ))}

          {/* Import YAML */}
          <ActionCard
            icon={<ClipboardPaste size={20} color={t.accent} />}
            title="Import YAML"
            description="Paste an existing workflow definition"
            onPress={onImportYaml}
            t={t}
          />

          {/* Blank */}
          <ActionCard
            icon={<Plus size={20} color={t.textMuted} />}
            title="Blank Workflow"
            description="Start from scratch with an empty definition"
            onPress={onStartBlank}
            t={t}
          />
        </div>
      )}
    </View>
  );
}

function TemplateCard({ template, onSelect, t }: {
  template: Workflow;
  onSelect: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <Pressable
      onPress={onSelect}
      style={{
        backgroundColor: t.codeBg,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
        padding: 16,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Zap size={16} color={t.accent} />
        <Text style={{ color: t.text, fontWeight: "600", fontSize: 14, flex: 1 }} numberOfLines={1}>
          {template.name}
        </Text>
      </View>
      {template.description ? (
        <Text style={{ color: t.textMuted, fontSize: 12, marginBottom: 8 }} numberOfLines={2}>
          {template.description}
        </Text>
      ) : null}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Text style={{ color: t.textDim, fontSize: 11 }}>
          {template.steps.length} step{template.steps.length !== 1 ? "s" : ""}
        </Text>
        {template.tags.length > 0 && template.tags.map((tag) => (
          <View key={tag} style={{
            backgroundColor: t.purpleSubtle, borderWidth: 1,
            borderColor: t.purpleBorder, paddingHorizontal: 5,
            paddingVertical: 1, borderRadius: 3,
          }}>
            <Text style={{ color: t.purple, fontSize: 10 }}>{tag}</Text>
          </View>
        ))}
        <View style={{
          backgroundColor: t.accentSubtle, borderWidth: 1,
          borderColor: t.accentBorder, paddingHorizontal: 5,
          paddingVertical: 1, borderRadius: 3,
        }}>
          <Text style={{ color: t.accent, fontSize: 10 }}>{template.source_type}</Text>
        </View>
      </View>
    </Pressable>
  );
}

function ActionCard({ icon, title, description, onPress, t }: {
  icon: React.ReactNode;
  title: string;
  description: string;
  onPress: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        backgroundColor: t.codeBg,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
        borderStyle: "dashed",
        padding: 16,
        alignItems: "center",
        justifyContent: "center",
        minHeight: 100,
      }}
    >
      <View style={{ marginBottom: 8 }}>{icon}</View>
      <Text style={{ color: t.text, fontWeight: "600", fontSize: 14, marginBottom: 4 }}>
        {title}
      </Text>
      <Text style={{ color: t.textMuted, fontSize: 12, textAlign: "center" }}>
        {description}
      </Text>
    </Pressable>
  );
}
