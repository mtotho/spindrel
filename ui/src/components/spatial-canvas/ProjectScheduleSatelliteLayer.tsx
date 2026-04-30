import { useMemo } from "react";
import { Clock, Plus } from "lucide-react";
import type { UpcomingItem } from "../../api/hooks/useUpcomingActivity";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import {
  SVG_MAX_DIMENSION_PX,
  bboxOverlaps,
  intersectBbox,
  projectFisheye,
  type Camera,
  type LensTransform,
  type WorldBbox,
} from "./spatialGeometry";
import {
  formatTimeUntil,
  projectScheduleSatellites,
  upcomingHref,
  upcomingTileColor,
  type ProjectScheduleOverflow,
  type ProjectScheduleSatellite,
} from "./spatialActivity";

interface ProjectScheduleSatelliteLayerProps {
  items: UpcomingItem[];
  nodes: SpatialNode[];
  zoom: number;
  tickedNow: number;
  connectionsEnabled: boolean;
  viewportBbox?: WorldBbox;
  navigate: (to: string, options?: any) => void;
  canvasBackState?: unknown;
  lensEngaged?: boolean;
  focalScreen?: { x: number; y: number } | null;
  lensRadius?: number;
  camera?: Camera;
}

interface TetherLine {
  key: string;
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  state: ProjectScheduleSatellite["state"] | "overflow";
}

function pointInViewport(x: number, y: number, viewportBbox?: WorldBbox): boolean {
  if (!viewportBbox) return true;
  return bboxOverlaps({ minX: x - 92, minY: y - 92, maxX: x + 92, maxY: y + 92 }, viewportBbox);
}

function satelliteToneClass(state: ProjectScheduleSatellite["state"]): string {
  if (state === "due") return "bg-danger/[0.16] text-danger ring-danger/45";
  if (state === "imminent") return "bg-warning/[0.15] text-warning ring-warning/45";
  if (state === "soon") return "bg-accent/[0.13] text-accent ring-accent/40";
  return "bg-surface/88 text-text-muted ring-surface-border/70";
}

function satelliteLens(
  x: number,
  y: number,
  props: Pick<ProjectScheduleSatelliteLayerProps, "lensEngaged" | "focalScreen" | "lensRadius" | "camera">,
): LensTransform | null {
  if (!props.lensEngaged || !props.focalScreen || !props.camera || !props.lensRadius) return null;
  return projectFisheye(x, y, props.camera, props.focalScreen, props.lensRadius);
}

function ProjectSatelliteButton({
  sat,
  zoom,
  tickedNow,
  navigate,
  canvasBackState,
  lens,
}: {
  sat: ProjectScheduleSatellite;
  zoom: number;
  tickedNow: number;
  navigate: (to: string, options?: any) => void;
  canvasBackState?: unknown;
  lens: LensTransform | null;
}) {
  const href = upcomingHref(sat.item);
  const color = upcomingTileColor(sat.item);
  const isClose = zoom >= 0.46 || sat.state !== "normal";
  const size = isClose ? 44 : 38;
  const time = formatTimeUntil(sat.item.scheduled_at, tickedNow);
  const projectName = sat.item.project_name || "Project";
  const transform = lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined;

  return (
    <div
      className="absolute z-20 flex flex-col items-center gap-1 pointer-events-auto"
      style={{
        left: sat.x - 76,
        top: sat.y - size / 2,
        width: 152,
        transform,
        transformOrigin: "center center",
      }}
      data-tile-kind="project-schedule-satellite"
      data-project-id={sat.projectId}
      data-schedule-state={sat.state}
      title={[sat.item.title, time, projectName].filter(Boolean).join(" · ")}
    >
      <div
        className="absolute left-[54px] top-1/2 h-px w-8 -translate-y-1/2 rounded-full opacity-70"
        style={{
          background: `linear-gradient(90deg, transparent, ${color})`,
          transform: "translateY(-50%) rotate(-8deg)",
          transformOrigin: "right center",
        }}
      />
      <button
        type="button"
        className={`relative flex items-center justify-center rounded-full ring-1 transition-colors duration-150 hover:bg-surface-overlay focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 ${satelliteToneClass(sat.state)}`}
        style={{
          width: size,
          height: size,
          border: `1px solid ${color}`,
          boxShadow: sat.state === "normal" ? `0 0 22px color-mix(in srgb, ${color} 18%, transparent)` : `0 0 22px ${color}`,
        }}
        aria-label={`Open ${sat.item.title || "project run"}`}
        onClick={(event) => {
          event.stopPropagation();
          if (href) navigate(href, { state: canvasBackState });
        }}
      >
        <span
          className="absolute inset-[6px] rounded-full opacity-35"
          style={{ background: `radial-gradient(circle at 34% 30%, ${color}, transparent 62%)` }}
        />
        <Clock size={isClose ? 18 : 16} strokeWidth={2} />
      </button>
      {isClose && (
        <div className="max-w-[142px] rounded-full bg-surface-raised/92 px-2 py-0.5 text-center text-[10px] font-medium text-text-muted ring-1 ring-surface-border/65">
          <span className="truncate">run probe</span>
          {time && <span className="ml-1 text-text-dim">{time}</span>}
        </div>
      )}
    </div>
  );
}

