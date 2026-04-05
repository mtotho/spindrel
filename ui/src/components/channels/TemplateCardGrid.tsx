import { useState } from "react";
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
  const [hoverSkip, setHoverSkip] = useState(false);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Group templates by group field for visual sections
  const groupOrder = ["Core", "Technical", "Business", "Personal", "Operations"];
  const sortedTemplates = [...templates].sort((a, b) => {
    const aIdx = groupOrder.indexOf(a.group || "");
    const bIdx = groupOrder.indexOf(b.group || "");
    const aSort = aIdx >= 0 ? aIdx : groupOrder.length;
    const bSort = bIdx >= 0 ? bIdx : groupOrder.length;
    return aSort - bSort;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Skip option */}
      {!hideSkip && (
        <button
          onClick={() => onSelect(null)}
          onMouseEnter={() => setHoverSkip(true)}
          onMouseLeave={() => setHoverSkip(false)}
          style={{
            border: `1px solid ${selectedId === null ? t.accent : t.surfaceBorder}`,
            backgroundColor: selectedId === null ? t.accent + "10" : hoverSkip ? t.surfaceOverlay : "transparent",
            borderRadius: 10,
            padding: 14,
            cursor: "pointer",
            textAlign: "left",
            transition: "background-color 0.15s, border-color 0.15s",
          }}
        >
          <span style={{ color: t.textMuted, fontSize: 14 }}>Skip — no workspace</span>
        </button>
      )}

      {sortedTemplates.map((tpl, idx) => {
        const prevTpl = idx > 0 ? sortedTemplates[idx - 1] : null;
        const showGroupHeader = tpl.group && tpl.group !== prevTpl?.group;
        const selected = selectedId === tpl.id;
        const integrationTags = (tpl.tags ?? []).filter((tag) => tag.startsWith("integration:"));
        const isRecommended = highlightIntegrations?.length
          ? integrationTags.some((tag) =>
              highlightIntegrations.some((int) => tag === `integration:${int}`),
            )
          : false;
        const files = parseFiles(tpl.content);
        const isHovered = hoverIdx === idx;

        return (
          <div key={tpl.id}>
            {showGroupHeader && (
              <span style={{
                display: "block",
                fontSize: 10,
                fontWeight: 700,
                color: t.textDim,
                textTransform: "uppercase",
                letterSpacing: 1,
                marginTop: idx > 0 ? 8 : 0,
                marginBottom: 4,
              }}>
                {tpl.group}
              </span>
            )}
            <button
              onClick={() => onSelect(tpl.id)}
              onMouseEnter={() => setHoverIdx(idx)}
              onMouseLeave={() => setHoverIdx(null)}
              style={{
                display: "flex",
                flexDirection: "column",
                width: "100%",
                border: `1px solid ${selected ? t.accent : isRecommended ? t.success + "50" : t.surfaceBorder}`,
                backgroundColor: selected ? t.accent + "10" : isRecommended ? t.success + "06" : isHovered ? t.surfaceOverlay : "transparent",
                borderRadius: 10,
                padding: 14,
                gap: 6,
                cursor: "pointer",
                textAlign: "left",
                transition: "background-color 0.15s, border-color 0.15s",
              }}
            >
              {/* Header row */}
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                <FileText size={16} color={selected ? t.accent : isRecommended ? t.success : t.textMuted} />
                <span
                  style={{
                    flex: 1,
                    fontSize: 14,
                    fontWeight: 600,
                    color: selected ? t.accent : t.text,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {tpl.name}
                </span>
                {isRecommended && (
                  <span style={{
                    backgroundColor: t.success + "20",
                    padding: "2px 8px",
                    borderRadius: 4,
                    fontSize: 10,
                    color: t.success,
                    fontWeight: 600,
                  }}>
                    Recommended
                  </span>
                )}
              </div>

              {/* Description */}
              {tpl.description && (
                <span style={{
                  fontSize: 12,
                  color: t.textMuted,
                  lineHeight: "17px",
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                }}>
                  {tpl.description}
                </span>
              )}

              {/* What you get: file list + integration tags */}
              {(files.length > 0 || integrationTags.length > 0) && (
                <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 2 }}>
                  {/* Workspace files */}
                  {files.slice(0, 4).map((f) => (
                    <span
                      key={f}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 3,
                        backgroundColor: t.surfaceOverlay,
                        padding: "2px 6px",
                        borderRadius: 4,
                      }}
                    >
                      <File size={9} color={t.textDim} />
                      <span style={{ fontSize: 10, color: t.textDim }}>{f.replace(".md", "")}</span>
                    </span>
                  ))}
                  {files.length > 4 && (
                    <span style={{ fontSize: 10, color: t.textDim, alignSelf: "center" }}>
                      +{files.length - 4} more
                    </span>
                  )}

                  {/* Integration tags */}
                  {integrationTags.map((tag) => {
                    const slug = tag.replace("integration:", "");
                    return (
                      <span
                        key={tag}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 3,
                          backgroundColor: isRecommended ? t.success + "15" : t.surfaceBorder,
                          padding: "2px 6px",
                          borderRadius: 4,
                        }}
                      >
                        <Plug size={9} color={isRecommended ? t.success : t.textDim} />
                        <span style={{ fontSize: 10, color: isRecommended ? t.success : t.textDim, fontWeight: 500 }}>
                          {prettyIntegrationName(slug)}
                        </span>
                      </span>
                    );
                  })}
                </div>
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
}
