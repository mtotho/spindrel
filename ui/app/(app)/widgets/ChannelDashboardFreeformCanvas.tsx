import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import type { ExternalDragBinding, TileBox } from "./DashboardDnd";
import { ResizeHandles } from "./DashboardDnd";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useDashboardsStore } from "@/src/stores/dashboards";
import type { DashboardChrome, GridPreset } from "@/src/lib/dashboardGrid";
import type { ChatZone, GridLayoutItem, PinnedWidget, ToolResultEnvelope, WidgetDashboardPin } from "@/src/types/api";
import { useSpatialNodes } from "@/src/api/hooks/useWorkspaceSpatial";
import { useChannels } from "@/src/api/hooks/useChannels";
import { writeSpatialHandoff } from "@/src/lib/spatialHandoff";
import { CanvasStarfield } from "@/src/components/spatial-canvas/SpatialCanvasChrome";
import { dotColor } from "@/src/components/spatial-canvas/spatialIdentity";
import {
  DASHBOARD_CAMERA_EXIT_SCALE,
  DASHBOARD_CAMERA_MAX_SCALE,
  DASHBOARD_CAMERA_MIN_SCALE,
  buildFreeformGridConfig,
  clampDashboardCamera,
  clampDropToZone,
  dashboardFrame,
  findOpenGridPlacement,
  freeformOriginForPreset,
  gridLayoutToWorldRect,
  homeFrameCamera,
  isFreeformGridConfig,
  migrateLayoutsToFreeform,
  originFromGridConfig,
  placeDashboardNeighborGhosts,
  zonedLayoutToWorldRect,
  type DashboardFrame,
  type Rect,
} from "@/src/lib/channelDashboardFreeform";
import { getWidgetLayoutBounds } from "@/src/lib/widgetLayoutHints";
import { dashboardCameraTransform, useDashboardCanvasCamera } from "./useDashboardCanvasCamera";

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    widget_instance_id: pin.widget_instance_id ?? null,
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    widget_contract: pin.widget_contract ?? null,
    config: pin.widget_config ?? {},
    widget_health: pin.widget_health ?? null,
  };
}

function hasLayout(pin: WidgetDashboardPin): pin is WidgetDashboardPin & { grid_layout: GridLayoutItem } {
  const gl = pin.grid_layout;
  return !!gl && typeof gl === "object" && "w" in gl && "h" in gl;
}

function defaultGridLayout(index: number, preset: GridPreset, origin: { x: number; y: number }): GridLayoutItem {
  return {
    x: origin.x + (index % 2) * preset.defaultTile.w,
    y: origin.y + Math.floor(index / 2) * preset.defaultTile.h,
    w: preset.defaultTile.w,
    h: preset.defaultTile.h,
  };
}

function layoutForPin(pin: WidgetDashboardPin, index: number, preset: GridPreset, origin: { x: number; y: number }): GridLayoutItem {
  if (hasLayout(pin)) return pin.grid_layout;
  return defaultGridLayout(index, preset, origin);
}

function normalizeZone(pin: WidgetDashboardPin): ChatZone {
  return "grid";
}

function tileRect(pin: WidgetDashboardPin, layout: GridLayoutItem, frame: DashboardFrame): Rect {
  return zonedLayoutToWorldRect(normalizeZone(pin), layout, frame);
}

type LayoutPreview = {
  zone: ChatZone;
  layout: GridLayoutItem;
  rect?: Rect;
};

function gridOccupancy(
  pins: WidgetDashboardPin[],
  layouts: Map<string, GridLayoutItem>,
  excludeId: string,
): GridLayoutItem[] {
  return pins
    .filter((p) => p.id !== excludeId && normalizeZone(p) === "grid")
    .map((p) => layouts.get(p.id))
    .filter((box): box is GridLayoutItem => !!box);
}

function classifyDashboardPointer(
  _point: { x: number; y: number },
  rect: Rect,
  frame: DashboardFrame,
): { zone: ChatZone; x: number; y: number } {
  return {
    zone: "grid",
    x: Math.max(0, Math.round(rect.x / frame.stepX)),
    y: Math.max(0, Math.round(rect.y / frame.stepY)),
  };
}

