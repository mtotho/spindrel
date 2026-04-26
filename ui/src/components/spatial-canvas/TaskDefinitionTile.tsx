import { useMemo } from "react";
import { MessageSquare, Workflow } from "lucide-react";
import type { TaskItem } from "../shared/TaskConstants";
import { type LensTransform } from "./spatialGeometry";

/**
 * TaskDefinitionTile — outer-ring orbit tile for a single task definition.
 *
 * Three semantic-zoom tiers (mirrors UpcomingTile):
 *   far  : tiny accent-tinted dot, no glyph.
 *   mid  : icon glyph + truncated title.
 *   close: icon + full title + step-count badge + trigger chip.
 *
 * Click → caller's onDive (mirrors channel zoom-dive). Static position
 * (definitions are not time-based — no drift inward).
 */

interface TaskDefinitionTileProps {
  task: TaskItem;
  zoom: number;
  /** World position from spatialDefinitionsOrbit. */
  worldX: number;
  worldY: number;
  /** Optional fisheye projection from the canvas lens pass. */
  lens?: LensTransform | null;
  /** Caller dives the camera + transitions the route. */
  onDive: (taskId: string) => void;
}

const FAR_THRESHOLD = 0.4;
const CLOSE_THRESHOLD = 1.0;

const FAR_DOT = 12;
const MID_W = 56;
const MID_H = 56;
const CLOSE_W = 220;
const CLOSE_H = 84;

function triggerLabel(task: TaskItem): string | null {
  const tc = (task as any).trigger_config;
  if (tc?.type === "schedule") return "schedule";
  if (tc?.type === "event") return "event";
  if (tc?.type === "manual") return "manual";
  if (task.recurrence) return "schedule";
  return null;
}

export function TaskDefinitionTile({ task, zoom, worldX, worldY, lens = null, onDive }: TaskDefinitionTileProps) {
  const isPipeline = (task.steps?.length ?? 0) > 0;
  const Icon = isPipeline ? Workflow : MessageSquare;
  const title = task.title?.trim() || task.prompt?.trim().slice(0, 48) || "(untitled)";

  const tier: "far" | "mid" | "close" =
    zoom < FAR_THRESHOLD ? "far" : zoom < CLOSE_THRESHOLD ? "mid" : "close";

  // Counter-scale labels so they remain readable through the lens at far zoom
  const cs = lens?.sizeFactor ?? 1;

  const tooltip = useMemo(() => {
    const parts: string[] = [title];
    if (isPipeline) parts.push(`${task.steps!.length} steps`);
    const trig = triggerLabel(task);
    if (trig) parts.push(trig);
    return parts.join(" · ");
  }, [task, title, isPipeline]);

  // Far tier — dot
  if (tier === "far") {
    const r = FAR_DOT;
    return (
      <button
        title={tooltip}
        onClick={() => onDive(task.id)}
        className="absolute z-10 flex items-center justify-center rounded-full border-none cursor-pointer bg-accent/55 hover:bg-accent transition-colors p-0"
        style={{
          left: worldX - r / 2,
          top: worldY - r / 2,
          width: r,
          height: r,
          transform: lens
            ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
            : undefined,
          transformOrigin: "center center",
        }}
      />
    );
  }

  // Mid tier — small glyph card
  if (tier === "mid") {
    return (
      <button
        title={tooltip}
        onClick={() => onDive(task.id)}
        className="absolute z-10 flex flex-col items-center justify-center gap-0.5 rounded-xl border border-accent/30 bg-surface-raised text-text shadow cursor-pointer hover:border-accent hover:bg-surface-overlay transition-colors p-0"
        style={{
          left: worldX - MID_W / 2,
          top: worldY - MID_H / 2,
          width: MID_W,
          height: MID_H,
          transform: lens
            ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
            : undefined,
          transformOrigin: "center center",
        }}
      >
        <Icon size={18} className="text-accent" />
        <span
          className="text-[9px] font-medium text-text-muted leading-none truncate max-w-[48px]"
          style={{ transform: cs !== 1 ? `scale(${1 / cs})` : undefined }}
        >
          {title}
        </span>
      </button>
    );
  }

  // Close tier — full card
  const trig = triggerLabel(task);
  return (
    <button
      title={tooltip}
      onClick={() => onDive(task.id)}
      className="absolute z-10 flex flex-row items-center gap-2.5 rounded-xl border border-accent/30 bg-surface-raised text-text shadow-md hover:border-accent hover:bg-surface-overlay cursor-pointer transition-colors px-3 py-2"
      style={{
        left: worldX - CLOSE_W / 2,
        top: worldY - CLOSE_H / 2,
        width: CLOSE_W,
        minHeight: CLOSE_H,
        transform: lens
          ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})`
          : undefined,
        transformOrigin: "center center",
      }}
    >
      <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-accent/10 text-accent shrink-0">
        <Icon size={18} />
      </div>
      <div className="flex flex-col gap-0.5 min-w-0 flex-1">
        <span className="text-[12px] font-semibold text-text truncate">{title}</span>
        <div className="flex flex-row items-center gap-1.5 text-[10px] text-text-muted">
          {isPipeline && <span>{task.steps!.length} steps</span>}
          {isPipeline && trig && <span>·</span>}
          {trig && <span className="capitalize">{trig}</span>}
        </div>
      </div>
    </button>
  );
}
