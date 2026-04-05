import { useState } from "react";
import { FileText, File, Pencil, RotateCcw, Save, BookTemplate, X, Sparkles, Plug, Timer } from "lucide-react";
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
      <div>
        {suggested.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 6 }}>
              <Sparkles size={12} color={t.success} />
              <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim }}>
                {activeIntegrationName
                  ? `Compatible with ${activeIntegrationName}`
                  : "Suggested templates"}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {suggested.map((tpl) => {
                const slug = getIntegrationSlug(tpl.source_path);
                const files = parseFiles(tpl.content);
                return (
                  <button
                    key={tpl.id}
                    onClick={() => handleTemplateLink(tpl.id)}
                    style={{
                      border: `1px solid ${t.success}40`,
                      borderLeft: `3px solid ${t.success}`,
                      borderRadius: 6,
                      padding: 10,
                      background: `${t.success}06`,
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <FileText size={14} color={t.success} />
                      <span style={{ fontSize: 12, fontWeight: 600, color: t.text, flex: 1 }}>
                        {tpl.name}
                      </span>
                      {activeIntegrationName && (
                        <span style={{
                          background: `${t.success}18`,
                          paddingLeft: 6,
                          paddingRight: 6,
                          paddingTop: 2,
                          paddingBottom: 2,
                          borderRadius: 3,
                          fontSize: 9,
                          fontWeight: 600,
                          color: t.success,
                        }}>
                          Recommended
                        </span>
                      )}
                    </div>
                    {tpl.description && (
                      <span
                        style={{
                          fontSize: 11,
                          color: t.textMuted,
                          marginTop: 3,
                          lineHeight: "16px",
                          display: "-webkit-box",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                        }}
                      >
                        {tpl.description}
                      </span>
                    )}
                    {/* File preview chips + provenance + heartbeat hint */}
                    {(files.length > 0 || slug) && (
                      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                        {files.slice(0, 4).map((f) => (
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
                        {files.length > 4 && (
                          <span style={{ fontSize: 9, color: t.textDim, alignSelf: "center" }}>
                            +{files.length - 4}
                          </span>
                        )}
                        {tpl.recommended_heartbeat && (
                          <span style={{
                            display: "inline-flex",
                            flexDirection: "row",
                            alignItems: "center",
                            gap: 3,
                            background: `${t.accent}12`,
                            paddingLeft: 5,
                            paddingRight: 5,
                            paddingTop: 2,
                            paddingBottom: 2,
                            borderRadius: 3,
                            fontSize: 9,
                            color: t.accent,
                            fontWeight: 500,
                          }}>
                            <Timer size={8} color={t.accent} />
                            {tpl.recommended_heartbeat.interval.charAt(0).toUpperCase() + tpl.recommended_heartbeat.interval.slice(1)}
                          </span>
                        )}
                        {slug && (
                          <span style={{
                            display: "inline-flex",
                            flexDirection: "row",
                            alignItems: "center",
                            gap: 3,
                            background: `${t.success}12`,
                            paddingLeft: 5,
                            paddingRight: 5,
                            paddingTop: 2,
                            paddingBottom: 2,
                            borderRadius: 3,
                            marginLeft: "auto",
                            fontSize: 9,
                            color: t.success,
                            fontWeight: 500,
                          }}>
                            <Plug size={8} color={t.success} />
                            {prettyIntegrationName(slug)}
                          </span>
                        )}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
            {/* Divider before other templates */}
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, marginBottom: 2 }}>
              <span style={{ fontSize: 10, fontWeight: 600, color: t.textDim }}>Other templates</span>
              <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
            </div>
          </div>
        )}
        {suggested.length === 0 && activeIntegrationName && (
          <span style={{ fontSize: 11, color: t.textDim, marginBottom: 6, fontStyle: "italic", display: "block" }}>
            No templates found compatible with {activeIntegrationName}. You can link any template below.
          </span>
        )}
        <PromptTemplateLink
          templateId={null}
          onLink={handleTemplateLink}
          onUnlink={handleTemplateUnlink}
          category="workspace_schema"
          highlightTag={highlightTag}
          highlightLabel={activeIntegrationName}
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
        highlightTag={highlightTag}
        highlightLabel={activeIntegrationName}
      />

      {/* Compatibility badge */}
      {hasTemplate && activeIntegrationName && highlightTag && (
        linkedTemplate.tags?.includes(highlightTag) ? (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
            <span style={{ fontSize: 10, color: t.success, fontWeight: 600 }}>
              {"✓"} Compatible with {activeIntegrationName}
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
            <span style={{ fontSize: 10, color: t.warning, fontWeight: 600 }}>
              {"⚠"} Not marked as compatible with {activeIntegrationName}
            </span>
          </div>
        )
      )}

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