interface Props {
  pins: WidgetDashboardPin[];
  preset: GridPreset;
  chrome: DashboardChrome;
  editMode: boolean;
  onUnpin: (pinId: string) => void;
  onEnvelopeUpdate: (pinId: string, envelope: ToolResultEnvelope) => void;
  onEditPin: (pinId: string) => void;
  channelId: string;
  dashboardSlug: string;
  gridConfig: unknown;
  highlightPinId: string | null;
  pendingNewPinId: string | null;
  onPendingNewPinHandled: (pinId: string) => void;
  viewLocked: boolean;
  onViewLockedChange: (locked: boolean) => void;
}

export function ChannelDashboardFreeformCanvas({
  pins,
  preset,
  chrome,
  editMode,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  channelId,
  dashboardSlug,
  gridConfig,
  highlightPinId,
  pendingNewPinId,
  onPendingNewPinHandled,
  viewLocked,
  onViewLockedChange,
}: Props) {
  const navigate = useNavigate();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const replaceConfig = useDashboardPinsStore((s) => s.replaceWidgetConfig);
  const updateDashboard = useDashboardsStore((s) => s.update);
  const { data: spatialNodes } = useSpatialNodes();
  const { data: channels } = useChannels();
  const {
    camera,
    cameraRef,
    viewportRef,
    worldRef,
    viewportSize,
    scheduleCamera,
    zoomAroundPoint,
    updateViewportMetrics,
  } = useDashboardCanvasCamera(dashboardSlug);
  const [movingPinId, setMovingPinId] = useState<string | null>(null);
  const [layoutPreview, setLayoutPreview] = useState<Map<string, LayoutPreview>>(() => new Map());
  const [isPanning, setIsPanning] = useState(false);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const migratedRef = useRef(false);
  const freeformEnabled = isFreeformGridConfig(gridConfig);

  const origin = useMemo(
    () => originFromGridConfig(gridConfig, preset),
    [gridConfig, preset],
  );
  const centerWidth = useMemo(() => {
    if (!viewportSize.w) return 840;
    return Math.max(620, Math.min(1080, viewportSize.w - 2 * 312));
  }, [viewportSize.w]);
  const frame = useMemo(
    () => dashboardFrame(preset, origin, centerWidth, Math.max(760, viewportSize.h * 1.45)),
    [preset, origin, centerWidth, viewportSize.h],
  );
  const layouts = useMemo(() => {
    const out = new Map<string, GridLayoutItem>();
    pins.forEach((pin, index) => {
      const layout = !freeformEnabled && normalizeZone(pin) === "grid" && !hasLayout(pin)
        ? {
            x: (index % 2) * preset.defaultTile.w,
            y: Math.floor(index / 2) * preset.defaultTile.h,
            w: preset.defaultTile.w,
            h: preset.defaultTile.h,
          }
        : layoutForPin(pin, index, preset, origin);
      out.set(
        pin.id,
        !freeformEnabled && normalizeZone(pin) === "grid"
          ? { ...layout, x: layout.x + origin.x, y: layout.y + origin.y }
          : layout,
      );
    });
    return out;
  }, [freeformEnabled, pins, preset, origin]);

  const persistLayout = useCallback(async (items: Array<{ id: string; zone?: ChatZone } & GridLayoutItem>) => {
    try {
      await applyLayout(items);
      setLayoutError(null);
    } catch (err) {
      console.error("Failed to persist channel dashboard layout:", err);
      setLayoutError(err instanceof Error ? err.message : "Failed to save layout");
    }
  }, [applyLayout]);

  useEffect(() => {
    if (migratedRef.current || freeformEnabled) return;
    migratedRef.current = true;
    const nextOrigin = freeformOriginForPreset(preset);
    const patches = migrateLayoutsToFreeform(
      pins.map((pin) => ({ id: pin.id, zone: pin.zone ?? "grid", grid_layout: hasLayout(pin) ? pin.grid_layout : null })),
      nextOrigin,
      { x: 0, y: 0, ...preset.defaultTile },
    );
    const nextConfig = buildFreeformGridConfig(gridConfig, preset.id, nextOrigin);
    void (async () => {
      if (patches.length > 0) await persistLayout(patches);
      await updateDashboard(dashboardSlug, { grid_config: nextConfig });
    })().catch((err) => {
      console.error("Failed to enable freeform channel dashboard:", err);
      setLayoutError(err instanceof Error ? err.message : "Failed to enable freeform dashboard");
    });
  }, [dashboardSlug, freeformEnabled, gridConfig, pins, persistLayout, preset, updateDashboard]);

  useEffect(() => {
    if (!freeformEnabled) return;
    const legacyPins = pins.filter((pin) => {
      const zone = pin.zone ?? "grid";
      return zone === "rail" || zone === "header" || zone === "dock";
    });
    if (legacyPins.length === 0) return;
    const occupied = gridOccupancy(pins, layouts, "");
    const patches = legacyPins.map((pin, index) => {
      const layout = findOpenGridPlacement(
        defaultGridLayout(index, preset, origin),
        occupied,
      );
      occupied.push(layout);
      return { id: pin.id, zone: "grid" as ChatZone, ...layout };
    });
    void (async () => {
      await Promise.all(
        legacyPins.map((pin) =>
          replaceConfig(pin.id, {
            ...(pin.widget_config ?? {}),
            show_in_chat_shelf: true,
          }),
        ),
      );
      await persistLayout(patches);
    })().catch((err) => {
      console.error("Failed to normalize legacy workbench zones:", err);
      setLayoutError(err instanceof Error ? err.message : "Failed to normalize legacy zones");
    });
  }, [freeformEnabled, layouts, origin, persistLayout, pins, preset, replaceConfig]);

  const lockDashboardView = useCallback(() => {
    if (!viewportSize.w || !viewportSize.h) return;
    scheduleCamera(homeFrameCamera(frame, viewportSize), "immediate");
  }, [frame, scheduleCamera, viewportSize]);

  useEffect(() => {
    if (!viewportSize.w || !viewportSize.h || !viewLocked) return;
    lockDashboardView();
  }, [lockDashboardView, viewLocked, viewportSize]);

  const focusWorldRect = useCallback((rect: Rect, zoom = DASHBOARD_CAMERA_MAX_SCALE) => {
    if (!viewportSize.w || !viewportSize.h) return;
    scheduleCamera(clampDashboardCamera({
      scale: zoom,
      x: viewportSize.w / 2 - (rect.x + rect.w / 2) * zoom,
      y: viewportSize.h / 2 - (rect.y + rect.h / 2) * zoom,
    }), "immediate");
  }, [scheduleCamera, viewportSize]);

  useEffect(() => {
    if (!highlightPinId) return;
    const pin = pins.find((p) => p.id === highlightPinId);
    const layout = pin ? layouts.get(pin.id) : null;
    if (!pin || !layout) return;
    focusWorldRect(tileRect(pin, layout, frame), Math.min(0.9, DASHBOARD_CAMERA_MAX_SCALE));
  }, [focusWorldRect, frame, highlightPinId, layouts, pins]);

  useEffect(() => {
    if (!pendingNewPinId || !viewportSize.w || !viewportSize.h) return;
    const pin = pins.find((p) => p.id === pendingNewPinId);
    if (!pin) return;
    const current = layouts.get(pin.id) ?? defaultGridLayout(0, preset, origin);
    const worldCenter = {
      x: (viewportSize.w / 2 - cameraRef.current.x) / cameraRef.current.scale,
      y: (viewportSize.h / 2 - cameraRef.current.y) / cameraRef.current.scale,
    };
    const desired: GridLayoutItem = {
      x: Math.max(0, Math.round(worldCenter.x / frame.stepX - current.w / 2)),
      y: Math.max(0, Math.round(worldCenter.y / frame.stepY - current.h / 2)),
      w: current.w,
      h: current.h,
    };
    const next = findOpenGridPlacement(desired, gridOccupancy(pins, layouts, pin.id));
    void persistLayout([{ id: pin.id, zone: "grid", ...next }]).then(() => {
      focusWorldRect(gridLayoutToWorldRect(next, frame), Math.min(0.9, DASHBOARD_CAMERA_MAX_SCALE));
      onPendingNewPinHandled(pin.id);
    });
  }, [cameraRef, focusWorldRect, frame, layouts, onPendingNewPinHandled, pendingNewPinId, persistLayout, pins, preset, origin, viewportSize]);

  const layoutFromMovedRect = useCallback((
    pinId: string,
    movedRect: Rect,
    pointerWorld: { x: number; y: number },
    layout: GridLayoutItem,
    settleCollision: boolean,
  ): LayoutPreview | null => {
    const pin = pins.find((p) => p.id === pinId);
    if (!pin || !layout) return null;
    const target = classifyDashboardPointer(pointerWorld, movedRect, frame);
    const bounds = getWidgetLayoutBounds(pin.widget_presentation, target.zone, preset.cols.lg);
    const preferredW = Math.max(bounds.minW, Math.min(bounds.maxW, layout.w));
    const preferredH = Math.max(bounds.minH, layout.h);
    const desired = clampDropToZone(
      target.zone,
      target.x,
      target.y,
      preferredW,
      preferredH,
      preset.cols.lg,
    );
    const next = desired;
    const snappedRect = zonedLayoutToWorldRect(target.zone, next, frame);
    return {
      zone: target.zone,
      layout: next,
      rect: settleCollision
        ? snappedRect
        : { ...movedRect, w: snappedRect.w, h: snappedRect.h },
    };
  }, [frame, layouts, pins, preset]);

  const beginTileMove = useCallback((pinId: string, event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const pin = pins.find((p) => p.id === pinId);
    const layout = layouts.get(pinId);
    if (!pin || !layout) return;
    event.preventDefault();
    event.stopPropagation();
    setMovingPinId(pinId);
    const startRect = tileRect(pin, layout, frame);
    const start = { x: event.clientX, y: event.clientY };
    const target = event.currentTarget;
    target.setPointerCapture?.(event.pointerId);

    const previewFor = (moveEvent: PointerEvent, settleCollision: boolean) => {
      const scale = Math.max(0.01, cameraRef.current.scale);
      const pointerWorld = {
        x: (moveEvent.clientX - cameraRef.current.x) / scale,
        y: (moveEvent.clientY - cameraRef.current.y) / scale,
      };
      const movedRect = {
        ...startRect,
        x: startRect.x + (moveEvent.clientX - start.x) / scale,
        y: startRect.y + (moveEvent.clientY - start.y) / scale,
      };
      return layoutFromMovedRect(pinId, movedRect, pointerWorld, layout, settleCollision);
    };

    const move = (moveEvent: PointerEvent) => {
      const next = previewFor(moveEvent, false);
      if (!next) return;
      setLayoutPreview((current) => {
        const clone = new Map(current);
        clone.set(pinId, next);
        return clone;
      });
    };
    const done = (doneEvent: PointerEvent) => {
      const next = previewFor(doneEvent, true);
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", done);
      target.removeEventListener("pointercancel", done);
      try {
        target.releasePointerCapture?.(doneEvent.pointerId);
      } catch {
        /* pointer capture may already be released */
      }
      setMovingPinId(null);
      if (!next) {
        setLayoutPreview((current) => {
          const clone = new Map(current);
          clone.delete(pinId);
          return clone;
        });
        return;
      }
      setLayoutPreview((current) => {
        const clone = new Map(current);
        clone.set(pinId, next);
        return clone;
      });
      void persistLayout([{ id: pinId, zone: next.zone, ...next.layout }]).finally(() => {
        setLayoutPreview((current) => {
          const clone = new Map(current);
          clone.delete(pinId);
          return clone;
        });
      });
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", done, { once: true });
    target.addEventListener("pointercancel", done, { once: true });
  }, [cameraRef, frame, layoutFromMovedRect, layouts, persistLayout, pins]);

  const beginPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 && event.button !== 1) return;
    if (viewLocked) return;
    if ((event.target as HTMLElement).closest("[data-dashboard-tile],button,a,input,textarea,select,[role='button'],iframe")) return;
    event.preventDefault();
    setIsPanning(true);
    const start = { x: event.clientX, y: event.clientY, camera: cameraRef.current };
    const target = event.currentTarget;
    target.setPointerCapture?.(event.pointerId);
    const move = (moveEvent: PointerEvent) => {
      scheduleCamera({
        ...start.camera,
        x: start.camera.x + moveEvent.clientX - start.x,
        y: start.camera.y + moveEvent.clientY - start.y,
      });
    };
    const done = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", done);
      target.removeEventListener("pointercancel", done);
      setIsPanning(false);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", done, { once: true });
    target.addEventListener("pointercancel", done, { once: true });
  }, [cameraRef, scheduleCamera, viewLocked]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      if (viewLocked) return;
      event.preventDefault();
      updateViewportMetrics();
      const factor = Math.exp(-event.deltaY * 0.00042);
      zoomAroundPoint(factor, event.clientX, event.clientY);
    };
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [updateViewportMetrics, viewLocked, viewportRef, zoomAroundPoint]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!viewportRef.current?.contains(document.activeElement)) return;
      if (event.key === "+" || event.key === "=") {
        if (viewLocked) return;
        event.preventDefault();
        scheduleCamera({ ...cameraRef.current, scale: Math.min(DASHBOARD_CAMERA_MAX_SCALE, cameraRef.current.scale * 1.12) });
      } else if (event.key === "-" || event.key === "_") {
        if (viewLocked) return;
        event.preventDefault();
        scheduleCamera({ ...cameraRef.current, scale: Math.max(DASHBOARD_CAMERA_MIN_SCALE, cameraRef.current.scale / 1.12) });
      } else if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        onViewLockedChange(true);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [cameraRef, onViewLockedChange, scheduleCamera, viewLocked, viewportRef]);

  const channelById = useMemo(() => {
    const out = new Map<string, { name?: string | null }>();
    for (const channel of channels ?? []) out.set(channel.id, channel);
    return out;
  }, [channels]);

  const channelGhosts = useMemo(() => {
    const channelNode = spatialNodes?.find((node) => node.channel_id === channelId);
    if (!channelNode || !spatialNodes) return [];
    const neighbors = spatialNodes
      .filter((node) => node.channel_id && node.channel_id !== channelId)
      .map((node) => ({
        id: node.id,
        channelId: node.channel_id as string,
        dx: node.world_x - channelNode.world_x,
        dy: node.world_y - channelNode.world_y,
      }))
      .sort((a, b) => Math.hypot(a.dx, a.dy) - Math.hypot(b.dx, b.dy))
      .slice(0, 6);
    return placeDashboardNeighborGhosts(frame, neighbors);
  }, [channelId, frame, spatialNodes]);

  return (
    <div
      ref={viewportRef}
      className="relative h-full min-h-[520px] select-none overflow-hidden bg-surface"
      style={{
        backgroundImage: "radial-gradient(rgb(var(--color-text) / 0.05) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
        cursor: viewLocked ? "default" : isPanning ? "grabbing" : "grab",
        touchAction: "none",
        overscrollBehavior: "none",
      }}
      onPointerDown={beginPan}
      tabIndex={0}
      data-testid="channel-dashboard-freeform-canvas"
    >
      <CanvasStarfield />
      <div
        ref={worldRef}
        className="absolute left-0 top-0 h-[1px] w-[1px] origin-top-left will-change-transform"
        style={{ transform: dashboardCameraTransform(camera) }}
      >
        <CanvasGuides frame={frame} editMode={editMode} scale={camera.scale} />
        {camera.scale <= 0.48 && channelGhosts.map((ghost) => {
          const channelName = channelById.get(ghost.channelId)?.name ?? "Unnamed channel";
          const color = dotColor(ghost.channelId);
          return (
            <div
              key={ghost.id}
              className="pointer-events-none absolute rounded-xl border bg-surface-raised/85 px-3 py-2 text-[12px] text-text-muted shadow-[0_0_48px_rgba(80,120,255,0.14)] backdrop-blur"
              style={{
                left: ghost.x - 120,
                top: ghost.y - 28,
                width: 240,
                opacity: ghost.opacity,
                borderColor: `${color}55`,
              }}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
                <span className="truncate font-medium text-text">{channelName}</span>
              </div>
              <div className="mt-1 pl-4 text-[10px] uppercase tracking-wide text-text-dim">Spatial neighbor</div>
            </div>
          );})}
        {pins.map((pin, index) => {
          const preview = layoutPreview.get(pin.id);
          const layout = preview?.layout ?? layouts.get(pin.id) ?? layoutForPin(pin, index, preset, origin);
          const zone = preview?.zone ?? normalizeZone(pin);
          const rect = preview?.rect ?? tileRect({ ...pin, zone }, layout, frame);
          const binding = tileMoveBinding(pin.id, editMode, movingPinId, beginTileMove);
          return (
            <DashboardTile
              key={pin.id}
              id={pin.id}
              rect={rect}
              isMoving={movingPinId === pin.id}
              className={highlightPinId === pin.id ? "pin-flash" : ""}
            >
              <>
                <PinnedToolWidget
                  widget={asPinnedWidget(pin)}
                  scope={{ kind: "dashboard", channelId }}
                  onUnpin={onUnpin}
                  onEnvelopeUpdate={onEnvelopeUpdate}
                  editMode={editMode}
                  onEdit={() => onEditPin(pin.id)}
                  borderless={chrome.borderless}
                  hoverScrollbars={chrome.hoverScrollbars}
                  hideTitles={chrome.hideTitles}
                  layout="grid"
                  externalDrag={binding}
                  canvasDragHandle
                />
                {editMode && (
                  <ResizeHandles
                    edges={["s", "e", "se", "w", "sw"]}
                    initial={layout}
                    cellPx={{ w: frame.stepX, h: frame.stepY }}
                    scale={camera.scale}
                    clampW={{
                      min: getWidgetLayoutBounds(pin.widget_presentation, "grid", preset.cols.lg).minW,
                      max: getWidgetLayoutBounds(pin.widget_presentation, "grid", preset.cols.lg).maxW,
                    }}
                    clampH={{ min: getWidgetLayoutBounds(pin.widget_presentation, "grid", preset.cols.lg).minH }}
                    onResizing={(box: TileBox) => {
                      const next = clampDropToZone(zone, box.x, box.y, box.w, box.h, preset.cols.lg);
                      setLayoutPreview((current) => {
                        const clone = new Map(current);
                        clone.set(pin.id, { zone, layout: next });
                        return clone;
                      });
                    }}
                    onCommit={(box: TileBox) => {
                      const next = clampDropToZone(zone, box.x, box.y, box.w, box.h, preset.cols.lg);
                      setLayoutPreview((current) => {
                        const clone = new Map(current);
                        clone.set(pin.id, { zone, layout: next });
                        return clone;
                      });
                      void persistLayout([{ id: pin.id, zone, ...next }]).finally(() => {
                        setLayoutPreview((current) => {
                          const clone = new Map(current);
                          clone.delete(pin.id);
                          return clone;
                        });
                      });
                    }}
                  />
                )}
              </>
            </DashboardTile>
          );
        })}
      </div>
      {camera.scale <= DASHBOARD_CAMERA_EXIT_SCALE && (
        <button
          type="button"
          className="absolute bottom-4 left-1/2 z-20 -translate-x-1/2 rounded-full border border-accent/40 bg-surface-raised/95 px-4 py-2 text-[12px] font-medium text-accent shadow-lg backdrop-blur"
          onClick={() => {
            writeSpatialHandoff({ kind: "channel", channelId, ts: Date.now() });
            navigate(`/?channel=${encodeURIComponent(channelId)}`);
          }}
        >
          Open spatial canvas
        </button>
      )}
      {layoutError && (
        <div className="absolute left-4 top-4 z-30 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
          {layoutError}
        </div>
      )}
    </div>
  );
}

