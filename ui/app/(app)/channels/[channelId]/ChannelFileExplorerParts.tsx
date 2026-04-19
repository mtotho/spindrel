/**
 * Visual subcomponents for the OmniPanel Files tab (FilesTabPanel).
 * Shared row primitives (ScopeStrip, Breadcrumb, TreeFolderRow, TreeFileRow,
 * NewItemRow) plus the DRAG_MIME / stripSlashes helpers.
 */
import { useState } from "react";
import { ChevronRight, Folder, Plus, Trash2 } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  formatRelativeTime,
  formatSize,
  getFileIcon,
  getArchiveIcon,
} from "./ChannelFileExplorerData";

// ---------------------------------------------------------------------------
// Path helper used by multiple components
// ---------------------------------------------------------------------------

export function stripSlashes(p: string): string {
  return p.replace(/^\/+/, "").replace(/\/+$/, "");
}

// Custom DataTransfer mime used to mark in-app file drags. The OS-file upload
// path checks `dataTransfer.types.includes("Files")`, so this lets us route
// in-app moves and OS uploads through the same drop targets without collision.
export const DRAG_MIME = "application/x-spindrel-move-path";

// ---------------------------------------------------------------------------
// Breadcrumb -- clickable path segments
// ---------------------------------------------------------------------------

// (InContextCard + ActiveFileRow — removed. The token gauge now lives inline
// on the FilesTabPanel action row; active-file ops are accessible via the
// shared tree row context menu.)


/** Scope targets for the breadcrumb scope chips. */
export interface ScopeTarget {
  label: string;
  path: string;
}

export function ScopeStrip({
  currentPath, scopeTargets, onJump,
}: {
  currentPath: string; scopeTargets: ScopeTarget[]; onJump: (path: string) => void;
}) {
  const t = useThemeTokens();
  if (scopeTargets.length === 0) return null;

  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center",
      gap: 6, padding: "4px 10px", flexShrink: 0,
    }}>
      {scopeTargets.map((c, i) => {
        const active = currentPath === c.path || (c.path !== "/" && currentPath.startsWith(c.path + "/"));
        return (
          <span key={c.label} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
            {i > 0 && <span style={{ color: t.surfaceBorder, fontSize: 10 }}>·</span>}
            <button type="button" onClick={() => onJump(c.path)}
              style={{
                padding: 0, cursor: "pointer", background: "none", border: "none",
                color: active ? t.text : t.textDim,
                fontSize: 11, fontWeight: active ? 600 : 400,
              }}
              onMouseEnter={(e) => { if (!active) e.currentTarget.style.color = t.textMuted; }}
              onMouseLeave={(e) => { if (!active) e.currentTarget.style.color = active ? t.text : t.textDim; }}
            >
              {c.label}
            </button>
          </span>
        );
      })}
    </div>
  );
}

