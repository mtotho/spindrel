import { useMemo } from "react";
import { Activity, Clock, Plus } from "lucide-react";
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
  channelScheduleSatellites,
  formatTimeUntil,
  upcomingHref,
  upcomingTileColor,
  type ChannelScheduleOverflow,
  type ChannelScheduleSatellite,
} from "./spatialActivity";

interface ScheduleSatelliteLayerProps {
  items: UpcomingItem[];
  nodes: SpatialNode[];
  zoom: number;
  tickedNow: number;
  connectionsEnabled: boolean;
  suppressedChannelIds?: Set<string>;
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
  state: ChannelScheduleSatellite["state"] | "overflow";
}

const SATELLITE_SIZE = 34;
const SATELLITE_SIZE_CLOSE = 40;

function lineBbox(line: TetherLine): WorldBbox {
  return {
    minX: Math.min(line.fromX, line.toX),
    minY: Math.min(line.fromY, line.toY),
    maxX: Math.max(line.fromX, line.toX),
    maxY: Math.max(line.fromY, line.toY),
  };
}

function pointInViewport(x: number, y: number, viewportBbox?: WorldBbox): boolean {
  if (!viewportBbox) return true;
  return bboxOverlaps(
    { minX: x - 80, minY: y - 80, maxX: x + 80, maxY: y + 80 },
    viewportBbox,
  );
}

function satelliteToneClass(state: ChannelScheduleSatellite["state"]): string {
  if (state === "due") return "bg-danger/[0.10] text-danger ring-danger/35";
  if (state === "imminent") return "bg-warning/[0.11] text-warning ring-warning/35";
  if (state === "soon") return "bg-accent/[0.10] text-accent ring-accent/30";
  return "bg-surface-raised/90 text-text-muted ring-surface-border/70";
}

function stateLabel(state: ChannelScheduleSatellite["state"], item: UpcomingItem): string {
  if (state === "due") return item.type === "heartbeat" ? "due" : "run due";
  if (state === "imminent") return "soon";
  if (state === "soon") return "next";
  return item.type === "heartbeat" ? "heartbeat" : "task";
}

function satelliteLens(
  x: number,
  y: number,
  props: Pick<ScheduleSatelliteLayerProps, "lensEngaged" | "focalScreen" | "lensRadius" | "camera">,
): LensTransform | null {
  if (!props.lensEngaged || !props.focalScreen || !props.camera || !props.lensRadius) return null;
  return projectFisheye(x, y, props.camera, props.focalScreen, props.lensRadius);
}

function ScheduleSatelliteButton({
  sat,
  zoom,
  tickedNow,
  navigate,
  canvasBackState,
  lens,
}: {
  sat: ChannelScheduleSatellite;
  zoom: number;
  tickedNow: number;
  navigate: (to: string, options?: any) => void;
  canvasBackState?: unknown;
  lens: LensTransform | null;
}) {
  const href = upcomingHref(sat.item);
  const color = upcomingTileColor(sat.item);
  const isClose = zoom >= 0.52 || sat.state !== "normal";
  const size = isClose ? SATELLITE_SIZE_CLOSE : SATELLITE_SIZE;
  const Icon = sat.item.type === "heartbeat" ? Activity : Clock;
  const label = sat.item.type === "heartbeat" ? "Heartbeat" : sat.item.title;
  const time = formatTimeUntil(sat.item.scheduled_at, tickedNow);
  const title = [label, time, sat.item.channel_name ? `#${sat.item.channel_name}` : null].filter(Boolean).join(" · ");
  const transform = lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined;

  return (
    <div
      className="absolute z-20 flex flex-col items-center gap-1 pointer-events-auto"
      style={{
        left: sat.x - 72,
        top: sat.y - size / 2,
        width: 144,
        transform,
        transformOrigin: "center center",
      }}
      data-tile-kind="channel-schedule-satellite"
      data-schedule-kind={sat.item.type}
      data-schedule-state={sat.state}
      data-channel-id={sat.channelId}
      data-schedule-href={href ?? ""}
      title={title}
    >
      <button
        type="button"
        className={`flex items-center justify-center rounded-full ring-1 transition-colors duration-150 hover:bg-surface-overlay focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 ${satelliteToneClass(sat.state)}`}
        style={{
          width: size,
          height: size,
          border: `1px solid ${color}`,
          boxShadow: sat.state === "normal" ? undefined : `0 0 18px ${color}`,
        }}
        aria-label={`Open ${label}`}
        onClick={(event) => {
          event.stopPropagation();
          if (href) navigate(href, { state: canvasBackState });
        }}
      >
        <Icon size={isClose ? 17 : 15} strokeWidth={2} />
      </button>
      {isClose && (
        <div className="max-w-[132px] rounded-full bg-surface-raised/90 px-2 py-0.5 text-center text-[10px] font-medium text-text-muted ring-1 ring-surface-border/60">
          <span className="truncate">{stateLabel(sat.state, sat.item)}</span>
          {time && <span className="ml-1 text-text-dim">{time}</span>}
        </div>
      )}
    </div>
  );
}

