/**
 * Visual subcomponents for ChannelFileExplorer.
 * Extracted to keep the main file under the 1000-line split rule.
 */
import { useState, useEffect, useMemo } from "react";
import { Plus, Trash2, Archive, ChevronRight, Folder } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFiles,
  useWriteChannelWorkspaceFile,
  type ChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import { useChatStore } from "@/src/stores/chat";
import {
  formatRelativeTime,
  formatSize,
  estimateTokens,
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
// IN CONTEXT card -- pinned active section
// ---------------------------------------------------------------------------

const TOKEN_BUDGET = 8000;

export function InContextCard({
  channelId,
  activeFile,
  onSelectFile,
  onArchive,
  onDelete,
}: {
  channelId: string;
  activeFile: string | null;
  onSelectFile: (workspaceRelativePath: string) => void;
  onArchive: (file: ChannelWorkspaceFile) => void;
  onDelete: (file: ChannelWorkspaceFile) => void;
}) {
  const t = useThemeTokens();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const writeMutation = useWriteChannelWorkspaceFile(channelId);

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(channelId, {
    includeArchive: false,
    includeData: false,
  });

  const queryClient = useQueryClient();
  const isStreaming = useChatStore((s) => Object.keys(s.getChannel(channelId).turns).length > 0);
  useEffect(() => {
    if (!isStreaming) return;
    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
    }, 3000);
    return () => clearInterval(interval);
  }, [isStreaming, channelId, queryClient]);

  const activeFiles = useMemo(
    () => (filesData?.files ?? []).filter((f) => f.section === "active" && f.type !== "folder"),
    [filesData],
  );

  const totalSize = activeFiles.reduce((s, f) => s + (f.size || 0), 0);
  const tokenStr = estimateTokens(totalSize);
  const tokenNum = Math.round(totalSize / 4);
  const tokenPct = Math.min(1, tokenNum / TOKEN_BUDGET);
  const tokenColor =
    tokenPct > 0.85 ? t.danger : tokenPct > 0.6 ? t.warning : t.textDim;

  const channelPathFor = (f: ChannelWorkspaceFile) => `channels/${channelId}/${f.path}`;

  const handleCreate = () => {
    let filename = newName.trim();
    if (!filename) {
      setCreating(false);
      return;
    }
    if (!filename.endsWith(".md")) filename += ".md";
    writeMutation.mutate(
      { path: filename, content: `# ${filename.replace(/\.md$/, "")}\n` },
      {
        onSuccess: () => {
          onSelectFile(`channels/${channelId}/${filename}`);
          setCreating(false);
          setNewName("");
        },
      },
    );
  };

  return (
    <div style={{ flexShrink: 0 }}>
      {/* Section header with token gauge */}
      <div
        className="flex items-center gap-1 pl-2 pr-2"
        style={{ height: 22 }}
      >
        <span
          className="flex-1 uppercase tracking-wider text-left"
          style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
        >
          In Context
        </span>
        {/* Token gauge — fill behind the text like a battery indicator */}
        <span
          className="relative overflow-hidden rounded"
          style={{
            padding: "1px 6px",
            fontSize: 10,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            color: tokenColor,
            backgroundColor: `${t.text}06`,
            flexShrink: 0,
          }}
        >
          <span
            className="absolute left-0 top-0 bottom-0 rounded"
            style={{
              width: `${Math.round(tokenPct * 100)}%`,
              backgroundColor: tokenColor,
              opacity: 0.12,
              transition: "width 0.3s ease, background-color 0.3s ease",
            }}
          />
          <span className="relative">~{tokenStr} tok</span>
        </span>
      </div>

      <div>
        {activeFiles.length === 0 && !creating && (
          <span
            className="block italic"
            style={{ color: t.textDim, fontSize: 11, padding: "4px 12px" }}
          >
            {isLoading ? "Loading\u2026" : "No active files yet"}
          </span>
        )}
        {activeFiles.map((f) => (
          <ActiveFileRow
            key={f.path}
            file={f}
            selected={activeFile === channelPathFor(f)}
            onSelect={() => onSelectFile(channelPathFor(f))}
            onArchive={() => onArchive(f)}
            onDelete={() => onDelete(f)}
          />
        ))}
        {creating ? (
          <div style={{ padding: "2px 12px" }}>
            <input
              autoFocus
              value={newName}
              onChange={(e: any) => setNewName(e.target.value)}
              onKeyDown={(e: any) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") { setCreating(false); setNewName(""); }
              }}
              onBlur={() => {
                if (!newName.trim()) { setCreating(false); setNewName(""); }
              }}
              placeholder="filename.md"
              className="w-full rounded"
              style={{
                background: t.surfaceOverlay,
                border: `1px solid ${t.surfaceBorder}`,
                padding: "1px 6px",
                fontSize: 11,
                color: t.text,
                outline: "none",
                height: 20,
                fontFamily: "inherit",
              }}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="flex items-center gap-1 opacity-40 hover:opacity-80 cursor-pointer bg-transparent border-0"
            style={{ padding: "3px 12px" }}
          >
            <Plus size={10} color={t.textMuted} />
            <span style={{ color: t.textMuted, fontSize: 10 }}>Add active file</span>
          </button>
        )}
      </div>
    </div>
  );
}

function ActiveFileRow({
  file, selected, onSelect, onArchive, onDelete,
}: {
  file: ChannelWorkspaceFile; selected: boolean; onSelect: () => void;
  onArchive: () => void; onDelete: () => void;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const displayName = file.name.includes("/")
    ? file.name.substring(file.name.lastIndexOf("/") + 1) : file.name;
  const icon = getFileIcon(displayName, null, t.textDim);
  const modified = formatRelativeTime(file.modified_at);

  return (
    <button type="button"
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: 12, paddingRight: 8, gap: 6, width: "100%",
        background: selected ? t.accentSubtle : hovered ? `${t.text}08` : "transparent",
        cursor: "pointer", border: "none",
      }}
    >
      {icon}
      <span style={{
        flex: 1, color: t.text, fontSize: 12,
        lineHeight: "22px", minWidth: 0, overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "left",
      }}>
        {displayName}
      </span>
      {hovered ? (
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 2 }}>
          <button type="button"
            onClick={(e) => { e.stopPropagation(); onArchive(); }}
            style={{ padding: 2, opacity: 0.6, background: "none", border: "none", cursor: "pointer" }}
            title="Archive"
          >
            <Archive size={11} color={t.textDim} />
          </button>
          <button type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            style={{ padding: 2, opacity: 0.6, background: "none", border: "none", cursor: "pointer" }}
            title="Delete"
          >
            <Trash2 size={11} color={t.textDim} />
          </button>
        </div>
      ) : modified ? (
        <span style={{ color: t.textDim, fontSize: 9, flexShrink: 0 }}>{modified}</span>
      ) : null}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Breadcrumb -- clickable path segments
// ---------------------------------------------------------------------------

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
