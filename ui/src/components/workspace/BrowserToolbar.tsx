import { useState } from "react";
import { useRouter } from "expo-router";
import {
  Columns2, FilePlus, FolderPlus, Upload, Settings, Play, Square, ChevronRight,
  PanelLeft,
} from "lucide-react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import {
  useWriteWorkspaceFile,
  useMkdirWorkspace,
  useStartWorkspace,
  useStopWorkspace,
} from "../../api/hooks/useWorkspaces";
import type { SharedWorkspace } from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";

interface BrowserToolbarProps {
  workspace: SharedWorkspace;
  onUpload: () => void;
  isMobile?: boolean;
}

export function BrowserToolbar({ workspace, onUpload, isMobile }: BrowserToolbarProps) {
  const t = useThemeTokens();
  const router = useRouter();
  const splitMode = useFileBrowserStore((s) => s.splitMode);
  const toggleSplit = useFileBrowserStore((s) => s.toggleSplit);
  const treeVisible = useFileBrowserStore((s) => s.treeVisible);
  const toggleTree = useFileBrowserStore((s) => s.toggleTree);
  const leftActive = useFileBrowserStore((s) => s.leftPane.activeFile);

  const writeMutation = useWriteWorkspaceFile(workspace.id);
  const mkdirMutation = useMkdirWorkspace(workspace.id);
  const startMutation = useStartWorkspace(workspace.id);
  const stopMutation = useStopWorkspace(workspace.id);

  const [creating, setCreating] = useState<"file" | "folder" | null>(null);
  const [newName, setNewName] = useState("");

  const isRunning = workspace.status === "running";

  // Determine current directory for new file/folder
  const currentDir = leftActive ? leftActive.substring(0, leftActive.lastIndexOf("/")) || "/" : "/";

  const handleCreate = async () => {
    if (!newName.trim()) return;
    const path = `${currentDir === "/" ? "" : currentDir}/${newName.trim()}`;
    try {
      if (creating === "file") {
        await writeMutation.mutateAsync({ path, content: "" });
      } else {
        await mkdirMutation.mutateAsync(path);
      }
      setCreating(null);
      setNewName("");
    } catch {}
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape") {
      setCreating(null);
      setNewName("");
    }
  };

  // Status colors
  const statusColor =
    workspace.status === "running" ? "#22c55e" :
    workspace.status === "creating" ? "#3b82f6" : t.textDim;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: isMobile ? 4 : 8,
        padding: isMobile ? "6px 8px" : "6px 12px",
        background: t.surfaceRaised,
        borderBottom: `1px solid ${t.surfaceBorder}`,
        flexShrink: 0,
        minHeight: 40,
        flexWrap: isMobile ? "nowrap" : undefined,
        overflow: "hidden",
      }}
    >
      {/* Tree toggle */}
      <ToolbarButton
        icon={<PanelLeft size={14} />}
        title={treeVisible ? "Hide Explorer" : "Show Explorer"}
        onClick={toggleTree}
        active={treeVisible}
      />

      {/* Workspace name + status */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: isMobile ? 1 : 0, minWidth: 0 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: statusColor, flexShrink: 0 }} />
        <span
          style={{
            fontSize: isMobile ? 13 : 14,
            fontWeight: 600,
            color: t.text,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {workspace.name}
        </span>
      </div>

      {/* Breadcrumb — hide on mobile */}
      {!isMobile && leftActive && (
        <div style={{ display: "flex", alignItems: "center", gap: 2, color: t.textDim, fontSize: 12, overflow: "hidden" }}>
          <ChevronRight size={12} color={t.textDim} />
          <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {leftActive}
          </span>
        </div>
      )}

      <div style={{ flex: 1 }} />

      {/* Inline new file/folder input */}
      {creating && (
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {!isMobile && (
            <span style={{ fontSize: 11, color: t.textDim }}>
              New {creating}:
            </span>
          )}
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={() => { setCreating(null); setNewName(""); }}
            placeholder={creating === "file" ? "filename.txt" : "folder-name"}
            style={{
              background: t.inputBg,
              border: `1px solid ${t.inputBorder}`,
              borderRadius: 4,
              padding: "2px 8px",
              color: t.inputText,
              fontSize: 12,
              outline: "none",
              width: isMobile ? 120 : 160,
            }}
          />
        </div>
      )}

      {/* Action buttons */}
      <ToolbarButton icon={<FilePlus size={14} />} title="New File" onClick={() => setCreating("file")} disabled={!isRunning} />
      <ToolbarButton icon={<FolderPlus size={14} />} title="New Folder" onClick={() => setCreating("folder")} disabled={!isRunning} />
      <ToolbarButton icon={<Upload size={14} />} title="Upload" onClick={onUpload} disabled={!isRunning} />

      {/* Split — hide on mobile */}
      {!isMobile && (
        <>
          <div style={{ width: 1, height: 20, background: t.surfaceBorder, flexShrink: 0 }} />
          <ToolbarButton
            icon={<Columns2 size={14} />}
            title={splitMode ? "Close Split" : "Split View"}
            onClick={toggleSplit}
            active={splitMode}
          />
        </>
      )}

      <div style={{ width: 1, height: 20, background: t.surfaceBorder, flexShrink: 0 }} />

      {/* Container controls */}
      {isRunning ? (
        <ToolbarButton
          icon={<Square size={14} />}
          title="Stop Workspace"
          onClick={() => stopMutation.mutate()}
          disabled={stopMutation.isPending}
        />
      ) : (
        <ToolbarButton
          icon={<Play size={14} />}
          title="Start Workspace"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
        />
      )}

      <ToolbarButton
        icon={<Settings size={14} />}
        title="Settings"
        onClick={() => router.push(`/admin/workspaces/${workspace.id}` as any)}
      />
    </div>
  );
}

function ToolbarButton({
  icon,
  title,
  onClick,
  disabled,
  active,
}: {
  icon: React.ReactNode;
  title: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
}) {
  const t = useThemeTokens();
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 28,
        height: 28,
        borderRadius: 4,
        border: "none",
        background: active ? `${t.accent}26` : "transparent",
        color: active ? t.accent : disabled ? t.textDim : t.textMuted,
        cursor: disabled ? "not-allowed" : "pointer",
        flexShrink: 0,
        padding: 0,
      }}
    >
      {icon}
    </button>
  );
}
