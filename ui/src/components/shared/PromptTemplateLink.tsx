import { useState, useRef } from "react";
import { Link2, Unlink, Pencil, X } from "lucide-react";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import { useThemeTokens } from "../../theme/tokens";
import { prettyIntegrationName } from "../../utils/format";
import { createPortal } from "react-dom";

function getIntegrationLabel(sourcePath?: string | null): string | null {
  if (!sourcePath) return null;
  const match = sourcePath.match(/integrations\/([^/]+)\//);
  if (!match) return null;
  return prettyIntegrationName(match[1]);
}

interface Props {
  templateId: string | null | undefined;
  onLink: (id: string) => void;
  onUnlink: () => void;
  /** When set, only show templates matching this category */
  category?: string;
}

export function PromptTemplateLink({ templateId, onLink, onUnlink, category }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const { data: templates } = usePromptTemplates(undefined, category);
  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
  const t = useThemeTokens();

  const linked = templates?.find((tpl) => tpl.id === templateId);

  const q = search.toLowerCase();
  const filtered = templates
    ? q
      ? templates.filter(
          (tpl) =>
            tpl.name.toLowerCase().includes(q) ||
            (tpl.category || "").toLowerCase().includes(q) ||
            (tpl.description || "").toLowerCase().includes(q) ||
            (tpl.tags || []).some((tag: string) => tag.toLowerCase().includes(q))
        )
      : templates
    : [];

  // Only show manual templates (not workspace_file sourced)
  const manual = filtered.filter((tpl) => tpl.source_type !== "workspace_file");

  const close = () => { setOpen(false); setSearch(""); };

  const selectTemplate = (id: string) => {
    onLink(id);
    close();
  };

  // Shared template list content
  const templateList = (
    <div style={{ flex: 1, overflowY: "auto", padding: "4px 0", WebkitOverflowScrolling: "touch" }}>
      {manual.length === 0 && (
        <div style={{ padding: "16px 12px", textAlign: "center", color: t.textDim, fontSize: 12 }}>
          No templates found
        </div>
      )}
      {manual.map((tpl, idx) => {
        const prevTpl = idx > 0 ? manual[idx - 1] : null;
        const showGroupHeader = tpl.group && tpl.group !== prevTpl?.group;
        return (
          <div key={tpl.id}>
            {showGroupHeader && (
              <div style={{
                padding: `${idx > 0 ? 8 : 4}px 12px 2px`,
                fontSize: 9,
                fontWeight: 700,
                color: t.textDim,
                textTransform: "uppercase",
                letterSpacing: 0.8,
                ...(idx > 0 ? { borderTop: `1px solid ${t.surfaceBorder}`, marginTop: 2 } : {}),
              }}>
                {tpl.group}
              </div>
            )}
            <button
              onMouseDown={(e) => {
                e.preventDefault();
                selectTemplate(tpl.id);
              }}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: isMobile ? 4 : 2,
                width: "100%",
                padding: isMobile ? "10px 16px" : "6px 12px",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = t.surfaceOverlay)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                <Pencil size={isMobile ? 13 : 11} color={t.accent} />
                <span style={{ fontSize: isMobile ? 14 : 12, fontWeight: 600, color: t.text }}>
                  {tpl.name}
                </span>
                {(tpl.source_type === "integration" || tpl.source_type === "file") && (
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                      padding: "1px 5px",
                      borderRadius: 3,
                      background: t.surfaceOverlay,
                      color: t.textDim,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {(tpl.source_type === "integration" && getIntegrationLabel(tpl.source_path)) || "Built-in"}
                  </span>
                )}
              </div>
              {tpl.description && (
                <span
                  style={{
                    fontSize: isMobile ? 12 : 11,
                    color: t.textDim,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    paddingLeft: isMobile ? 19 : 17,
                  }}
                >
                  {tpl.description}
                </span>
              )}
            </button>
          </div>
        );
      })}
    </div>
  );

  // Search bar
  const searchBar = (
    <input
      type="text"
      value={search}
      onChange={(e) => setSearch(e.target.value)}
      placeholder="Search templates..."
      autoFocus
      style={{
        width: "100%",
        background: t.inputBg,
        border: `1px solid ${t.inputBorder}`,
        borderRadius: isMobile ? 8 : 4,
        padding: isMobile ? "10px 12px" : "5px 8px",
        fontSize: isMobile ? 16 : 12,
        color: t.inputText,
        outline: "none",
      }}
    />
  );

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
      {linked ? (
        <>
          <div
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 5,
              padding: "3px 8px",
              fontSize: 11,
              fontWeight: 600,
              borderRadius: 4,
              background: t.accentSubtle,
              border: `1px solid ${t.accentBorder}`,
              color: t.accent,
            }}
          >
            <Pencil size={11} />
            {linked.name}
            {(linked.source_type === "integration" || linked.source_type === "file") && (
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  padding: "1px 5px",
                  borderRadius: 3,
                  background: `${t.accent}22`,
                  color: t.accent,
                  whiteSpace: "nowrap",
                }}
              >
                {(linked.source_type === "integration" && getIntegrationLabel(linked.source_path)) || "Built-in"}
              </span>
            )}
          </div>
          <button
            onClick={onUnlink}
            title="Unlink template"
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 3,
              padding: "3px 6px",
              fontSize: 10,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              background: "transparent",
              color: t.textDim,
              cursor: "pointer",
            }}
          >
            <Unlink size={10} />
            Unlink
          </button>
        </>
      ) : (
        <div style={{ position: "relative", display: "inline-block" }}>
          <button
            ref={btnRef}
            onClick={() => setOpen(!open)}
            title="Link a prompt template"
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 4,
              padding: "3px 8px",
              fontSize: 11,
              fontWeight: 600,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              background: open ? t.surfaceOverlay : "transparent",
              color: t.textDim,
              cursor: "pointer",
            }}
          >
            <Link2 size={11} />
            Link Template
          </button>

          {open &&
            typeof document !== "undefined" &&
            (() => {              return createPortal(
                isMobile ? (
                  /* ---- Mobile: full-screen modal ---- */
                  <div
                    style={{
                      position: "fixed",
                      inset: 0,
                      zIndex: 10010,
                      background: t.surface,
                      display: "flex",
                      flexDirection: "column",
                    }}
                  >
                    <div style={{
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      gap: 8,
                      padding: "12px 16px",
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                      flexShrink: 0,
                    }}>
                      <div style={{ flex: 1 }}>{searchBar}</div>
                      <button
                        onClick={close}
                        style={{
                          display: "flex", flexDirection: "row",
                          alignItems: "center",
                          justifyContent: "center",
                          width: 36,
                          height: 36,
                          borderRadius: 8,
                          border: `1px solid ${t.surfaceBorder}`,
                          background: "transparent",
                          color: t.textMuted,
                          cursor: "pointer",
                          flexShrink: 0,
                        }}
                      >
                        <X size={18} />
                      </button>
                    </div>
                    {templateList}
                  </div>
                ) : (
                  /* ---- Desktop: positioned dropdown ---- */
                  <>
                    <div
                      onClick={close}
                      style={{ position: "fixed", inset: 0, zIndex: 10010 }}
                    />
                    <div
                      style={{
                        position: "fixed",
                        top: (btnRef.current?.getBoundingClientRect().bottom ?? 0) + 4,
                        left: btnRef.current?.getBoundingClientRect().left ?? 0,
                        width: 340,
                        maxHeight: 380,
                        zIndex: 10011,
                        background: t.surfaceRaised,
                        border: `1px solid ${t.surfaceBorder}`,
                        borderRadius: 8,
                        boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
                        display: "flex",
                        flexDirection: "column",
                      }}
                    >
                      <div style={{ padding: "8px 10px", borderBottom: `1px solid ${t.surfaceOverlay}` }}>
                        {searchBar}
                      </div>
                      {templateList}
                    </div>
                  </>
                ),
                document.body
              );
            })()}
        </div>
      )}
    </div>
  );
}
