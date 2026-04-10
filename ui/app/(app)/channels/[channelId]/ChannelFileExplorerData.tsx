/**
 * Shared types and helpers for ChannelFileExplorer.
 *
 * The unified explorer renders one panel that combines:
 *   - a pinned IN CONTEXT card (channel-scoped active files via the channel API)
 *   - a breadcrumb-driven directory tree (full workspace via the workspace API)
 *
 * This file holds the small helpers shared between the two surfaces.
 */
import { useEffect, useRef } from "react";
import {
  Archive,
  FileJson, FileCode, FileSpreadsheet, Image, FileType, FileText, File as FileIcon,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A file as returned by the channel-workspace endpoint (active/archive/data). */
export type ChannelFile = {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  section: "active" | "archive" | "data";
  type?: "folder";
  count?: number;
};

/** A directory entry as returned by the generic workspace files endpoint. */
export type WorkspaceEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  size?: number | null;
  modified_at?: number | null;
  display_name?: string | null;
};

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null || isNaN(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 100) return `${kb.toFixed(1)} KB`;
  return `${Math.round(kb)} KB`;
}

export function estimateTokens(bytes: number): string {
  const tokens = Math.round(bytes / 4);
  if (tokens < 1000) return `~${tokens}`;
  return `~${(tokens / 1000).toFixed(1)}k`;
}

export function formatRelativeTime(unixSeconds: number | null | undefined): string {
  if (!unixSeconds || unixSeconds <= 0) return "";
  const seconds = Math.floor(Date.now() / 1000 - unixSeconds);
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  return `${Math.floor(days / 30)}mo`;
}

// ---------------------------------------------------------------------------
// File icons (Seti / VS Code default theme colors)
// ---------------------------------------------------------------------------

const IC = {
  md: "#519aba", json: "#cbcb41", yaml: "#a074c4", py: "#519aba",
  js: "#cbcb41", ts: "#519aba", go: "#519aba", rs: "#dea584",
  rb: "#cc3e44", sh: "#4d5a5e", html: "#e37933", css: "#519aba",
  csv: "#89e051", img: "#a074c4", pdf: "#cc3e44",
};

/**
 * Return a colored icon for a file based on its extension.
 *
 * `liveColor` is used when the file is in the active context (the IN CONTEXT
 * card) — it overrides the per-extension color so all live files visually
 * read as one unit. Pass `null` for tree rows.
 */
export function getFileIcon(name: string, liveColor: string | null, dimColor: string) {
  const ext = name.includes(".") ? name.substring(name.lastIndexOf(".")).toLowerCase() : "";
  const tint = (specific: string) => liveColor ?? specific;
  switch (ext) {
    case ".md": case ".txt": case ".rst":
      return <FileText size={14} color={tint(IC.md)} />;
    case ".json":
      return <FileJson size={14} color={tint(IC.json)} />;
    case ".yaml": case ".yml": case ".toml": case ".ini": case ".cfg":
      return <FileCode size={14} color={tint(IC.yaml)} />;
    case ".py":
      return <FileCode size={14} color={tint(IC.py)} />;
    case ".js": case ".jsx":
      return <FileCode size={14} color={tint(IC.js)} />;
    case ".ts": case ".tsx":
      return <FileCode size={14} color={tint(IC.ts)} />;
    case ".go":
      return <FileCode size={14} color={tint(IC.go)} />;
    case ".rs":
      return <FileCode size={14} color={tint(IC.rs)} />;
    case ".rb":
      return <FileCode size={14} color={tint(IC.rb)} />;
    case ".sh":
      return <FileCode size={14} color={tint(IC.sh)} />;
    case ".java": case ".c": case ".cpp": case ".h": case ".hpp": case ".swift":
      return <FileCode size={14} color={liveColor ?? dimColor} />;
    case ".csv": case ".tsv": case ".xls": case ".xlsx":
      return <FileSpreadsheet size={14} color={tint(IC.csv)} />;
    case ".png": case ".jpg": case ".jpeg": case ".gif": case ".svg":
    case ".webp": case ".ico": case ".bmp":
      return <Image size={14} color={tint(IC.img)} />;
    case ".pdf":
      return <FileType size={14} color={tint(IC.pdf)} />;
    case ".html": case ".xml":
      return <FileCode size={14} color={tint(IC.html)} />;
    case ".css":
      return <FileCode size={14} color={tint(IC.css)} />;
    case ".sql":
      return <FileCode size={14} color={liveColor ?? dimColor} />;
    default:
      return liveColor
        ? <FileText size={14} color={liveColor} />
        : <FileIcon size={14} color={dimColor} />;
  }
}

export function getArchiveIcon(color: string) {
  return <Archive size={14} color={color} />;
}

// ---------------------------------------------------------------------------
// Generic context menu (used by both active rows and tree rows)
// ---------------------------------------------------------------------------

export interface ContextMenuItem {
  label: string;
  danger?: boolean;
  separator?: boolean;
  action: () => void;
}

export function ContextMenu({
  x, y, items, onClose,
}: {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
}) {
  const t = useThemeTokens();
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      style={{
        position: "fixed",
        left: x,
        top: y,
        zIndex: 9999,
        minWidth: 180,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        padding: "4px 0",
        boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
      }}
    >
      {items.map((item, i) => (
        <div
          key={i}
          onClick={item.action}
          style={{
            padding: "5px 14px",
            fontSize: 12,
            color: item.danger ? t.danger : t.text,
            cursor: "pointer",
            borderTop: item.separator ? `1px solid ${t.surfaceBorder}` : undefined,
            marginTop: item.separator ? 4 : 0,
            paddingTop: item.separator ? 8 : 5,
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = t.accentSubtle; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
        >
          {item.label}
        </div>
      ))}
    </div>
  );
}
