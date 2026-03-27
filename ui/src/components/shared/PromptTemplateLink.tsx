import { useState, useRef } from "react";
import { Link2, Unlink, Pencil } from "lucide-react";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import type { PromptTemplate } from "../../types/api";

interface Props {
  templateId: string | null | undefined;
  onLink: (id: string) => void;
  onUnlink: () => void;
}

export function PromptTemplateLink({ templateId, onLink, onUnlink }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const { data: templates } = usePromptTemplates();

  const linked = templates?.find((t) => t.id === templateId);

  const q = search.toLowerCase();
  const filtered = templates
    ? q
      ? templates.filter(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            (t.category || "").toLowerCase().includes(q) ||
            (t.description || "").toLowerCase().includes(q)
        )
      : templates
    : [];

  // Only show manual templates (not workspace_file sourced)
  const manual = filtered.filter((t) => t.source_type !== "workspace_file");

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
              background: "rgba(59,130,246,0.1)",
              border: "1px solid rgba(59,130,246,0.25)",
              color: "#93c5fd",
            }}
          >
            <Pencil size={11} />
            {linked.name}
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
              border: "1px solid #333",
              borderRadius: 4,
              background: "transparent",
              color: "#888",
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
              border: "1px solid #333",
              borderRadius: 4,
              background: open ? "#1a1a1a" : "transparent",
              color: "#888",
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
                      background: "#1a1a1a",
                      border: "1px solid #333",
                      borderRadius: 8,
                      boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                      display: "flex",
                      flexDirection: "column",
                    }}
                  >
                    <div style={{ padding: "8px 10px", borderBottom: "1px solid #2a2a2a" }}>
                      <input
                        type="text"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search templates..."
                        autoFocus
                        style={{
                          width: "100%",
                          background: "#111",
                          border: "1px solid #333",
                          borderRadius: 4,
                          padding: "5px 8px",
                          fontSize: 12,
                          color: "#e5e5e5",
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
                            color: "#555",
                            fontSize: 12,
                          }}
                        >
                          No templates found
                        </div>
                      )}
                      {manual.map((t) => (
                        <button
                          key={t.id}
                          onMouseDown={(e) => {
                            e.preventDefault();
                            onLink(t.id);
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
                          onMouseEnter={(e) => (e.currentTarget.style.background = "#2a2a2a")}
                          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <Pencil size={11} color="#93c5fd" />
                            <span style={{ fontSize: 12, fontWeight: 600, color: "#e5e5e5" }}>
                              {t.name}
                            </span>
                          </div>
                          {t.description && (
                            <span
                              style={{
                                fontSize: 11,
                                color: "#666",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                paddingLeft: 17,
                              }}
                            >
                              {t.description}
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
