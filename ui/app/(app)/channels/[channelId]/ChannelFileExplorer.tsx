/**
 * ChannelFileExplorer — left-rail IN CONTEXT surface.
 *
 * Tree navigation lives in BrowseFilesModal. This component only renders
 * the FILES header + the IN CONTEXT card (active files injected into every
 * LLM turn). Pinned widgets live in OmniPanel below this.
 */
import { useCallback } from "react";
import { FolderOpen, ChevronDown } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import {
  useMoveChannelWorkspaceFile,
  useDeleteChannelWorkspaceFile,
  type ChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import { InContextCard } from "./ChannelFileExplorerParts";

interface ChannelFileExplorerProps {
  channelId: string;
  activeFile: string | null;
  onSelectFile: (workspaceRelativePath: string) => void;
  onBrowseFiles: () => void;
  /** When provided, title bar shows a collapse chevron (used inside OmniPanel). */
  onCollapseFiles?: () => void;
}

export function ChannelFileExplorer({
  channelId,
  activeFile,
  onSelectFile,
  onBrowseFiles,
  onCollapseFiles,
}: ChannelFileExplorerProps) {
  const t = useThemeTokens();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const moveChannel = useMoveChannelWorkspaceFile(channelId);
  const deleteChannel = useDeleteChannelWorkspaceFile(channelId);

  const archiveActiveFile = useCallback(
    (f: ChannelWorkspaceFile) => {
      const basename = f.name.includes("/") ? f.name.substring(f.name.lastIndexOf("/") + 1) : f.name;
      moveChannel.mutate({ old_path: f.path, new_path: `archive/${basename}` });
    },
    [moveChannel],
  );

  const deleteActiveFile = useCallback(
    async (f: ChannelWorkspaceFile) => {
      const ok = await confirm(`Delete ${f.name}?`, {
        title: "Delete file",
        confirmLabel: "Delete",
        variant: "danger",
      });
      if (!ok) return;
      deleteChannel.mutate(f.path);
    },
    [deleteChannel, confirm],
  );

  return (
    <div
      className="flex flex-col h-full overflow-hidden relative"
      style={{ backgroundColor: t.surfaceRaised }}
    >
      {/* Title bar */}
      <div
        className="flex items-center h-7 gap-0.5"
        style={{ paddingLeft: onCollapseFiles ? 4 : 10, paddingRight: 4 }}
      >
        {onCollapseFiles && (
          <button
            type="button"
            onClick={onCollapseFiles}
            className="header-icon-btn p-1 rounded cursor-pointer bg-transparent border-0"
            title="Collapse files"
          >
            <ChevronDown size={12} color={t.textMuted} />
          </button>
        )}
        <span
          className="flex-1 uppercase tracking-wider"
          style={{ color: t.textMuted, fontSize: 11, fontWeight: 600 }}
        >
          Files
        </span>
        <button
          type="button"
          className="header-icon-btn p-1.5 rounded cursor-pointer bg-transparent border-0"
          onClick={onBrowseFiles}
          title="Browse all files (⌘⇧O)"
        >
          <FolderOpen size={13} color={t.textDim} />
        </button>
      </div>

      {/* IN CONTEXT card — the live surface, only thing that lives in the rail */}
      <div className="flex-1 overflow-y-auto">
        <InContextCard
          channelId={channelId}
          activeFile={activeFile}
          onSelectFile={onSelectFile}
          onArchive={archiveActiveFile}
          onDelete={deleteActiveFile}
        />
      </div>

      <ConfirmDialogSlot />
    </div>
  );
}
