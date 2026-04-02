import { useEffect, useCallback } from "react";
import { Copy, ClipboardCopy, Edit3, Columns2, FilePlus, FolderPlus, Trash2 } from "lucide-react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import { useDeleteWorkspaceFile } from "../../api/hooks/useWorkspaces";
import { apiFetch } from "../../api/client";
import type { WorkspaceFileEntry } from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";
import { writeToClipboard } from "../../utils/clipboard";

interface FileContextMenuProps {
  x: number;
  y: number;
  entry: WorkspaceFileEntry | null; // null = root area context menu
  workspaceId: string;
  onClose: () => void;
  onStartRename: (entry: WorkspaceFileEntry) => void;
  onCreateIn: (dir: string, type: "file" | "folder") => void;
}

interface MenuItem {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
  separator?: boolean;
}

export function FileContextMenu({ x, y, entry, workspaceId, onClose, onStartRename, onCreateIn }: FileContextMenuProps) {
  const t = useThemeTokens();
  const openFile = useFileBrowserStore((s) => s.openFile);
  const splitMode = useFileBrowserStore((s) => s.splitMode);
  const deleteMutation = useDeleteWorkspaceFile(workspaceId);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") onClose();
  }, [onClose]);

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const handleCopyContents = async () => {
    if (!entry || entry.is_dir) return;
    try {
      const data = await apiFetch<{ content: string }>(
        `/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(entry.path)}`
      );
      await writeToClipboard(data.content);
    } catch (err) {
      console.error("Failed to copy contents:", err);
    }
    onClose();
  };

  const handleCopyPath = () => {
    if (!entry) return;
    writeToClipboard(entry.path);
    onClose();
  };

  const handleRename = () => {
    if (!entry) return;
    onStartRename(entry);
    onClose();
  };

  const handleOpenToSide = () => {
    if (!entry || entry.is_dir) return;
    openFile(entry.path, entry.name, "right");
    onClose();
  };

  const handleNewFile = () => {
    const dir = entry?.is_dir ? entry.path : "/";
    onCreateIn(dir, "file");
    onClose();
  };

  const handleNewFolder = () => {
    const dir = entry?.is_dir ? entry.path : "/";
    onCreateIn(dir, "folder");
    onClose();
  };

  const handleDelete = () => {
    if (!entry) return;
    if (confirm(`Delete ${entry.is_dir ? "folder" : "file"} "${entry.name}"?`)) {
      deleteMutation.mutate(entry.path);
    }
    onClose();
  };

  // Build menu items based on entry type
  const items: MenuItem[] = [];

  if (entry && !entry.is_dir) {
    items.push({ label: "Copy contents", icon: <Copy size={14} />, onClick: handleCopyContents });
  }
  if (entry) {
    items.push({ label: "Copy path", icon: <ClipboardCopy size={14} />, onClick: handleCopyPath });
    items.push({ label: "Rename", icon: <Edit3 size={14} />, onClick: handleRename });
  }
  if (entry && !entry.is_dir && splitMode) {
    items.push({ label: "Open to side", icon: <Columns2 size={14} />, onClick: handleOpenToSide });
  }
  if (!entry || entry.is_dir) {
    items.push({ label: "New file", icon: <FilePlus size={14} />, onClick: handleNewFile });
    items.push({ label: "New folder", icon: <FolderPlus size={14} />, onClick: handleNewFolder });
  }
  if (entry) {
    items.push({ label: "Delete", icon: <Trash2 size={14} />, onClick: handleDelete, danger: true, separator: true });
  }

  // Clamp position to viewport
  const menuWidth = 180;
  const menuHeight = items.length * 32 + (items.some((i) => i.separator) ? 9 : 0) + 8;
  const clampedX = Math.min(x, window.innerWidth - menuWidth - 8);
  const clampedY = Math.min(y, window.innerHeight - menuHeight - 8);

  if (typeof document === "undefined") return null;

  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <>
      <div
        onClick={onClose}
        onContextMenu={(e: React.MouseEvent) => { e.preventDefault(); onClose(); }}
        style={{ position: "fixed", inset: 0, zIndex: 50000 }}
      />
      <div
        style={{
          position: "fixed",
          top: clampedY,
          left: clampedX,
          zIndex: 50001,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6,
          padding: "4px 0",
          minWidth: menuWidth,
          boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
        }}
      >
        {items.map((item, i) => (
          <div key={i}>
            {item.separator && (
              <div style={{ height: 1, background: t.surfaceBorder, margin: "4px 0" }} />
            )}
            <div
              onClick={item.onClick}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 12px",
                cursor: "pointer",
                fontSize: 13,
                color: item.danger ? t.danger : t.text,
                borderRadius: 0,
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = t.overlayLight; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
            >
              {item.icon}
              {item.label}
            </div>
          </div>
        ))}
      </div>
    </>,
    document.body
  );
}