function ProjectOverflowMarker({ marker, lens }: { marker: ProjectScheduleOverflow; lens: LensTransform | null }) {
  const transform = lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined;
  return (
    <div
      className="absolute z-10 flex h-8 w-8 items-center justify-center rounded-full bg-surface-raised/88 text-[10px] font-semibold text-text-dim ring-1 ring-surface-border/70"
      style={{
        left: marker.x - 16,
        top: marker.y - 16,
        transform,
        transformOrigin: "center center",
      }}
      data-tile-kind="project-schedule-overflow"
      data-project-id={marker.projectId}
      title={`${marker.count} more project run${marker.count === 1 ? "" : "s"}`}
    >
      <Plus size={11} />
      {marker.count}
    </div>
  );
}

export function ProjectScheduleSatelliteLayer(props: ProjectScheduleSatelliteLayerProps) {
  const { items, nodes, zoom, tickedNow, connectionsEnabled, viewportBbox, navigate, canvasBackState } = props;
  const anchors = useMemo(() => {
    return nodes
      .filter((node) => node.project_id)
      .map((node) => ({
        projectId: node.project_id!,
        nodeId: node.id,
        x: node.world_x,
        y: node.world_y,
        w: node.world_w,
        h: node.world_h,
      }));
  }, [nodes]);
  const layout = useMemo(
    () => projectScheduleSatellites(items, anchors, tickedNow, 4),
    [anchors, items, tickedNow],
  );
  const visibleSatellites = layout.satellites.filter((sat) => pointInViewport(sat.x, sat.y, viewportBbox));
  const visibleOverflow = layout.overflow.filter((marker) => pointInViewport(marker.x, marker.y, viewportBbox));
  const tetherLines = useMemo<TetherLine[]>(() => {
    if (!connectionsEnabled) return [];
    return [
      ...visibleSatellites.map((sat) => ({
        key: sat.key,
        fromX: sat.anchorX,
        fromY: sat.anchorY,
        toX: sat.x,
        toY: sat.y,
        state: sat.state,
      })),
      ...visibleOverflow.map((marker) => ({
        key: marker.key,
        fromX: marker.anchorX,
        fromY: marker.anchorY,
        toX: marker.x,
        toY: marker.y,
        state: "overflow" as const,
      })),
    ];
  }, [connectionsEnabled, visibleOverflow, visibleSatellites]);
  const tetherBounds = useMemo(() => {
    if (!tetherLines.length) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const line of tetherLines) {
      minX = Math.min(minX, line.fromX, line.toX);
      minY = Math.min(minY, line.fromY, line.toY);
      maxX = Math.max(maxX, line.fromX, line.toX);
      maxY = Math.max(maxY, line.fromY, line.toY);
    }
    const content = { minX: minX - 96, minY: minY - 96, maxX: maxX + 96, maxY: maxY + 96 };
    const draw = viewportBbox ? intersectBbox(content, viewportBbox) : content;
    if (!draw) return null;
    return {
      x: draw.minX,
      y: draw.minY,
      w: Math.min(draw.maxX - draw.minX, SVG_MAX_DIMENSION_PX),
      h: Math.min(draw.maxY - draw.minY, SVG_MAX_DIMENSION_PX),
    };
  }, [tetherLines, viewportBbox]);
  if (!visibleSatellites.length && !visibleOverflow.length) return null;

  return (
    <>
      {tetherBounds && (
        <div
          className="absolute pointer-events-none"
          style={{ left: tetherBounds.x, top: tetherBounds.y, width: tetherBounds.w, height: tetherBounds.h }}
          aria-hidden
        >
          <svg width={tetherBounds.w} height={tetherBounds.h} viewBox={`${tetherBounds.x} ${tetherBounds.y} ${tetherBounds.w} ${tetherBounds.h}`} style={{ overflow: "visible" }}>
            {tetherLines.map((line) => (
              <path
                key={line.key}
                data-testid="project-schedule-tether"
                d={projectScheduleTetherPath(line)}
                stroke={line.state === "due" || line.state === "imminent" ? "rgb(var(--color-warning))" : "rgb(var(--color-accent))"}
                strokeOpacity={line.state === "due" || line.state === "imminent" ? 0.28 : 0.14}
                strokeWidth={1.3}
                strokeDasharray="2 10"
                strokeLinecap="round"
                fill="none"
              />
            ))}
          </svg>
        </div>
      )}
      {visibleSatellites.map((sat) => (
        <ProjectSatelliteButton
          key={sat.key}
          sat={sat}
          zoom={zoom}
          tickedNow={tickedNow}
          navigate={navigate}
          canvasBackState={canvasBackState}
          lens={satelliteLens(sat.x, sat.y, props)}
        />
      ))}
      {visibleOverflow.map((marker) => (
        <ProjectOverflowMarker
          key={marker.key}
          marker={marker}
          lens={satelliteLens(marker.x, marker.y, props)}
        />
      ))}
    </>
  );
}

function projectScheduleTetherPath(line: TetherLine): string {
  const dx = line.toX - line.fromX;
  const dy = line.toY - line.fromY;
  const dist = Math.max(1, Math.hypot(dx, dy));
  const bend = Math.min(76, Math.max(28, dist * 0.16));
  const nx = -dy / dist;
  const ny = dx / dist;
  const cx = line.fromX + dx * 0.52 + nx * bend;
  const cy = line.fromY + dy * 0.52 + ny * bend;
  return `M ${line.fromX.toFixed(2)} ${line.fromY.toFixed(2)} Q ${cx.toFixed(2)} ${cy.toFixed(2)} ${line.toX.toFixed(2)} ${line.toY.toFixed(2)}`;
}
