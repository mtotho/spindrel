/**
 * Rich workflow selector with search, grouping by source, and metadata display.
 * Used in HeartbeatTab for selecting a workflow to trigger on heartbeat intervals.
 */
import { useState, useRef, useMemo } from "react";
import { useThemeTokens, type ThemeTokens } from "../../theme/tokens";
import { useWorkflows } from "../../api/hooks/useWorkflows";
import { Search, ChevronDown, Zap, X } from "lucide-react";
import type { Workflow } from "../../types/api";

interface Props {
  value: string | null;
  onChange: (workflowId: string | null) => void;
}

export function WorkflowSelector({ value, onChange }: Props) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);
  const { data: workflows } = useWorkflows();

  const selected = useMemo(
    () => workflows?.find((w) => w.id === value) ?? null,
    [workflows, value],
  );

  const filtered = useMemo(() => {
    if (!workflows) return [];
    const q = search.toLowerCase();
    if (!q) return workflows;
    return workflows.filter(
      (w) =>
        w.id.toLowerCase().includes(q) ||
        w.name.toLowerCase().includes(q) ||
        (w.description || "").toLowerCase().includes(q) ||
        w.tags.some((tag) => tag.toLowerCase().includes(q)),
    );
  }, [workflows, search]);

  // Group by source_type
  const groups = useMemo(() => {
    const result: { key: string; label: string; items: Workflow[] }[] = [];
    const manual: Workflow[] = [];
    const file: Workflow[] = [];
    const integration: Workflow[] = [];

    for (const w of filtered) {
      if (w.source_type === "integration") integration.push(w);
      else if (w.source_type === "file") file.push(w);
      else manual.push(w);
    }

    if (manual.length) result.push({ key: "manual", label: "User Created", items: manual });
    if (file.length) result.push({ key: "file", label: "File-Managed", items: file });
    if (integration.length) result.push({ key: "integration", label: "Integration", items: integration });

    return result;
  }, [filtered]);

  if (!workflows || workflows.length === 0) {
    return (
      <div style={{
        padding: "16px 12px", borderRadius: 6, textAlign: "center",
        background: t.codeBg, border: `1px solid ${t.codeBorder}`,
      }}>
        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 4 }}>
          No workflows available
        </div>
        <div style={{ fontSize: 11, color: t.textDim }}>
          Create a workflow in Admin &rarr; Workflows first.
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "relative" }}>
      {/* Trigger button */}
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          width: "100%", padding: "8px 12px",
          background: t.inputBg, border: `1px solid ${t.inputBorder}`,
          borderRadius: 8, cursor: "pointer", textAlign: "left",
        }}
      >
        <Zap size={14} color={selected ? t.accent : t.textDim} />
        <div style={{ flex: 1, minWidth: 0 }}>
          {selected ? (
            <div>
              <span style={{ fontSize: 13, color: t.inputText, fontWeight: 500 }}>
                {selected.name || selected.id}
              </span>
              {selected.source_type !== "manual" && (
                <span style={{
                  marginLeft: 6, fontSize: 10, padding: "1px 5px", borderRadius: 3,
                  background: t.accentSubtle, border: `1px solid ${t.accentBorder}`, color: t.accent,
                }}>
                  {selected.source_type}
                </span>
              )}
            </div>
          ) : (
            <span style={{ fontSize: 13, color: t.textDim }}>Select a workflow...</span>
          )}
        </div>
        {value ? (
          <span
            onClick={(e) => { e.stopPropagation(); onChange(null); setOpen(false); }}
            style={{ padding: 2, cursor: "pointer", display: "flex" }}
          >
            <X size={14} color={t.textDim} />
          </span>
        ) : (
          <ChevronDown size={14} color={t.textDim} />
        )}
      </button>

      {/* Popover via portal */}
      {open && typeof document !== "undefined" &&
        (() => {
          const ReactDOM = require("react-dom");
          const rect = btnRef.current?.getBoundingClientRect();
          return ReactDOM.createPortal(
            <>
              <div
                onClick={() => { setOpen(false); setSearch(""); }}
                style={{ position: "fixed", inset: 0, zIndex: 10010 }}
              />
              <div
                style={{
                  position: "fixed",
                  top: (rect?.bottom ?? 0) + 4,
                  left: rect?.left ?? 0,
                  width: Math.max(rect?.width ?? 340, 340),
                  maxHeight: 420,
                  zIndex: 10011,
                  background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 10,
                  boxShadow: `0 8px 32px ${t.overlayLight}`,
                  display: "flex", flexDirection: "column",
                  overflow: "hidden",
                }}
              >
                {/* Search */}
                <div style={{
                  padding: "8px 10px",
                  borderBottom: `1px solid ${t.surfaceBorder}`,
                }}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 6,
                    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
                    borderRadius: 6, padding: "5px 8px",
                  }}>
                    <Search size={13} color={t.textDim} />
                    <input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search workflows..."
                      autoFocus
                      style={{
                        flex: 1, width: "100%", background: "none", border: "none",
                        outline: "none", color: t.text, fontSize: 12,
                      }}
                    />
                  </div>
                </div>

                {/* List */}
                <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
                  {filtered.length === 0 && (
                    <div style={{
                      padding: "20px 12px", textAlign: "center",
                      color: t.textDim, fontSize: 12,
                    }}>
                      No workflows match &ldquo;{search}&rdquo;
                    </div>
                  )}
                  {groups.map((group) => (
                    <div key={group.key}>
                      <div style={{
                        padding: "8px 12px 3px",
                        fontSize: 9, fontWeight: 700, color: t.textDim,
                        textTransform: "uppercase", letterSpacing: "0.06em",
                      }}>
                        {group.label}
                        <span style={{ marginLeft: 4, fontWeight: 500 }}>{group.items.length}</span>
                      </div>
                      {group.items.map((wf) => (
                        <WorkflowItem
                          key={wf.id}
                          workflow={wf}
                          isSelected={wf.id === value}
                          t={t}
                          onSelect={() => {
                            onChange(wf.id);
                            setOpen(false);
                            setSearch("");
                          }}
                        />
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </>,
            document.body,
          );
        })()}
    </div>
  );
}

function WorkflowItem({ workflow: wf, isSelected, t, onSelect }: {
  workflow: Workflow; isSelected: boolean; t: ThemeTokens; onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      style={{
        display: "flex", flexDirection: "column", gap: 2,
        width: "100%", padding: "7px 12px",
        background: isSelected ? t.accentSubtle : "transparent",
        border: "none", cursor: "pointer", textAlign: "left",
      }}
      onMouseEnter={(e) => {
        if (!isSelected) e.currentTarget.style.background = t.overlayLight;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = isSelected ? t.accentSubtle : "transparent";
      }}
    >
      {/* Name row */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Zap size={12} color={isSelected ? t.accent : t.textMuted} />
        <span style={{
          fontSize: 12, fontWeight: 600,
          color: isSelected ? t.accent : t.text,
        }}>
          {wf.name || wf.id}
        </span>
        {wf.source_type !== "manual" && (
          <span style={{
            fontSize: 9, padding: "1px 4px", borderRadius: 3,
            background: t.accentSubtle, color: t.accent,
          }}>
            {wf.source_type}
          </span>
        )}
      </div>
      {/* Description */}
      {wf.description && (
        <span style={{
          fontSize: 11, color: t.textDim, paddingLeft: 18,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {wf.description}
        </span>
      )}
      {/* Meta row: steps + tags */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6, paddingLeft: 18,
      }}>
        <span style={{ fontSize: 10, color: t.textDim }}>
          {wf.steps?.length ?? 0} step{(wf.steps?.length ?? 0) !== 1 ? "s" : ""}
        </span>
        {wf.tags?.length > 0 && wf.tags.map((tag) => (
          <span key={tag} style={{
            fontSize: 9, padding: "0 4px", borderRadius: 3,
            background: t.purpleSubtle, border: `1px solid ${t.purpleBorder}`, color: t.purple,
          }}>
            {tag}
          </span>
        ))}
      </div>
    </button>
  );
}
