import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { DndContext, MouseSensor, TouchSensor, type DragEndEvent, type DragStartEvent, useSensor, useSensors } from "@dnd-kit/core";
import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { LocateFixed, Maximize2, Minus, Plus, Sparkles } from "lucide-react";
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
  DASHBOARD_HEADER_ROW_HEIGHT,
  buildFreeformGridConfig,
  clampDashboardCamera,
  clampDropToZone,
  classifyDashboardDrop,
  dashboardFrame,
  findOpenGridPlacement,
  fitFrameCamera,
  freeformOriginForPreset,
  gridLayoutToWorldRect,
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
  if ((pin.zone ?? "grid") === "grid") return defaultGridLayout(index, preset, origin);
  return { x: 0, y: index * preset.defaultTile.h, w: 1, h: preset.defaultTile.h };
}

function normalizeZone(pin: WidgetDashboardPin): ChatZone {
  return pin.zone ?? "grid";
}

function tileRect(pin: WidgetDashboardPin, layout: GridLayoutItem, frame: DashboardFrame): Rect {
  return zonedLayoutToWorldRect(normalizeZone(pin), layout, frame);
}

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

function actualFrameCamera(frame: DashboardFrame, viewport: { w: number; h: number }) {
  return clampDashboardCamera({
    scale: DASHBOARD_CAMERA_MAX_SCALE,
    x: Math.max(24, (viewport.w - frame.centerRect.w) / 2) - frame.centerRect.x,
    y: 48 - frame.headerRect.y,
  });
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
}: Props) {
  const navigate = useNavigate();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
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
  const [activeId, setActiveId] = useState<string | null>(null);
  const [resizePreview, setResizePreview] = useState<Map<string, GridLayoutItem>>(() => new Map());
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const migratedRef = useRef(false);
  const initialCameraRef = useRef(false);
  const freeformEnabled = isFreeformGridConfig(gridConfig);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 300, tolerance: 8 } }),
  );

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
      pins.map((pin) => ({ id: pin.id, zone: normalizeZone(pin), grid_layout: hasLayout(pin) ? pin.grid_layout : null })),
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
    if (!viewportSize.w || !viewportSize.h || initialCameraRef.current) return;
    initialCameraRef.current = true;
    scheduleCamera(actualFrameCamera(frame, viewportSize), "immediate");
  }, [frame, scheduleCamera, viewportSize]);

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

  const onDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(String(event.active.id));
  }, []);

  const onDragEnd = useCallback((event: DragEndEvent) => {
    const pinId = String(event.active.id);
    setActiveId(null);
    const pin = pins.find((p) => p.id === pinId);
    const layout = layouts.get(pinId);
    if (!pin || !layout) return;
    const startRect = tileRect(pin, layout, frame);
    const movedRect = {
      ...startRect,
      x: startRect.x + event.delta.x / cameraRef.current.scale,
      y: startRect.y + event.delta.y / cameraRef.current.scale,
    };
    const target = classifyDashboardDrop(movedRect, frame);
    const bounds = getWidgetLayoutBounds(pin.widget_presentation, target.zone, preset.cols.lg);
    const desired = clampDropToZone(
      target.zone,
      target.x,
      target.y,
      Math.max(bounds.minW, Math.min(bounds.maxW, target.zone === "rail" || target.zone === "dock" ? 1 : layout.w)),
      Math.max(bounds.minH, layout.h),
      preset.cols.lg,
    );
    const next = target.zone === "grid"
      ? findOpenGridPlacement(desired, gridOccupancy(pins, layouts, pinId))
      : desired;
    void persistLayout([{ id: pinId, zone: target.zone, ...next }]);
  }, [cameraRef, frame, layouts, persistLayout, pins, preset]);

  const beginPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 && event.button !== 1) return;
    if ((event.target as HTMLElement).closest("[data-dashboard-tile],button,a,input,textarea,select,[role='button'],iframe")) return;
    event.preventDefault();
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
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", done, { once: true });
    target.addEventListener("pointercancel", done, { once: true });
  }, [cameraRef, scheduleCamera]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      event.preventDefault();
      updateViewportMetrics();
      const factor = Math.exp(-event.deltaY * 0.00065);
      zoomAroundPoint(factor, event.clientX, event.clientY);
    };
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [updateViewportMetrics, viewportRef, zoomAroundPoint]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!viewportRef.current?.contains(document.activeElement)) return;
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        scheduleCamera({ ...cameraRef.current, scale: Math.min(DASHBOARD_CAMERA_MAX_SCALE, cameraRef.current.scale * 1.12) });
      } else if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        scheduleCamera({ ...cameraRef.current, scale: Math.max(DASHBOARD_CAMERA_MIN_SCALE, cameraRef.current.scale / 1.12) });
      } else if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        scheduleCamera(actualFrameCamera(frame, viewportSize), "immediate");
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [cameraRef, frame, scheduleCamera, viewportRef, viewportSize]);

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
      className="relative h-full min-h-[520px] select-none overflow-hidden rounded-lg border border-surface-border/60 bg-surface"
      style={{
        backgroundImage: "radial-gradient(rgb(var(--color-text) / 0.05) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
        touchAction: "none",
        overscrollBehavior: "none",
      }}
      onPointerDown={beginPan}
      tabIndex={0}
      data-testid="channel-dashboard-freeform-canvas"
    >
      <CanvasStarfield />
      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setActiveId(null)}>
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
            const layout = resizePreview.get(pin.id) ?? layouts.get(pin.id) ?? layoutForPin(pin, index, preset, origin);
            const zone = normalizeZone(pin);
            const rect = tileRect(pin, layout, frame);
            return (
              <DraggableDashboardTile
                key={pin.id}
                id={pin.id}
                rect={rect}
                disabled={!editMode}
                scale={camera.scale}
                activeId={activeId}
                className={highlightPinId === pin.id ? "pin-flash" : ""}
              >
                {(binding) => (
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
                      layout={zone}
                      externalDrag={binding}
                      canvasDragHandle
                    />
                    {editMode && (
                      <ResizeHandles
                        edges={zone === "header" ? ["e"] : zone === "rail" || zone === "dock" ? ["s"] : ["s", "e", "se", "w", "sw"]}
                        initial={layout}
                        cellPx={{ w: frame.stepX, h: zone === "header" ? DASHBOARD_HEADER_ROW_HEIGHT : frame.stepY }}
                        scale={camera.scale}
                        clampW={{
                          min: zone === "rail" || zone === "dock" ? 1 : getWidgetLayoutBounds(pin.widget_presentation, zone, preset.cols.lg).minW,
                          max: zone === "rail" || zone === "dock" ? 1 : getWidgetLayoutBounds(pin.widget_presentation, zone, preset.cols.lg).maxW,
                        }}
                        clampH={{ min: zone === "header" ? 1 : getWidgetLayoutBounds(pin.widget_presentation, zone, preset.cols.lg).minH }}
                        showRest
                        onResizing={(box: TileBox) => {
                          const next = clampDropToZone(zone, box.x, box.y, box.w, box.h, preset.cols.lg);
                          setResizePreview((current) => {
                            const clone = new Map(current);
                            clone.set(pin.id, next);
                            return clone;
                          });
                        }}
                        onCommit={(box: TileBox) => {
                          const next = clampDropToZone(zone, box.x, box.y, box.w, box.h, preset.cols.lg);
                          setResizePreview((current) => {
                            const clone = new Map(current);
                            clone.delete(pin.id);
                            return clone;
                          });
                          void persistLayout([{ id: pin.id, zone, ...next }]);
                        }}
                      />
                    )}
                  </>
                )}
              </DraggableDashboardTile>
            );
          })}
        </div>
      </DndContext>

      <CanvasControls
        scale={camera.scale}
        onZoomIn={() => scheduleCamera({ ...cameraRef.current, scale: Math.min(DASHBOARD_CAMERA_MAX_SCALE, cameraRef.current.scale * 1.08) })}
        onZoomOut={() => scheduleCamera({ ...cameraRef.current, scale: Math.max(DASHBOARD_CAMERA_MIN_SCALE, cameraRef.current.scale / 1.08) })}
        onFit={() => scheduleCamera(fitFrameCamera(frame, viewportSize), "immediate")}
        onActualSize={() => scheduleCamera(actualFrameCamera(frame, viewportSize), "immediate")}
        onSpatial={() => {
          writeSpatialHandoff({ kind: "channel", channelId, ts: Date.now() });
          navigate(`/?channel=${encodeURIComponent(channelId)}`);
        }}
      />
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

