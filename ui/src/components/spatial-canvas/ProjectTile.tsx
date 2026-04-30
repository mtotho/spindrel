import { FolderGit2 } from "lucide-react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import type { WorkspaceMapObjectState } from "../../api/types/workspaceMapState";
import { ObjectStatusPill, mapCueIntent } from "./SpatialObjectStatus";

interface ProjectTileProps {
  node: SpatialNode;
  zoom: number;
  extraScale?: number;
  workState?: WorkspaceMapObjectState | null;
  onSelect?: () => void;
  onOpen?: () => void;
}

function projectHue(node: SpatialNode): number {
  const key = node.project_id ?? node.id;
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 33 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}

export function ProjectTile({ node, zoom, extraScale = 1, workState, onSelect, onOpen }: ProjectTileProps) {
  const project = node.project;
  const name = project?.name || "Project";
  const channelCount = project?.attached_channel_count ?? workState?.counts.channels ?? 0;
  const hue = projectHue(node);
  const showDetail = zoom * extraScale >= 0.34;
  const showStatus = zoom * extraScale >= 0.48;
  const cue = workState?.cue ? mapCueIntent(workState) : null;

  return (
    <div
      data-tile-kind="project"
      className="group relative flex h-full w-full items-center justify-center rounded-[50%] outline-none"
      onClick={(event) => {
        event.stopPropagation();
        onSelect?.();
      }}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onOpen?.();
      }}
      role="button"
      tabIndex={0}
      aria-label={`Project ${name}`}
    >
      <div
        className="absolute inset-[4%] rounded-[50%] border border-white/15 shadow-[0_24px_80px_rgba(0,0,0,0.36)]"
        style={{
          background: [
            `radial-gradient(circle at 34% 28%, hsla(${hue}, 82%, 82%, 0.88), transparent 0 18%)`,
            `radial-gradient(circle at 66% 64%, hsla(${(hue + 52) % 360}, 64%, 56%, 0.45), transparent 0 24%)`,
            `linear-gradient(135deg, hsl(${hue}, 46%, 38%), hsl(${(hue + 24) % 360}, 48%, 20%) 62%, hsl(${(hue + 74) % 360}, 42%, 16%))`,
          ].join(", "),
        }}
      />
      <div
        className="absolute inset-[9%] rounded-[50%] border border-white/10 opacity-55"
        style={{
          background: `repeating-radial-gradient(ellipse at 50% 54%, transparent 0 20px, hsla(${hue}, 70%, 82%, 0.09) 21px 23px)`,
        }}
      />
      <div className="relative z-10 flex max-w-[72%] flex-col items-center gap-1 text-center">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-black/22 text-white ring-1 ring-white/16">
          <FolderGit2 size={18} strokeWidth={2} />
        </div>
        <div className="max-w-full truncate text-[18px] font-semibold leading-tight text-white drop-shadow">
          {name}
        </div>
        {showDetail && (
          <div className="max-w-full truncate rounded-full bg-black/20 px-2 py-0.5 text-[11px] font-medium text-white/75 ring-1 ring-white/12">
            {channelCount} channel{channelCount === 1 ? "" : "s"}
          </div>
        )}
        {showStatus && workState && (
          <div className="mt-1 flex max-w-full items-center gap-1">
            <ObjectStatusPill state={workState} compact />
            {cue && <span className="truncate text-[10px] font-medium text-white/68">{workState.cue?.label}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