function tileMoveBinding(
  pinId: string,
  enabled: boolean,
  movingPinId: string | null,
  beginTileMove: (pinId: string, event: React.PointerEvent<HTMLElement>) => void,
): ExternalDragBinding {
  const isMoving = movingPinId === pinId;
  return {
    attributes: {
      role: "button",
      tabIndex: 0,
      "aria-disabled": !enabled,
      "aria-pressed": false,
      "aria-roledescription": "draggable",
      "aria-describedby": "",
    },
    listeners: enabled
      ? {
          onPointerDown: (event: React.PointerEvent<HTMLElement>) => beginTileMove(pinId, event),
        }
      : undefined,
    setNodeRef: () => {},
    isDragging: isMoving,
    style: {
      zIndex: isMoving ? 40 : undefined,
      opacity: isMoving ? 0.78 : undefined,
    } as CSSProperties,
  };
}

function DashboardTile({
  id,
  rect,
  isMoving,
  className,
  children,
}: {
  id: string;
  rect: Rect;
  isMoving: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-dashboard-tile
      data-pin-id={id}
      className={`absolute min-w-0 ${isMoving ? "" : "transition-[left,top,width,height] duration-150 ease-out"} ${className ?? ""}`}
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        zIndex: isMoving ? 40 : undefined,
      }}
    >
      {children}
    </div>
  );
}

function CanvasGuides({ frame, editMode, scale }: { frame: DashboardFrame; editMode: boolean; scale: number }) {
  const labelScale = Number.isFinite(scale) && scale > 0 ? 1 / scale : 1;
  return (
    <>
      <div
        className={`pointer-events-none absolute rounded-lg border ${editMode ? "border-accent/20" : "border-surface-border/20"} bg-surface/20`}
        style={{ left: frame.centerRect.x, top: frame.centerRect.y, width: frame.centerRect.w, height: frame.centerRect.h }}
      />
      {editMode && (
        <div
          className="pointer-events-none absolute whitespace-nowrap rounded-md border border-surface-border/50 bg-surface-raised/80 px-2 py-1 text-[10px] uppercase tracking-wide text-text-dim shadow-sm backdrop-blur"
          style={{
            left: frame.centerRect.x,
            top: frame.centerRect.y - 34,
            transform: `scale(${labelScale})`,
            transformOrigin: "left bottom",
          }}
        >
          Freeform canvas. Drag artifacts anywhere on the board.
        </div>
      )}
    </>
  );
}
