import { useState, useRef, useCallback } from "react";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import { useThemeTokens } from "../../theme/tokens";
import type { PromptTemplate } from "../../types/api";

interface Props {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (v: string) => void;
  workspaceId?: string;
}

export function PromptTemplateSelector({ textareaRef, value, onChange, workspaceId }: Props) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const { data: templates } = usePromptTemplates(workspaceId);

  const insertTemplate = useCallback(
    (template: PromptTemplate) => {
      const ta = textareaRef.current;
      const insertText = template.content;
      if (ta) {
        const start = ta.selectionStart ?? value.length;
        const end = ta.selectionEnd ?? value.length;
        const newValue = value.slice(0, start) + insertText + value.slice(end);
        onChange(newValue);
        // Restore cursor after insert
        requestAnimationFrame(() => {
          ta.focus();
          const pos = start + insertText.length;
          ta.setSelectionRange(pos, pos);
        });
      } else {
        onChange(value + insertText);
      }
      setOpen(false);
      setSearch("");
    },
    [textareaRef, value, onChange]
  );

  if (!templates || templates.length === 0) return null;

  const q = search.toLowerCase();
  const filtered = q
    ? templates.filter(
        (tpl) =>
          tpl.name.toLowerCase().includes(q) ||
          (tpl.category || "").toLowerCase().includes(q) ||
          (tpl.description || "").toLowerCase().includes(q)
      )
    : templates;

  // Group by category
  const grouped = new Map<string, PromptTemplate[]>();
  for (const tpl of filtered) {
    const cat = tpl.category || "Uncategorized";
    if (!grouped.has(cat)) grouped.set(cat, []);
    grouped.get(cat)!.push(tpl);
  }

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        title="Insert prompt template"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "3px 8px",
          fontSize: 11,
          fontWeight: 600,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 4,
          background: open ? t.surfaceRaised : "transparent",
          color: t.textMuted,
          cursor: "pointer",
        }}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="12" y1="18" x2="12" y2="12" />
          <line x1="9" y1="15" x2="15" y2="15" />
        </svg>
        Template
      </button>

      {open && typeof document !== "undefined" &&
        (() => {
          const ReactDOM = require("react-dom");
          return ReactDOM.createPortal(
            <>
              <div
                onClick={() => { setOpen(false); setSearch(""); }}
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
                  boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                {/* Search */}
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
                      border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 4,
                      padding: "5px 8px",
                      fontSize: 12,
                      color: t.text,
                      outline: "none",
                    }}
                  />
                </div>
                {/* List */}
                <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
                  {filtered.length === 0 && (
                    <div style={{ padding: "16px 12px", textAlign: "center", color: t.textDim, fontSize: 12 }}>
                      No templates found
                    </div>
                  )}
                  {Array.from(grouped.entries()).map(([cat, items]) => (
                    <div key={cat}>
                      <div
                        style={{
                          padding: "6px 12px 2px",
                          fontSize: 9,
                          fontWeight: 700,
                          color: t.textDim,
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                        }}
                      >
                        {cat}
                      </div>
                      {items.map((tpl) => (
                        <button
                          key={tpl.id}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            insertTemplate(tpl);
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
                            <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                              {tpl.name}
                            </span>
                            {tpl.workspace_id && (
                              <span
                                style={{
                                  fontSize: 9,
                                  padding: "1px 4px",
                                  borderRadius: 3,
                                  background: "rgba(59,130,246,0.15)",
                                  color: "#93c5fd",
                                }}
                              >
                                workspace
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
                              }}
                            >
                              {tpl.description}
                            </span>
                          )}
                          <span
                            style={{
                              fontSize: 10,
                              color: t.surfaceBorder,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              fontFamily: "monospace",
                            }}
                          >
                            {tpl.content.slice(0, 80)}
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </>,
            document.body
          );
        })()}
    </div>
  );
}
