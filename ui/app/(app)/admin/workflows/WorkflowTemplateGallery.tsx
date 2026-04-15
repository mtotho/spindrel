/**
 * Template gallery shown on the "new workflow" page before the blank form.
 * Displays file-based workflows as reusable starting points.
 */

import { Spinner } from "@/src/components/shared/Spinner";
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
    <div style={{ display: "flex", gap: 16 }}>
      <div style={{ display: "flex", gap: 4 }}>
        <span style={{ color: t.text, fontSize: 18, fontWeight: "700" }}>
          Create a Workflow
        </span>
        <span style={{ color: t.textMuted, fontSize: 13 }}>
          Start from a template, import YAML, or build from scratch.
        </span>
      </div>

      {isLoading ? (
        <div style={{ display: "flex", alignItems: "center", padding: 32 }}>
          <Spinner />
        </div>
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
            onClick={onImportYaml}
            t={t}
          />

          {/* Blank */}
          <ActionCard
            icon={<Plus size={20} color={t.textMuted} />}
            title="Blank Workflow"
            description="Start from scratch with an empty definition"
            onClick={onStartBlank}
            t={t}
          />
        </div>
      )}
    </div>
  );
}

function TemplateCard({ template, onSelect, t }: {
  template: Workflow;
  onSelect: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button type="button"
      onClick={onSelect}
      style={{
        backgroundColor: t.codeBg,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
        padding: 16,
      }}
    >
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Zap size={16} color={t.accent} />
        <span style={{ color: t.text, fontWeight: "600", fontSize: 14, flex: 1 }}>
          {template.name}
        </span>
      </div>
      {template.description ? (
        <span style={{ color: t.textMuted, fontSize: 12, marginBottom: 8 }}>
          {template.description}
        </span>
      ) : null}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ color: t.textDim, fontSize: 11 }}>
          {template.steps.length} step{template.steps.length !== 1 ? "s" : ""}
        </span>
        {template.tags.length > 0 && template.tags.map((tag) => (
          <div key={tag} style={{
            backgroundColor: t.purpleSubtle, borderWidth: 1,
            borderColor: t.purpleBorder, paddingInline: 5,
            paddingBlock: 1, borderRadius: 3,
          }}>
            <span style={{ color: t.purple, fontSize: 10 }}>{tag}</span>
          </div>
        ))}
        <div style={{
          backgroundColor: t.accentSubtle, borderWidth: 1,
          borderColor: t.accentBorder, paddingInline: 5,
          paddingBlock: 1, borderRadius: 3,
        }}>
          <span style={{ color: t.accent, fontSize: 10 }}>{template.source_type}</span>
        </div>
      </div>
    </button>
  );
}

function ActionCard({ icon, title, description, onClick, t }: {
  icon: React.ReactNode;
  title: string;
  description: string;
  onClick: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button type="button"
      onClick={onClick}
      style={{
        display: "flex",
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
      <div style={{ marginBottom: 8 }}>{icon}</div>
      <span style={{ color: t.text, fontWeight: "600", fontSize: 14, marginBottom: 4 }}>
        {title}
      </span>
      <span style={{ color: t.textMuted, fontSize: 12, textAlign: "center" }}>
        {description}
      </span>
    </button>
  );
}
