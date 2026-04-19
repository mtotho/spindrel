/**
 * Visual subcomponents for the OmniPanel Files tab (FilesTabPanel).
 * Shared row primitives (ScopeStrip, Breadcrumb, TreeFolderRow, TreeFileRow,
 * NewItemRow) plus the DRAG_MIME / stripSlashes helpers.
 */
import { useState } from "react";
import { BookOpen, ChevronDown, ChevronRight, Folder, FolderOpen, Plus, Trash2 } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWorkspaceFiles } from "@/src/api/hooks/useWorkspaces";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import {
  formatRelativeTime,
  formatSize,
  getFileIcon,
  getArchiveIcon,
} from "./ChannelFileExplorerData";

// ---------------------------------------------------------------------------
// Knowledge-base detection — the auto-indexed convention folder gets a
// first-class visual treatment everywhere in the tree (icon, label, tint).
// ---------------------------------------------------------------------------
export function isKnowledgeBaseFolder(name: string, fullPath: string): boolean {
  if (name === "knowledge-base") return true;
  return fullPath.endsWith("/knowledge-base") || fullPath === "/knowledge-base";
}

const INDENT_PX = 14;
/** Folder yellow used across the explorer. Kept hardcoded so it stays
 *  identical in light + dark; the rest of the row honors theme tokens. */
const FOLDER_YELLOW = "#dcb67a";

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
  name, displayLabel, fullPath, expanded, depth = 0, onToggle, onContextMenu, onMoveDrop, focused, multiSelected,
}: {
  name: string; displayLabel?: string | null; fullPath: string;
  expanded: boolean; depth?: number;
  onToggle: (p: string, e?: React.MouseEvent) => void; onContextMenu?: (e: any) => void;
  onMoveDrop?: (sourcePath: string) => void; focused?: boolean; multiSelected?: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const isKB = isKnowledgeBaseFolder(name, fullPath);
  // Use the proper "Knowledge Base" label for KB; the literal slug lives in
  // the title attribute for power users who want to copy the real name.
  const label = isKB ? "Knowledge Base" : (displayLabel || name);

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

  // Background priority: drag-over > multi-select > KB tint > hover/focus.
  const bg = dragOver
    ? `${t.accent}25`
    : multiSelected
      ? t.accentSubtle
      : isKB
        ? `${t.accent}12`
        : (hovered || focused)
          ? `${t.text}08`
          : "transparent";

  const FolderIcon = isKB ? BookOpen : (expanded ? FolderOpen : Folder);
  const folderColor = isKB ? t.accent : (dragOver ? t.accent : FOLDER_YELLOW);

  return (
    <button type="button" onClick={(e) => onToggle(fullPath, e)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: depth * INDENT_PX + 6, paddingRight: 8, gap: 4, width: "100%",
        background: bg,
        outline: dragOver ? `1px solid ${t.accent}` : focused ? `1px dotted ${t.textDim}` : "none",
        outlineOffset: -1, cursor: "pointer", border: "none",
      }}
      {...(onContextMenu ? { onContextMenu } : {})}
      title={isKB ? `${name} — auto-indexed knowledge base` : (displayLabel ? name : undefined)}
      {...dropProps}
    >
      {expanded ? <ChevronDown size={11} color={t.textDim} /> : <ChevronRight size={11} color={t.textDim} />}
      <FolderIcon size={13} color={folderColor} />
      <span style={{
        flex: 1, color: isKB ? t.text : t.text, fontSize: 12, lineHeight: "22px", minWidth: 0,
        fontWeight: isKB ? 600 : 400,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "left",
      }}>
        {label}
      </span>
      {isKB && (
        <span style={{
          fontSize: 8.5, color: t.accent, opacity: 0.85,
          textTransform: "uppercase", letterSpacing: "0.06em",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          flexShrink: 0,
        }}>
          auto
        </span>
      )}
    </button>
  );
}

