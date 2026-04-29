import { AlertTriangle, ChevronRight, Clock3, History, ListChecks, Radio } from "lucide-react";
import type { ComponentType } from "react";
import type { LucideProps } from "lucide-react";
import type { WorkspaceMapCueIntent } from "../../api/types/workspaceMapState";
import type { WorkspaceMapObjectState } from "../../api/types/workspaceMapState";
import { mapCueIntent, mapCueRank, mapStateLabel, mapStateMeta, mapStateTone } from "./SpatialObjectStatus.js";

const CUE_VIEWPORT_MARGIN_WORLD = 220;
export interface WorldBbox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface SpatialActionCueObject {
  id: string;
  label: string;
  kind: "channel" | "widget" | "bot" | "landmark";
  worldX: number;
  worldY: number;
  worldW?: number;
  worldH?: number;
  distance: number;
  onSelect: () => void;
  workState?: WorkspaceMapObjectState | null;
}

export function objectWorldBbox(item: SpatialActionCueObject, margin = 0): WorldBbox {
  const w = item.worldW ?? 96;
  const h = item.worldH ?? 72;
  return {
    minX: item.worldX - w / 2 - margin,
    minY: item.worldY - h / 2 - margin,
    maxX: item.worldX + w / 2 + margin,
    maxY: item.worldY + h / 2 + margin,
  };
}

export function objectNearViewport(item: SpatialActionCueObject, viewport?: WorldBbox | null): boolean {
  if (!viewport) return false;
  const bbox = objectWorldBbox(item, CUE_VIEWPORT_MARGIN_WORLD);
  return bbox.minX < viewport.maxX && bbox.maxX > viewport.minX && bbox.minY < viewport.maxY && bbox.maxY > viewport.minY;
}

export function shouldRenderCueMarker(item: SpatialActionCueObject): boolean {
  return Boolean(item.workState && mapCueIntent(item.workState) !== "quiet");
}

export function topActionCompassItems(
  objects: SpatialActionCueObject[],
  viewport?: WorldBbox | null,
  limit = 3,
): SpatialActionCueObject[] {
  return objects
    .filter(shouldRenderCueMarker)
    .slice()
    .sort((a, b) => {
      const aCue = cuePriority(a);
      const bCue = cuePriority(b);
      if (aCue !== bCue) return bCue - aCue;
      const aNear = objectNearViewport(a, viewport) ? 1 : 0;
      const bNear = objectNearViewport(b, viewport) ? 1 : 0;
      if (aNear !== bNear) return bNear - aNear;
      return a.distance - b.distance || a.label.localeCompare(b.label);
    })
    .slice(0, limit);
}

function cuePriority(item: SpatialActionCueObject): number {
  return mapCueRank(item.workState) * 1000 + (item.workState?.cue?.priority ?? 0);
}

function cueIcon(intent: WorkspaceMapCueIntent): ComponentType<LucideProps> {
  if (intent === "investigate") return AlertTriangle;
  if (intent === "next") return Clock3;
  if (intent === "recent") return History;
  return Radio;
}

function cueToneClass(item: SpatialActionCueObject): string {
  const tone = mapStateTone(item.workState);
  if (tone === "danger") return "text-danger ring-danger/55 bg-danger/[0.075]";
  if (tone === "warning") return "text-warning ring-warning/50 bg-warning/[0.075]";
  if (tone === "accent") return "text-accent ring-accent/45 bg-accent/[0.07]";
  return "text-text-muted ring-surface-border bg-surface-raised/80";
}

function cueLabel(item: SpatialActionCueObject): string {
  return mapStateLabel(item.workState) ?? "Map cue";
}

function cueTitle(item: SpatialActionCueObject): string {
  const label = cueLabel(item);
  const meta = mapStateMeta(item.workState);
  return meta ? `${label}: ${meta}` : label;
}

function cueReason(item: SpatialActionCueObject): string {
  return mapStateMeta(item.workState) ?? item.workState?.cue?.reason ?? kindLabel(item.kind);
}

