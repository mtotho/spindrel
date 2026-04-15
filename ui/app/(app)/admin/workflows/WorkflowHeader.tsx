/**
 * Sticky header bar for workflow detail page.
 * Back button, workflow name, source badge, action buttons.
 */

import { type ThemeTokens } from "@/src/theme/tokens";
import {
  ArrowLeft, Save, Trash2, Download, Copy, Unlink,
} from "lucide-react";

interface WorkflowHeaderProps {
  name: string;
  isNew: boolean;
  dirty: boolean;
  isFileBased: boolean;
  sourceType?: string;
  sourcePath?: string | null;
  /** True when gallery/import is showing (hide save) */
  showingPicker: boolean;
  onBack: () => void;
  onSave: () => void;
  onDelete: () => void;
  onClone: () => void;
  onExport: () => void;
  saving: boolean;
  t: ThemeTokens;
}

export function WorkflowHeader({
  name, isNew, dirty, isFileBased, sourceType, sourcePath,
  showingPicker, onBack, onSave, onDelete, onClone, onExport, saving, t,
}: WorkflowHeaderProps) {
  return (
    <div style={{
      position: "sticky", top: 0, zIndex: 10,
      background: t.surface,
      borderBottom: `1px solid ${t.surfaceBorder}`,
      padding: "10px 16px",
    }}>
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
        maxWidth: 1200,
      }}>
        {/* Left: back + name */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
          <button type="button"
            onClick={onBack}
            style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
          >
            <ArrowLeft size={16} color={t.textMuted} />
            <span style={{ color: t.textMuted, fontSize: 12 }}>Workflows</span>
          </button>
          <span style={{
            fontSize: 15, fontWeight: 700, color: t.text,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {name || (isNew ? "New Workflow" : "Workflow")}
          </span>

          {/* Source badge */}
          {isFileBased && (
            <span style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 10, padding: "2px 7px", borderRadius: 4,
              background: t.accentSubtle, border: `1px solid ${t.accentBorder}`, color: t.accent,
            }}>
              <Unlink size={10} />
              {sourceType}
            </span>
          )}

          {/* Dirty dot */}
          {dirty && !isNew && (
            <span style={{
              width: 7, height: 7, borderRadius: 4,
              background: t.warning, flexShrink: 0,
            }}
            title="Unsaved changes"
            />
          )}
        </div>

        {/* Right: action buttons */}
        <div style={{ display: "flex", flexDirection: "row", gap: 6, alignItems: "center", flexShrink: 0 }}>
          {!isNew && (
            <HeaderButton onClick={onClone} t={t} subtle>
              <Copy size={13} color={t.textMuted} />
              <span>Clone</span>
            </HeaderButton>
          )}
          {!isNew && (
            <HeaderButton onClick={onExport} t={t} subtle>
              <Download size={13} color={t.textMuted} />
              <span>Export</span>
            </HeaderButton>
          )}
          {!isNew && (
            <HeaderButton onClick={onDelete} t={t} danger>
              <Trash2 size={13} color={t.danger} />
            </HeaderButton>
          )}
          {!showingPicker && (
            <button type="button"
              onClick={onSave}
              disabled={(!dirty && !isNew) || saving}
              style={{
                flexDirection: "row", alignItems: "center", gap: 4,
                paddingInline: 14, paddingBlock: 6, borderRadius: 6,
                backgroundColor: dirty || isNew ? t.accent : t.surfaceBorder,
                opacity: (dirty || isNew) && !saving ? 1 : 0.5,
              }}
            >
              <Save size={13} color="#fff" />
              <span style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
                {saving ? "Saving..." : isNew ? "Create" : isFileBased && dirty ? "Detach & Save" : "Save"}
              </span>
            </button>
          )}
        </div>
      </div>

      {/* File-managed info banner */}
      {isFileBased && !isNew && (
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          marginTop: 8, padding: "6px 10px", borderRadius: 6,
          background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
          fontSize: 11, color: t.accent,
        }}>
          <Unlink size={12} color={t.accent} />
          <span>
            Sourced from {sourceType}{sourcePath ? ` (${sourcePath})` : ""}.
            Saving will detach and make this user-managed.
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small header button
// ---------------------------------------------------------------------------

function HeaderButton({ onClick, children, t, subtle, danger }: {
  onClick: () => void;
  children: React.ReactNode;
  t: ThemeTokens;
  subtle?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
        padding: "5px 10px", borderRadius: 6, border: "none",
        background: danger ? t.dangerSubtle : t.codeBg,
        color: danger ? t.danger : t.textMuted,
        fontSize: 11, cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
