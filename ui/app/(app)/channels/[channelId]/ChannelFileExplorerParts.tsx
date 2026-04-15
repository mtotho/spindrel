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

  // Auto-refresh while bot is streaming so newly written active files appear.
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
    tokenPct > 0.85 ? t.danger : tokenPct > 0.6 ? t.warning : t.accent;

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
    <div
      style={{
        marginTop: 6,
        margin: "6px 6px 4px",
        backgroundColor: t.accentSubtle,
        borderRadius: 6,
        borderLeft: `2px solid ${t.accent}`,
        overflow: "hidden",
      }}
    >
      {/* Title row */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          padding: "6px 8px 4px",
          gap: 6,
        }}
      >
        <div style={{
          width: 6, height: 6, borderRadius: 3,
          backgroundColor: isStreaming ? "#14b8a6" : t.accent,
          opacity: isStreaming ? 1 : 0.5,
        }} />
        <span
          style={{
            flex: 1,
            color: t.textMuted,
            fontSize: 10,
            fontWeight: "700",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          In Context
        </span>
        <span
          style={{
            color: tokenColor,
            fontSize: 10,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          }}
        >
          {tokenStr} tok
        </span>
      </div>

      {/* Token bar */}
      <div style={{ height: 2, backgroundColor: `${t.text}10`, margin: "0 8px", borderRadius: 1 }}>
        <div
          style={{
            width: `${Math.round(tokenPct * 100)}%`,
            height: 2,
            backgroundColor: tokenColor,
            borderRadius: 1,
          }}
        />
      </div>

      {/* File rows */}
      <div style={{ padding: "4px 0" }}>
        {activeFiles.length === 0 && !creating && (
          <span
            style={{
              display: "block",
              color: t.textDim,
              fontSize: 11,
              fontStyle: "italic",
              padding: "4px 10px",
            }}
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
          <div style={{ padding: "2px 10px" }}>
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
              style={{
                width: "100%",
                background: t.inputBg,
                border: `1px solid ${t.accent}`,
                borderRadius: 3,
                padding: "1px 6px",
                fontSize: 11,
                color: t.text,
                outline: "none",
                height: 18,
                fontFamily: "inherit",
              }}
            />
          </div>
        ) : (
          <button type="button"
            onClick={() => setCreating(true)}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 5,
              padding: "3px 10px",
              opacity: 0.55,
              cursor: "pointer",
              background: "none",
              border: "none",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
            onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.55"; }}
          >
            <Plus size={11} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 10.5, fontWeight: "500" }}>
              Add active file
            </span>
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
  const icon = getFileIcon(displayName, t.accent, t.textDim);
  const modified = formatRelativeTime(file.modified_at);

  return (
    <button type="button"
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: 10, paddingRight: 8, gap: 6, width: "100%",
        background: selected ? `${t.accent}25` : hovered ? `${t.accent}12` : "transparent",
        cursor: "pointer", border: "none",
      }}
    >
      {icon}
      <span style={{
        flex: 1, color: selected ? t.text : t.accent, fontSize: 11.5,
        lineHeight: "22px", minWidth: 0, overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "left",
      }}>
        {displayName}
      </span>
      {hovered ? (
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 1 }}>
          <button type="button"
            onClick={(e) => { e.stopPropagation(); onArchive(); }}
            style={{ padding: 2, opacity: 0.7, background: "none", border: "none", cursor: "pointer" }}
            title="Archive"
          >
            <Archive size={11} color={t.textMuted} />
          </button>
          <button type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            style={{ padding: 2, opacity: 0.7, background: "none", border: "none", cursor: "pointer" }}
            title="Delete"
          >
            <Trash2 size={11} color={t.textMuted} />
          </button>
        </div>
      ) : modified ? (
        <span style={{ color: t.textDim, fontSize: 9, flexShrink: 0 }}>{modified}</span>
      ) : null}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Scope strip -- quick-jump chips
// ---------------------------------------------------------------------------