function cueCountLabel(item: SpatialActionCueObject): string | null {
  const intent = mapCueIntent(item.workState);
  const counts = item.workState?.counts;
  if (!counts) return null;
  if (intent === "investigate" && counts.warnings > 0) return `${counts.warnings}`;
  if (intent === "next" && counts.upcoming > 0) return `${counts.upcoming}`;
  if (intent === "recent" && counts.recent > 0) return `${counts.recent}`;
  return null;
}

function actionCount(objects: SpatialActionCueObject[]): number {
  return objects.filter(shouldRenderCueMarker).length;
}

function kindLabel(kind: SpatialActionCueObject["kind"]): string {
  if (kind === "channel") return "Channel";
  if (kind === "widget") return "Widget";
  if (kind === "bot") return "Bot";
  return "Landmark";
}

export function SpatialActionCueLayer({
  objects,
  selectedObjectId,
  highlightedObjectId,
  scale,
  suppressedObjectIds,
}: {
  objects: SpatialActionCueObject[];
  selectedObjectId: string | null;
  highlightedObjectId: string | null;
  scale: number;
  suppressedObjectIds?: Set<string>;
}) {
  const visible = objects.filter((item) => shouldRenderCueMarker(item) && !suppressedObjectIds?.has(item.id));
  if (!visible.length) return null;
  const inverseScale = 1 / Math.max(scale, 0.2);
  return (
    <>
      {visible.map((item) => {
        const intent = mapCueIntent(item.workState);
        const Icon = cueIcon(intent);
        const highlighted = highlightedObjectId === item.id;
        const width = Math.max(42, Math.min(220, (item.worldW ?? 96) * scale + 24));
        const height = Math.max(34, Math.min(160, (item.worldH ?? 72) * scale + 24));
        const toneClass = cueToneClass(item);
        const badgeX = Math.round(width / 2 - 10);
        const badgeY = Math.round(-height / 2 + 2);
        return (
          <div
            key={`action-cue-${item.id}`}
            data-testid="spatial-action-cue-marker"
            data-spatial-action-cue-id={item.id}
            data-spatial-action-cue-intent={intent}
            title={cueTitle(item)}
            className="pointer-events-none absolute z-[4996]"
            style={{
              left: item.worldX,
              top: item.worldY,
              transform: `translate(-50%, -50%) scale(${inverseScale})`,
              transformOrigin: "center center",
            }}
          >
            <div
              className={`relative transition-transform duration-150 ${highlighted ? "scale-110" : "scale-100"}`}
              style={{ width: 0, height: 0 }}
            >
              <div
                className={`absolute flex h-5 w-5 items-center justify-center rounded-full ring-1 backdrop-blur-sm ${toneClass} ${
                  highlighted ? "ring-2 ring-accent/35" : ""
                }`}
                style={{ transform: `translate(${badgeX}px, ${badgeY}px)` }}
              >
                <Icon size={13} />
                <span className="sr-only">{cueLabel(item)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}

export function ActionCompass({
  objects,
  viewport,
  selectedObjectId,
  highlightedObjectId,
  onHighlight,
  collapsed = false,
}: {
  objects: SpatialActionCueObject[];
  viewport?: WorldBbox | null;
  selectedObjectId: string | null;
  highlightedObjectId: string | null;
  onHighlight: (id: string | null) => void;
  collapsed?: boolean;
}) {
  const selectedItem = selectedObjectId
    ? objects.find((item) => item.id === selectedObjectId && shouldRenderCueMarker(item)) ?? null
    : null;
  const rankedItems = topActionCompassItems(objects, viewport, selectedItem ? 6 : 3);
  const items = selectedItem
    ? [selectedItem, ...rankedItems.filter((item) => item.id !== selectedItem.id)].slice(0, 3)
    : rankedItems.slice(0, 3);
  if (!items.length) return null;
  if (collapsed) {
    const total = actionCount(objects);
    const topItem = items[0];
    const intent = mapCueIntent(topItem.workState);
    const Icon = cueIcon(intent);
    return (
      <div
        data-testid="spatial-action-compass"
        data-spatial-action-compass-collapsed="true"
        className="absolute left-4 top-4 z-[2] flex flex-col items-center gap-1 rounded-md bg-surface-raised/90 p-1.5 text-text ring-1 ring-surface-border/70"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          title={`Needs action: ${total}`}
          aria-label={`Needs action: ${total}`}
          className="flex h-10 w-10 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay/60 hover:text-text"
          onPointerEnter={() => onHighlight(topItem.id)}
          onPointerLeave={() => onHighlight(null)}
          onFocus={() => onHighlight(topItem.id)}
          onBlur={() => onHighlight(null)}
          onClick={() => topItem.onSelect()}
        >
          <ListChecks size={17} />
        </button>
        <button
          type="button"
          title={`${cueLabel(topItem)}: ${topItem.label}`}
          aria-label={`${cueLabel(topItem)}: ${topItem.label}`}
          className={`flex h-8 w-8 items-center justify-center rounded-full ring-1 ${cueToneClass(topItem)}`}
          onPointerEnter={() => onHighlight(topItem.id)}
          onPointerLeave={() => onHighlight(null)}
          onFocus={() => onHighlight(topItem.id)}
          onBlur={() => onHighlight(null)}
          onClick={() => topItem.onSelect()}
        >
          <Icon size={13} />
        </button>
        <span className="rounded-full bg-surface-overlay/65 px-1.5 py-0.5 text-[10px] font-medium text-text-muted">{total}</span>
      </div>
    );
  }
  return (
    <div
      data-testid="spatial-action-compass"
      className="absolute left-4 top-4 z-[2] w-[320px] rounded-md bg-surface-raised/90 p-2 text-sm text-text ring-1 ring-surface-border/70"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-end justify-between gap-3 px-1 pb-1.5">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">
            Needs action
          </div>
          <div className="mt-0.5 text-xs text-text-muted">
            Best next clicks from live map state.
          </div>
        </div>
        <span className="rounded-full bg-surface-overlay/60 px-2 py-0.5 text-[11px] text-text-dim">{items.length}</span>
      </div>
      <div className="space-y-1">
        {items.map((item, index) => {
          const intent = mapCueIntent(item.workState);
          const Icon = cueIcon(intent);
          const highlighted = highlightedObjectId === item.id;
          const selected = item.id === selectedObjectId;
          const count = cueCountLabel(item);
          return (
            <button
              key={item.id}
              type="button"
              data-testid="spatial-action-compass-row"
              data-spatial-action-compass-id={item.id}
              data-spatial-action-compass-intent={intent}
              data-spatial-action-compass-selected={selected ? "true" : "false"}
              className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ${
                selected || highlighted
                  ? "bg-accent/[0.08] ring-1 ring-accent/15"
                  : "hover:bg-surface-overlay/60 focus-visible:bg-surface-overlay/60"
              }`}
              onPointerEnter={() => onHighlight(item.id)}
              onPointerLeave={() => onHighlight(null)}
              onFocus={() => onHighlight(item.id)}
              onBlur={() => onHighlight(null)}
              onClick={() => item.onSelect()}
            >
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 ${cueToneClass(item)}`}>
                <Icon size={12} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-xs font-medium text-text">{item.label}</span>
                  <span className="shrink-0 rounded-full bg-surface-overlay/50 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.06em] text-text-dim">
                    {kindLabel(item.kind)}
                  </span>
                </span>
                <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-text-dim">
                  <span className="shrink-0 font-medium text-text-muted">{cueLabel(item)}</span>
                  <span className="min-w-0 truncate">{cueReason(item)}</span>
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                {count && (
                  <span className="rounded-full bg-surface-overlay/65 px-1.5 py-0.5 text-[10px] font-medium text-text-muted">
                    {count}
                  </span>
                )}
                <ChevronRight size={13} className="text-text-dim" />
                <span className="text-[10px] font-medium text-text-dim">{index + 1}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