export function TreeFileRow({
  name, fullPath, size, modifiedAt, selected, focused, multiSelected, depth = 0, onSelect, onContextMenu, onDelete, draggable = true,
}: {
  name: string; fullPath: string; size: number | null | undefined;
  modifiedAt: number | null | undefined; selected: boolean; focused?: boolean;
  multiSelected?: boolean; depth?: number;
  onSelect: (e?: React.MouseEvent) => void; onContextMenu?: (e: any) => void; onDelete: () => void;
  draggable?: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const icon = name === "MEMORY.md" || fullPath.endsWith("/archive")
    ? getArchiveIcon(t.textMuted) : getFileIcon(name, null, t.textMuted);
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

  // Selected gets an inset accent left bar (2px) on top of the subtle bg.
  const bg = multiSelected || selected
    ? t.accentSubtle
    : (hovered || focused) ? `${t.text}06` : "transparent";

  return (
    <button type="button" onClick={(e) => onSelect(e)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        position: "relative",
        height: 22, paddingLeft: depth * INDENT_PX + 6 + 11 + 4 /* chevron-slot + gap */, paddingRight: 8, gap: 6, width: "100%",
        background: bg,
        outline: focused && !selected ? `1px dotted ${t.textDim}` : "none",
        outlineOffset: -1, cursor: dragging ? "grabbing" : "pointer",
        opacity: dragging ? 0.5 : 1, border: "none",
      }}
      {...(onContextMenu ? { onContextMenu } : {})}
      {...dragProps}
    >
      {selected && (
        <span style={{
          position: "absolute", left: 0, top: 2, bottom: 2,
          width: 2, background: t.accent, borderRadius: 1,
        }} />
      )}
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
        <span style={{ color: t.textDim, fontSize: 9, flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
          {modified || sizeStr}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// TreeBranch -- recursive folder/file render with lazy-loaded children
// ---------------------------------------------------------------------------

export interface TreeBranchCallbacks {
  onSelectFile: (fullPath: string, e?: React.MouseEvent) => void;
  onFileContextMenu: (e: React.MouseEvent, entry: { name: string; path: string }) => void;
  onFolderContextMenu: (e: React.MouseEvent, entry: { name: string; path: string }) => void;
  onMoveDrop: (srcPath: string, destFolderPath: string) => void;
  onDeleteFile: (name: string, path: string) => void;
}

interface TreeBranchProps {
  workspaceId: string | undefined;
  /** Workspace-relative entry path for THIS folder (no leading slash). */
  folderPath: string;
  /** Display name for the breadcrumb tooltip; usually the entry's name. */
  folderName: string;
  /** Folder display label override (e.g. channel display names). */
  folderDisplayLabel?: string | null;
  /** When this is the synthetic root, skip rendering the folder row itself. */
  isRoot?: boolean;
  depth: number;
  selectedPaths: Set<string>;
  activeFilePath?: string | null;
  /** Map of child folder name -> displayLabel (used for channel name overrides). */
  childDisplayLabels?: Record<string, string | undefined>;
  callbacks: TreeBranchCallbacks;
}

export function TreeBranch({
  workspaceId, folderPath, folderName, folderDisplayLabel, isRoot,
  depth, selectedPaths, activeFilePath, childDisplayLabels, callbacks,
}: TreeBranchProps) {
  const t = useThemeTokens();
  // Root is implicitly always-expanded; non-root folders use the shared store.
  const expanded = useFileBrowserStore((s) => isRoot ? true : !!s.expandedDirs[folderPath]);
  const toggleDir = useFileBrowserStore((s) => s.toggleDir);

  // Lazy-fetch children only when expanded. React-query dedupes per (wsId, path)
  // so re-collapsing + re-expanding hits the cache.
  const apiPath = folderPath ? "/" + stripSlashes(folderPath) : "/";
  const { data, isLoading } = useWorkspaceFiles(expanded ? workspaceId : undefined, apiPath);

  const sortedChildren = (() => {
    const entries = data?.entries ?? [];
    return [...entries].sort((a, b) => {
      // Knowledge Base folder always first.
      const aIsKB = a.is_dir && isKnowledgeBaseFolder(a.name, "/" + stripSlashes(a.path));
      const bIsKB = b.is_dir && isKnowledgeBaseFolder(b.name, "/" + stripSlashes(b.path));
      if (aIsKB !== bIsKB) return aIsKB ? -1 : 1;
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  })();

  const folderRow = !isRoot ? (
    <TreeFolderRow
      name={folderName}
      displayLabel={folderDisplayLabel}
      fullPath={"/" + stripSlashes(folderPath)}
      expanded={expanded}
      depth={depth}
      multiSelected={selectedPaths.has("/" + stripSlashes(folderPath))}
      onToggle={(_p, e) => {
        if (e?.ctrlKey || e?.metaKey || e?.shiftKey) return; // multi-select handled by parent if it wants
        toggleDir(folderPath);
      }}
      onContextMenu={(e) => callbacks.onFolderContextMenu(e, { name: folderName, path: folderPath })}
      onMoveDrop={(src) => callbacks.onMoveDrop(src, folderPath)}
    />
  ) : null;

  return (
    <div>
      {folderRow}
      {expanded && (
        <div style={{ position: "relative" }}>
          {/* Indent guide — vertical 1px line at each non-root depth. */}
          {!isRoot && (
            <span style={{
              position: "absolute",
              left: depth * INDENT_PX + 6 + 5 /* chevron center */,
              top: 0, bottom: 0, width: 1,
              background: `${t.surfaceBorder}80`,
              pointerEvents: "none",
            }} />
          )}
          {isLoading && (
            <div style={{ paddingLeft: (depth + 1) * INDENT_PX + 6 + 11 + 4, color: t.textDim, fontSize: 11, height: 22, lineHeight: "22px" }}>
              loading…
            </div>
          )}
          {!isLoading && sortedChildren.length === 0 && (
            <div style={{ paddingLeft: (depth + 1) * INDENT_PX + 6 + 11 + 4, color: t.textDim, fontSize: 10, fontStyle: "italic", height: 20, lineHeight: "20px" }}>
              empty
            </div>
          )}
          {sortedChildren.map((entry) => {
            const stripped = stripSlashes(entry.path);
            if (entry.is_dir) {
              const childLabel = entry.display_name || childDisplayLabels?.[entry.name] || null;
              return (
                <TreeBranch
                  key={entry.path}
                  workspaceId={workspaceId}
                  folderPath={stripped}
                  folderName={entry.name}
                  folderDisplayLabel={childLabel}
                  depth={depth + 1}
                  selectedPaths={selectedPaths}
                  activeFilePath={activeFilePath}
                  childDisplayLabels={childDisplayLabels}
                  callbacks={callbacks}
                />
              );
            }
            return (
              <TreeFileRow
                key={entry.path}
                name={entry.name}
                fullPath={stripped}
                size={entry.size}
                modifiedAt={entry.modified_at}
                selected={activeFilePath === stripped}
                multiSelected={selectedPaths.has(stripped)}
                depth={depth + 1}
                onSelect={(e) => callbacks.onSelectFile(stripped, e)}
                onContextMenu={(e) => callbacks.onFileContextMenu(e, { name: entry.name, path: entry.path })}
                onDelete={() => callbacks.onDeleteFile(entry.name, entry.path)}
              />
            );
          })}
        </div>
      )}
    </div>
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