export function ScopeStrip({
  currentPath, channelTarget, memoryTarget, rootTarget, onJump,
}: {
  currentPath: string; channelTarget: string | null; memoryTarget: string | null;
  rootTarget: string; onJump: (path: string) => void;
}) {
  const t = useThemeTokens();
  const chips: { label: string; path: string }[] = [];
  if (channelTarget) chips.push({ label: "Channel", path: channelTarget });
  if (memoryTarget) chips.push({ label: "Memory", path: memoryTarget });
  chips.push({ label: "Workspace", path: rootTarget });

  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 4, padding: "4px 8px" }}>
      {chips.map((c) => {
        const active = currentPath === c.path || (c.path !== "/" && currentPath.startsWith(c.path + "/"));
        return (
          <button type="button" key={c.label} onClick={() => onJump(c.path)}
            style={{
              padding: "2px 8px", borderRadius: 10, cursor: "pointer",
              backgroundColor: active ? t.accentSubtle : "transparent",
              border: active ? `1px solid ${t.accentBorder}` : "1px solid transparent",
            }}
            onMouseEnter={(e) => { if (!active) e.currentTarget.style.backgroundColor = `${t.text}08`; }}
            onMouseLeave={(e) => { if (!active) e.currentTarget.style.backgroundColor = active ? t.accentSubtle : "transparent"; }}
          >
            <span style={{
              color: active ? t.accent : t.textMuted, fontSize: 10,
              fontWeight: active ? "600" : "500", letterSpacing: 0.2,
            }}>
              {c.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Breadcrumb -- clickable path segments
// ---------------------------------------------------------------------------

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

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", padding: "3px 10px", flexWrap: "nowrap", minHeight: 20 }}>
      <button type="button" onClick={() => onNavigate("/")}
        style={{ cursor: "pointer", opacity: 0.85, background: "none", border: "none", padding: 0 }}
        onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
        onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.85"; }}
      >
        <span style={{ color: path === "/" ? t.text : t.accent, fontSize: 10.5, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>
          /ws
        </span>
      </button>
      {segments.map((seg, i) => {
        const segPath = "/" + segments.slice(0, i + 1).join("/");
        const isLast = i === segments.length - 1;
        const label = labelFor(seg, i);
        return (
          <div key={segPath} style={{ display: "flex", flexDirection: "row", alignItems: "center", minWidth: 0 }}>
            <span style={{ color: t.textDim, fontSize: 10.5, margin: "0 3px" }}>&rsaquo;</span>
            <button type="button" onClick={() => !isLast && onNavigate(segPath)}
              style={{ cursor: isLast ? "default" : "pointer", opacity: 0.85, minWidth: 0, background: "none", border: "none", padding: 0 }}
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
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tree row -- folder or file in current directory
// ---------------------------------------------------------------------------

export function TreeFolderRow({
  name, displayLabel, fullPath, onNavigate, onContextMenu, onMoveDrop, focused,
}: {
  name: string; displayLabel?: string | null; fullPath: string;
  onNavigate: (p: string) => void; onContextMenu?: (e: any) => void;
  onMoveDrop?: (sourcePath: string) => void; focused?: boolean;
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
    <button type="button" onClick={() => onNavigate(fullPath)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: 12, paddingRight: 8, gap: 6, width: "100%",
        background: dragOver ? `${t.accent}25` : hovered || focused ? `${t.text}08` : "transparent",
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
  name, fullPath, size, modifiedAt, selected, focused, onSelect, onContextMenu, onDelete, draggable = true,
}: {
  name: string; fullPath: string; size: number | null | undefined;
  modifiedAt: number | null | undefined; selected: boolean; focused?: boolean;
  onSelect: () => void; onContextMenu?: (e: any) => void; onDelete: () => void;
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
    <button type="button" onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "row", alignItems: "center",
        height: 22, paddingLeft: 12, paddingRight: 8, gap: 6, width: "100%",
        background: selected ? t.accentSubtle : hovered || focused ? `${t.text}08` : "transparent",
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