export function Breadcrumb({
  path, channelId, channelDisplayName, channelNameMap, onNavigate,
}: {
  path: string; channelId: string; channelDisplayName: string | null | undefined;
  channelNameMap?: Record<string, string> | null; onNavigate: (p: string) => void;
}) {
  const t = useThemeTokens();
  const segments = path === "/" ? [] : stripSlashes(path).split("/");
  const labelFor = (seg: string, i: number) => {
    if (i > 0 && segments[i - 1] === "channels") {
      const mapped = channelNameMap?.[seg];
      if (mapped) return mapped;
      if (seg === channelId && channelDisplayName) return channelDisplayName;
    }
    return seg;
  };

  // Collapse middle breadcrumb segments when path is deep (>3 segments)
  const MAX_VISIBLE = 3;
  const collapsed = segments.length > MAX_VISIBLE;
  const visibleSegments = collapsed
    ? [segments[0], null, ...segments.slice(-2)] // null = ellipsis placeholder
    : segments;
  const realIndex = (vi: number): number => {
    if (!collapsed) return vi;
    if (vi === 0) return 0;
    if (vi === 1) return -1; // ellipsis
    return segments.length - (visibleSegments.length - vi);
  };

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", padding: "3px 10px", flexWrap: "nowrap", minHeight: 20, overflow: "hidden", flexShrink: 0, lineHeight: "16px" }}>
      <button type="button" onClick={() => onNavigate("/")}
        style={{ cursor: "pointer", opacity: 0.85, background: "none", border: "none", padding: 0, flexShrink: 0, lineHeight: "inherit" }}
        onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
        onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.85"; }}
      >
        <span style={{ color: path === "/" ? t.text : t.accent, fontSize: 10.5, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>
          /ws
        </span>
      </button>
      {visibleSegments.map((seg, vi) => {
        if (seg === null) {
          return (
            <span key="ellipsis">
              <span style={{ color: t.textDim, fontSize: 10.5, margin: "0 3px" }}>&rsaquo;</span>
              <span style={{ color: t.textDim, fontSize: 10.5, cursor: "default" }}>…</span>
            </span>
          );
        }
        const ri = realIndex(vi);
        const segPath = "/" + segments.slice(0, ri + 1).join("/");
        const isLast = ri === segments.length - 1;
        const label = labelFor(seg, ri);
        return (
          <span key={segPath} style={{ display: "inline-flex", alignItems: "baseline", minWidth: 0 }}>
            <span style={{ color: t.textDim, fontSize: 10.5, margin: "0 3px", flexShrink: 0 }}>&rsaquo;</span>
            <button type="button" onClick={() => !isLast && onNavigate(segPath)}
              style={{ cursor: isLast ? "default" : "pointer", opacity: 0.85, minWidth: 0, background: "none", border: "none", padding: 0, lineHeight: "inherit" }}
              onMouseEnter={(e) => { if (!isLast) e.currentTarget.style.opacity = "1"; }}
              onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.85"; }}
            >
              <span style={{
                color: isLast ? t.text : t.accent, fontSize: 10.5,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block",
              }}>
                {label}
              </span>
            </button>
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tree row -- folder or file in current directory
// ---------------------------------------------------------------------------

export function TreeFolderRow({
  name, displayLabel, fullPath, onNavigate, onContextMenu, onMoveDrop, focused, multiSelected,
}: {
  name: string; displayLabel?: string | null; fullPath: string;
  onNavigate: (p: string, e?: React.MouseEvent) => void; onContextMenu?: (e: any) => void;
  onMoveDrop?: (sourcePath: string) => void; focused?: boolean; multiSelected?: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const label = displayLabel || name;

  const dropProps = onMoveDrop ? {
    onDragOver: (e: any) => {
      if (e.dataTransfer?.types?.includes(DRAG_MIME)) {
        e.preventDefault(); e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        if (!dragOver) setDragOver(true);
      }
    },
    onDragLeave: (e: any) => {
      const next = e.relatedTarget as Node | null;
      if (next && e.currentTarget.contains(next)) return;
      setDragOver(false);
    },
    onDrop: (e: any) => {
      const src = e.dataTransfer?.getData(DRAG_MIME);
      if (!src) return;
      e.preventDefault(); e.stopPropagation();
      setDragOver(false);
      onMoveDrop(src);
    },
  } : {};

  return (
    <button type="button" onClick={(e) => onNavigate(fullPath, e)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: 12, paddingRight: 8, gap: 6, width: "100%",
        background: multiSelected ? t.accentSubtle : dragOver ? `${t.accent}25` : hovered || focused ? `${t.text}08` : "transparent",
        outline: dragOver ? `1px solid ${t.accent}` : focused ? `1px dotted ${t.textDim}` : "none",
        outlineOffset: -1, cursor: "pointer", border: "none",
      }}
      {...(onContextMenu ? { onContextMenu } : {})}
      {...(displayLabel ? { title: name } : {})}
      {...dropProps}
    >
      <Folder size={13} color={dragOver ? t.accent : "#dcb67a"} />
      <span style={{
        flex: 1, color: t.text, fontSize: 12, lineHeight: "22px", minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "left",
      }}>
        {label}
      </span>
      <ChevronRight size={11} color={t.textDim} />
    </button>
  );
}

export function TreeFileRow({
  name, fullPath, size, modifiedAt, selected, focused, multiSelected, onSelect, onContextMenu, onDelete, draggable = true,
}: {
  name: string; fullPath: string; size: number | null | undefined;
  modifiedAt: number | null | undefined; selected: boolean; focused?: boolean;
  multiSelected?: boolean;
  onSelect: (e?: React.MouseEvent) => void; onContextMenu?: (e: any) => void; onDelete: () => void;
  draggable?: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const icon = name === "MEMORY.md" || fullPath.endsWith("/archive")
    ? getArchiveIcon(t.textDim) : getFileIcon(name, null, t.textDim);
  const sizeStr = formatSize(size);
  const modified = formatRelativeTime(modifiedAt);

  const dragProps = draggable ? {
    draggable: true,
    onDragStart: (e: any) => {
      try { e.dataTransfer.setData(DRAG_MIME, fullPath); e.dataTransfer.effectAllowed = "move"; } catch {}
      setDragging(true);
    },
    onDragEnd: () => setDragging(false),
  } : {};

  return (
    <button type="button" onClick={(e) => onSelect(e)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: 12, paddingRight: 8, gap: 6, width: "100%",
        background: multiSelected ? t.accentSubtle : selected ? t.accentSubtle : hovered || focused ? `${t.text}08` : "transparent",
        outline: focused && !selected ? `1px dotted ${t.textDim}` : "none",
        outlineOffset: -1, cursor: dragging ? "grabbing" : "pointer",
        opacity: dragging ? 0.5 : 1, border: "none",
      }}
      {...(onContextMenu ? { onContextMenu } : {})}
      {...dragProps}
    >
      {icon}
      <span style={{
        flex: 1, color: t.text, fontSize: 12, lineHeight: "22px", minWidth: 0,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "left",
      }}>
        {name}
      </span>
      {hovered ? (
        <button type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          style={{ padding: 2, opacity: 0.7, background: "none", border: "none", cursor: "pointer" }}
          title="Delete"
        >
          <Trash2 size={11} color={t.textMuted} />
        </button>
      ) : (
        <span style={{ color: t.textDim, fontSize: 9, flexShrink: 0 }}>
          {modified || sizeStr}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Inline new-item row (file or folder)
// ---------------------------------------------------------------------------

export function NewItemRow({
  kind, onSubmit, onCancel,
}: {
  kind: "file" | "folder"; onSubmit: (name: string) => void; onCancel: () => void;
}) {
  const t = useThemeTokens();
  const [name, setName] = useState("");

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", height: 24, paddingLeft: 12, paddingRight: 8, gap: 6 }}>
      {kind === "folder" ? <Folder size={13} color="#dcb67a" /> : <Plus size={13} color={t.accent} />}
      <input
        autoFocus value={name}
        onChange={(e: any) => setName(e.target.value)}
        onKeyDown={(e: any) => {
          if (e.key === "Enter" && name.trim()) onSubmit(name.trim());
          if (e.key === "Escape") onCancel();
        }}
        onBlur={() => { if (!name.trim()) onCancel(); else onSubmit(name.trim()); }}
        placeholder={kind === "folder" ? "folder-name" : "filename.md"}
        style={{
          flex: 1, background: t.inputBg, border: `1px solid ${t.accent}`, borderRadius: 3,
          padding: "0px 6px", fontSize: 12, color: t.text, outline: "none", height: 20,
          fontFamily: "inherit", minWidth: 0,
        }}
      />
    </div>
  );
}