function DraggableDashboardTile({
  id,
  rect,
  disabled,
  scale,
  activeId,
  className,
  children,
}: {
  id: string;
  rect: Rect;
  disabled: boolean;
  scale: number;
  activeId: string | null;
  className?: string;
  children: (binding: ExternalDragBinding) => ReactNode;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id, disabled });
  const adjustedTransform = transform
    ? { ...transform, x: transform.x / scale, y: transform.y / scale }
    : null;
  const binding: ExternalDragBinding = {
    attributes,
    listeners: disabled ? undefined : listeners,
    setNodeRef,
    isDragging,
    style: {
      transform: adjustedTransform ? CSS.Transform.toString(adjustedTransform) : undefined,
      zIndex: isDragging ? 40 : undefined,
      opacity: activeId === id && isDragging ? 0.72 : undefined,
    } as CSSProperties,
  };
  return (
    <div
      data-dashboard-tile
      data-pin-id={id}
      className={`absolute min-w-0 ${className ?? ""}`}
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
      }}
    >
      {children(binding)}
    </div>
  );
}

function CanvasGuides({ frame, editMode, scale }: { frame: DashboardFrame; editMode: boolean; scale: number }) {
  const guide = editMode ? "border-accent/35 bg-accent/[0.025]" : "border-surface-border/25 bg-white/[0.01]";
  const labelScale = Number.isFinite(scale) && scale > 0 ? 1 / scale : 1;
  return (
    <>
      <div
        className={`pointer-events-none absolute rounded-lg border border-dashed ${guide}`}
        style={{ left: frame.railRect.x, top: frame.railRect.y, width: frame.railRect.w, height: frame.railRect.h }}
      />
      <div
        className={`pointer-events-none absolute rounded-lg border ${editMode ? "border-accent/20" : "border-surface-border/20"} bg-surface/20`}
        style={{ left: frame.centerRect.x, top: frame.centerRect.y, width: frame.centerRect.w, height: frame.centerRect.h }}
      />
      <div
        className={`pointer-events-none absolute rounded-lg border border-dashed ${guide}`}
        style={{ left: frame.dockRect.x, top: frame.dockRect.y, width: frame.dockRect.w, height: frame.dockRect.h }}
      />
      <div
        className={`pointer-events-none absolute rounded-md border border-dashed ${guide}`}
        style={{ left: frame.headerRect.x, top: frame.headerRect.y, width: frame.headerRect.w, height: frame.headerRect.h }}
      />
      {editMode && (
        <div
          className="pointer-events-none absolute whitespace-nowrap rounded-md border border-surface-border/50 bg-surface-raised/80 px-2 py-1 text-[10px] uppercase tracking-wide text-text-dim shadow-sm backdrop-blur"
          style={{
            left: frame.centerRect.x,
            top: frame.headerRect.y - 34,
            transform: `scale(${labelScale})`,
            transformOrigin: "left bottom",
          }}
        >
          Guided lanes stay available; drag outside for freeform placement.
        </div>
      )}
    </>
  );
}