function ScheduleOverflowMarker({ marker, lens }: { marker: ChannelScheduleOverflow; lens: LensTransform | null }) {
  const transform = lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined;
  return (
    <div
      className="absolute z-10 flex h-7 w-7 items-center justify-center rounded-full bg-surface-raised/85 text-[10px] font-semibold text-text-dim ring-1 ring-surface-border/70"
      style={{
        left: marker.x - 14,
        top: marker.y - 14,
        transform,
        transformOrigin: "center center",
      }}
      data-tile-kind="channel-schedule-overflow"
      data-channel-id={marker.channelId}
      title={`${marker.count} more scheduled item${marker.count === 1 ? "" : "s"}`}
    >
      <Plus size={11} />
      {marker.count}
    </div>
  );
}

export function ScheduleSatelliteLayer(props: ScheduleSatelliteLayerProps) {
  const {
    items,
    nodes,
    zoom,
    tickedNow,
    connectionsEnabled,
    suppressedChannelIds,
    viewportBbox,
    navigate,
    canvasBackState,
  } = props;

  const anchors = useMemo(() => {
    return nodes
      .filter((node) => node.channel_id && !suppressedChannelIds?.has(node.channel_id))
      .map((node) => ({
        channelId: node.channel_id!,
        nodeId: node.id,
        x: node.world_x,
        y: node.world_y,
        w: node.world_w,
        h: node.world_h,
      }));
  }, [nodes, suppressedChannelIds]);

  const layout = useMemo(
    () => channelScheduleSatellites(items, anchors, tickedNow, 3),
    [items, anchors, tickedNow],
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
    ].filter((line) => {
      if (!viewportBbox) return true;
      const lb = lineBbox(line);
      return bboxOverlaps(
        { minX: lb.minX - 80, minY: lb.minY - 80, maxX: lb.maxX + 80, maxY: lb.maxY + 80 },
        viewportBbox,
      );
    });
  }, [connectionsEnabled, visibleSatellites, visibleOverflow, viewportBbox]);

  const tetherBounds = useMemo(() => {
    if (!tetherLines.length) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const line of tetherLines) {
      minX = Math.min(minX, line.fromX, line.toX);
      minY = Math.min(minY, line.fromY, line.toY);
      maxX = Math.max(maxX, line.fromX, line.toX);
      maxY = Math.max(maxY, line.fromY, line.toY);
    }
    const contentBbox = { minX: minX - 90, minY: minY - 90, maxX: maxX + 90, maxY: maxY + 90 };
    const drawBbox = viewportBbox ? intersectBbox(contentBbox, viewportBbox) : contentBbox;
    if (!drawBbox) return null;
    return {
      x: drawBbox.minX,
      y: drawBbox.minY,
      w: Math.min(drawBbox.maxX - drawBbox.minX, SVG_MAX_DIMENSION_PX),
      h: Math.min(drawBbox.maxY - drawBbox.minY, SVG_MAX_DIMENSION_PX),
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
          <svg
            width={tetherBounds.w}
            height={tetherBounds.h}
            viewBox={`${tetherBounds.x} ${tetherBounds.y} ${tetherBounds.w} ${tetherBounds.h}`}
            style={{ overflow: "visible" }}
          >
            {tetherLines.map((line) => (
              <line
                key={line.key}
                data-testid="channel-schedule-tether"
                x1={line.fromX}
                y1={line.fromY}
                x2={line.toX}
                y2={line.toY}
                stroke={line.state === "due" || line.state === "imminent" ? "rgb(var(--color-warning))" : "rgb(var(--color-text))"}
                strokeOpacity={line.state === "due" || line.state === "imminent" ? 0.36 : 0.16}
                strokeWidth={1.25}
                strokeDasharray="4 8"
                strokeLinecap="round"
              />
            ))}
          </svg>
        </div>
      )}
      {visibleSatellites.map((sat) => (
        <ScheduleSatelliteButton
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
        <ScheduleOverflowMarker
          key={marker.key}
          marker={marker}
          lens={satelliteLens(marker.x, marker.y, props)}
        />
      ))}
    </>
  );
}
