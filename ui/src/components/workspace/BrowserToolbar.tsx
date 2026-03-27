import { useState } from "react";
import { useRouter } from "expo-router";
import {
  Columns2, FilePlus, FolderPlus, Upload, Settings, Play, Square, ChevronRight,
} from "lucide-react";
import { useFileBrowserStore } from "../../stores/fileBrowser";
import {
  useWriteWorkspaceFile,
  useMkdirWorkspace,
  useStartWorkspace,
  useStopWorkspace,
} from "../../api/hooks/useWorkspaces";
import type { SharedWorkspace } from "../../types/api";

interface BrowserToolbarProps {
  workspace: SharedWorkspace;
  onUpload: () => void;
}

export function BrowserToolbar({ workspace, onUpload }: BrowserToolbarProps) {
  const router = useRouter();
  const splitMode = useFileBrowserStore((s) => s.splitMode);
  const toggleSplit = useFileBrowserStore((s) => s.toggleSplit);
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
    workspace.status === "creating" ? "#3b82f6" : "#666";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 12px",
        background: "#141414",
        borderBottom: "1px solid #222",
        flexShrink: 0,
        minHeight: 40,
      }}
    >
      {/* Workspace name + status */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: statusColor, flexShrink: 0 }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: "#e5e5e5" }}>{workspace.name}</span>
      </div>

      {/* Breadcrumb */}
      {leftActive && (
        <div style={{ display: "flex", alignItems: "center", gap: 2, color: "#555", fontSize: 12, overflow: "hidden" }}>
          <ChevronRight size={12} color="#444" />
          <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {leftActive}
          </span>
        </div>
      )}

      <div style={{ flex: 1 }} />

      {/* Inline new file/folder input */}
      {creating && (
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 11, color: "#666" }}>
            New {creating}:
          </span>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={() => { setCreating(null); setNewName(""); }}
            placeholder={creating === "file" ? "filename.txt" : "folder-name"}
            style={{
              background: "#0a0a0a",
              border: "1px solid #333",
              borderRadius: 4,
              padding: "2px 8px",
              color: "#e5e5e5",
              fontSize: 12,
              outline: "none",
              width: 160,
            }}
          />
        </div>
      )}

      {/* Action buttons */}
      <ToolbarButton icon={<FilePlus size={14} />} title="New File" onClick={() => setCreating("file")} disabled={!isRunning} />
      <ToolbarButton icon={<FolderPlus size={14} />} title="New Folder" onClick={() => setCreating("folder")} disabled={!isRunning} />
      <ToolbarButton icon={<Upload size={14} />} title="Upload" onClick={onUpload} disabled={!isRunning} />

      <div style={{ width: 1, height: 20, background: "#333", flexShrink: 0 }} />

      <ToolbarButton
        icon={<Columns2 size={14} />}
        title={splitMode ? "Close Split" : "Split View"}
        onClick={toggleSplit}
        active={splitMode}
      />

      <div style={{ width: 1, height: 20, background: "#333", flexShrink: 0 }} />

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
        background: active ? "rgba(59,130,246,0.15)" : "transparent",
        color: active ? "#3b82f6" : disabled ? "#444" : "#888",
        cursor: disabled ? "not-allowed" : "pointer",
        flexShrink: 0,
        padding: 0,
      }}
    >
      {icon}
    </button>
  );
}