function CanvasControls({
  scale,
  onZoomIn,
  onZoomOut,
  onFit,
  onActualSize,
  onSpatial,
}: {
  scale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onActualSize: () => void;
  onSpatial: () => void;
}) {
  const btn = "inline-flex h-8 w-8 items-center justify-center rounded-md border border-surface-border bg-surface-raised/85 text-text-muted shadow-sm backdrop-blur hover:bg-surface-overlay hover:text-text";
  return (
    <div className="absolute right-4 top-4 z-20 flex items-center gap-1.5">
      <button type="button" className={btn} onClick={onZoomOut} aria-label="Zoom out" title="Zoom out">
        <Minus size={14} />
      </button>
      <div className="rounded-md border border-surface-border bg-surface-raised/85 px-2 py-1 text-[11px] text-text-muted backdrop-blur">
        {Math.round(scale * 100)}%
      </div>
      <button type="button" className={btn} onClick={onZoomIn} aria-label="Zoom in" title="Zoom in">
        <Plus size={14} />
      </button>
      <button type="button" className={btn} onClick={onActualSize} aria-label="Frame dashboard" title="Frame dashboard">
        <LocateFixed size={14} />
      </button>
      <button type="button" className={btn} onClick={onFit} aria-label="Fit dashboard" title="Fit dashboard">
        <Maximize2 size={14} />
      </button>
      <button type="button" className={btn} onClick={onSpatial} aria-label="Open spatial canvas" title="Open spatial canvas">
        <Sparkles size={14} />
      </button>
    </div>
  );
}
