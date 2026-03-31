import { useState, useRef } from "react";
import { Link2, Unlink, Pencil } from "lucide-react";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import { useThemeTokens } from "../../theme/tokens";

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
  const t = useThemeTokens();

  const linked = templates?.find((tpl) => tpl.id === templateId);

  const q = search.toLowerCase();
  const filtered = templates
    ? q
      ? templates.filter(
          (tpl) =>
            tpl.name.toLowerCase().includes(q) ||
            (tpl.category || "").toLowerCase().includes(q) ||
            (tpl.description || "").toLowerCase().includes(q)
        )
      : templates
    : [];

  // Only show manual templates (not workspace_file sourced)
  const manual = filtered.filter((tpl) => tpl.source_type !== "workspace_file");

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
      {linked ? (
        <>
          <div
            style={{
              display: "inline-flex",
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
                Built-in
              </span>
            )}
          </div>
          <button
            onClick={onUnlink}
            title="Unlink template"
            style={{
              display: "inline-flex",
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
              display: "inline-flex",
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
            (() => {
              const ReactDOM = require("react-dom");
              return ReactDOM.createPortal(
                <>
                  <div
                    onClick={() => {
                      setOpen(false);
                      setSearch("");
                    }}
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
                          borderRadius: 4,
                          padding: "5px 8px",
                          fontSize: 12,
                          color: t.inputText,
                          outline: "none",
                        }}
                      />
                    </div>
                    <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
                      {manual.length === 0 && (
                        <div
                          style={{
                            padding: "16px 12px",
                            textAlign: "center",
                            color: t.textDim,
                            fontSize: 12,
                          }}
                        >
                          No templates found
                        </div>
                      )}
                      {manual.map((tpl) => (
                        <button
                          key={tpl.id}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            onLink(tpl.id);
                            setOpen(false);
                            setSearch("");
                          }}
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 2,
                            width: "100%",
                            padding: "6px 12px",
                            background: "transparent",
                            border: "none",
                            cursor: "pointer",
                            textAlign: "left",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = t.surfaceOverlay)}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <Pencil size={11} color={t.accent} />
                            <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
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
                                Built-in
                              </span>
                            )}
                          </div>
                          {tpl.description && (
                            <span
                              style={{
                                fontSize: 11,
                                color: t.textDim,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                paddingLeft: 17,
                              }}
                            >
                              {tpl.description}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                </>,
                document.body
              );
            })()}
        </div>
      )}
    </div>
  );
}
