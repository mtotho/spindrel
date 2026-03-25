import { useState, useRef, useCallback, useEffect } from "react";
import { useModelGroups } from "../../api/hooks/useModels";

interface Props {
  value: string;
  onChange: (modelId: string) => void;
  placeholder?: string;
  label?: string;
  allowClear?: boolean;
  /** Where to anchor the dropdown relative to the trigger. Default "bottom". */
  anchor?: "bottom" | "top";
}

/**
 * Model picker dropdown that renders into a portal (document.body)
 * to avoid any z-index / overflow clipping from parent ScrollViews.
 */
export function LlmModelDropdown({
  value,
  onChange,
  placeholder = "Select model...",
  label,
  allowClear = true,
  anchor = "bottom",
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [pos, setPos] = useState({ top: 0, left: 0, bottom: 0, width: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const { data: groups, isLoading } = useModelGroups();

  // Measure trigger position for portal dropdown
  const openDropdown = useCallback(() => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({
        top: rect.bottom + 4,
        left: rect.left,
        bottom: window.innerHeight - rect.top + 4,
        width: rect.width,
      });
    }
    setOpen(true);
    setSearch("");
  }, [anchor]);

  const filteredGroups = groups
    ?.map((g) => ({
      ...g,
      models: g.models.filter(
        (m) =>
          !search ||
          m.id.toLowerCase().includes(search.toLowerCase()) ||
          m.display.toLowerCase().includes(search.toLowerCase())
      ),
    }))
    .filter((g) => g.models.length > 0);

  return (
    <div style={{ position: "relative" }}>
      {label && (
        <div style={{ color: "#666", fontSize: 12, marginBottom: 4 }}>{label}</div>
      )}

      {/* Trigger button */}
      <div
        ref={triggerRef}
        onClick={openDropdown}
        style={{
          display: "flex",
          alignItems: "center",
          background: "#111",
          border: "1px solid #333",
          borderRadius: 8,
          padding: "7px 12px",
          cursor: "pointer",
          gap: 8,
        }}
      >
        <span style={{ flex: 1, fontSize: 13, color: value ? "#e5e5e5" : "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {value || placeholder}
        </span>
        {allowClear && value ? (
          <span
            onClick={(e) => { e.stopPropagation(); onChange(""); }}
            style={{ color: "#999", cursor: "pointer", fontSize: 14, lineHeight: 1 }}
          >
            ✕
          </span>
        ) : (
          <span style={{ color: "#666", fontSize: 10 }}>▾</span>
        )}
      </div>

      {/* Portal dropdown — rendered into document.body */}
      {open && typeof document !== "undefined" &&
        (() => {
          const ReactDOM = require("react-dom");
          return ReactDOM.createPortal(
            <>
              {/* Backdrop */}
              <div
                onClick={() => setOpen(false)}
                style={{ position: "fixed", inset: 0, zIndex: 50000 }}
              />
              {/* Dropdown panel */}
              <div
                style={{
                  position: "fixed",
                  ...(anchor === "top"
                    ? { bottom: pos.bottom, left: pos.left }
                    : { top: pos.top, left: pos.left }),
                  width: Math.max(pos.width, 320),
                  maxHeight: 340,
                  zIndex: 50001,
                  background: "#1a1a1a",
                  border: "1px solid #333",
                  borderRadius: 10,
                  boxShadow: "0 12px 40px rgba(0,0,0,0.5)",
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                }}
              >
                {/* Search */}
                <div style={{ padding: "10px 12px", borderBottom: "1px solid #333" }}>
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search models..."
                    autoFocus
                    style={{
                      width: "100%",
                      background: "#111",
                      border: "1px solid #444",
                      borderRadius: 6,
                      padding: "6px 10px",
                      color: "#e5e5e5",
                      fontSize: 13,
                      outline: "none",
                    }}
                    onFocus={(e) => { (e.target as HTMLInputElement).style.borderColor = "#3b82f6"; }}
                    onBlur={(e) => { (e.target as HTMLInputElement).style.borderColor = "#444"; }}
                  />
                </div>

                {/* Model list */}
                <div style={{ flex: 1, overflowY: "auto" }}>
                  {isLoading ? (
                    <div style={{ padding: 16, color: "#666", fontSize: 13 }}>Loading models...</div>
                  ) : filteredGroups?.length === 0 ? (
                    <div style={{ padding: 16, color: "#666", fontSize: 13, textAlign: "center" }}>No models found</div>
                  ) : (
                    filteredGroups?.map((group) => (
                      <div key={group.provider_name}>
                        <div style={{
                          padding: "6px 12px",
                          background: "#222",
                          fontSize: 10,
                          fontWeight: 600,
                          color: "#666",
                          letterSpacing: "0.05em",
                          textTransform: "uppercase",
                          position: "sticky",
                          top: 0,
                        }}>
                          {group.provider_name}
                        </div>
                        {group.models.map((model) => (
                          <div
                            key={model.id}
                            onClick={() => {
                              onChange(model.id);
                              setOpen(false);
                            }}
                            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#2a2a2a"; }}
                            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = model.id === value ? "rgba(59,130,246,0.08)" : "transparent"; }}
                            style={{
                              padding: "8px 12px",
                              cursor: "pointer",
                              background: model.id === value ? "rgba(59,130,246,0.08)" : "transparent",
                            }}
                          >
                            <div style={{ fontSize: 13, color: model.id === value ? "#3b82f6" : "#e5e5e5" }}>
                              {model.id}
                            </div>
                            {model.display !== model.id && (
                              <div style={{ fontSize: 11, color: "#666", marginTop: 1 }}>
                                {model.display}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </>,
            document.body
          );
        })()
      }
    </div>
  );
}
