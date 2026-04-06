import { useState } from "react";
import { FileText, File, Pencil, RotateCcw, Save, BookTemplate, X, Timer } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
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

interface Props {
  templateId: string | null | undefined;
  schemaContent: string | null | undefined;
  onTemplateChange: (id: string | null) => void;
  onContentChange: (content: string | null) => void;
}

export function WorkspaceSchemaEditor({
  templateId,
  schemaContent,
  onTemplateChange,
  onContentChange,
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

  // No template linked — show simple picker
  if (!hasTemplate && !hasOverride) {
    return (
      <div>
        <PromptTemplateLink
          templateId={null}
          onLink={handleTemplateLink}
          onUnlink={handleTemplateUnlink}
          category="workspace_schema"
        />
      </div>
    );
  }

  return (
    <div>
      {/* Template picker row */}
      <PromptTemplateLink
        templateId={templateId ?? null}
        onLink={handleTemplateLink}
        onUnlink={handleTemplateUnlink}
        category="workspace_schema"
      />

      {/* Template description */}
      {hasTemplate && linkedTemplate.description && !hasOverride && (
        <span style={{ color: t.textDim, fontSize: 12, lineHeight: "18px", marginTop: 4, display: "block" }}>
          {linkedTemplate.description}
        </span>
      )}

      {/* File preview chips for linked template */}
      {hasTemplate && !hasOverride && (() => {
        const files = parseFiles(linkedTemplate.content);
        if (files.length === 0) return null;
        return (
          <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
            {files.slice(0, 5).map((f) => (
              <span
                key={f}
                style={{
                  display: "inline-flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 3,
                  background: t.surfaceOverlay,
                  paddingLeft: 5,
                  paddingRight: 5,
                  paddingTop: 2,
                  paddingBottom: 2,
                  borderRadius: 3,
                  fontSize: 9,
                  color: t.textDim,
                }}
              >
                <File size={8} color={t.textDim} />
                {f.replace(".md", "")}
              </span>
            ))}
            {files.length > 5 && (
              <span style={{ fontSize: 9, color: t.textDim, alignSelf: "center" }}>
                +{files.length - 5} more
              </span>
            )}
          </div>
        );
      })()}

      {/* Heartbeat recommendation */}
      {hasTemplate && linkedTemplate.recommended_heartbeat && !hasOverride && (
        <div style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          marginTop: 6,
          padding: 8,
          borderRadius: 6,
          background: `${t.accent}08`,
          border: `1px solid ${t.accent}20`,
        }}>
          <Timer size={12} color={t.accent} />
          <span style={{ fontSize: 11, color: t.textMuted, flex: 1 }}>
            <span style={{ fontWeight: 600, color: t.accent }}>
              {linkedTemplate.recommended_heartbeat.interval.charAt(0).toUpperCase()
                + linkedTemplate.recommended_heartbeat.interval.slice(1)} heartbeat recommended
            </span>
            {" — "}
            {linkedTemplate.recommended_heartbeat.prompt.length > 80
              ? linkedTemplate.recommended_heartbeat.prompt.slice(0, 80) + "..."
              : linkedTemplate.recommended_heartbeat.prompt}
          </span>
        </div>
      )}

      {hasOverride && (
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2, marginBottom: 4 }}>
          <Pencil size={10} color={t.warning} />
          <span style={{ fontSize: 10, color: t.warning, fontWeight: 600 }}>Customized for this channel</span>
        </div>
      )}

      {/* Blueprint card */}
      <div
        style={{
          marginTop: 8,
          borderLeft: `3px solid ${hasOverride ? t.warning : t.accent}`,
          borderRadius: 6,
          background: t.surfaceOverlay,
          padding: 12,
        }}
      >
        {/* Label */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 }}>
          <FileText size={12} color={t.textDim} />
          <span style={{ fontSize: 10, fontWeight: 700, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Template
          </span>
        </div>

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
            <div style={{ display: "flex", flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <SchemaActionButton
                icon={<Save size={11} />}
                label="Save"
                color={t.accent}
                onClick={handleSave}
                t={t}
              />
              <SchemaActionButton
                icon={<X size={11} />}
                label="Cancel"
                color={t.textDim}
                onClick={handleCancel}
                t={t}
              />
              {hasTemplate && (
                <SchemaActionButton
                  icon={<RotateCcw size={11} />}
                  label="Reset to Template"
                  color={t.textDim}
                  onClick={handleResetToTemplate}
                  t={t}
                />
              )}
              <SchemaActionButton
                icon={<BookTemplate size={11} />}
                label="Save as New Template..."
                color={t.textDim}
                onClick={() => setShowSaveModal(true)}
                t={t}
              />
            </div>
          </>
        ) : (
          <>
            <span
              style={{
                fontSize: 12,
                fontFamily: "monospace",
                color: t.text,
                lineHeight: "18px",
                whiteSpace: "pre-wrap",
                display: "block",
              }}
            >
              {displayContent}
            </span>
            {isLong && (
              <button
                onClick={() => setExpanded(!expanded)}
                style={{
                  marginTop: 4,
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  fontSize: 11,
                  color: t.accent,
                  fontWeight: 500,
                }}
              >
                {expanded ? "Show less" : `Show all (${contentLines.length} lines)`}
              </button>
            )}
            <div style={{ display: "flex", flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <SchemaActionButton
                icon={<Pencil size={11} />}
                label={hasOverride ? "Edit" : "Customize for this channel"}
                color={t.textDim}
                onClick={handleCustomize}
                t={t}
              />
              {hasOverride && hasTemplate && (
                <SchemaActionButton
                  icon={<RotateCcw size={11} />}
                  label="Reset to Template"
                  color={t.textDim}
                  onClick={handleResetToTemplate}
                  t={t}
                />
              )}
              {hasOverride && (
                <SchemaActionButton
                  icon={<BookTemplate size={11} />}
                  label="Save as New Template..."
                  color={t.textDim}
                  onClick={() => setShowSaveModal(true)}
                  t={t}
                />
              )}
            </div>
          </>
        )}
      </div>

      {showSaveModal && (
        <SaveAsTemplateModal
          content={editing ? draft : effectiveContent}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </div>
  );
}

function SchemaActionButton({
  icon,
  label,
  color,
  onClick,
  t,
}: {
  icon: React.ReactNode;
  label: string;
  color: string;
  onClick: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingLeft: 8,
        paddingRight: 8,
        paddingTop: 4,
        paddingBottom: 4,
        borderRadius: 4,
        border: `1px solid ${t.surfaceBorder}`,
        background: "transparent",
        cursor: "pointer",
        fontSize: 11,
        color,
        fontWeight: 500,
      }}
    >
      {icon}
      {label}
    </button>
  );
}
