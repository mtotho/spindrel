import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { isEmptySpaceClickGesture } from "./spatialCanvasPointer";
import { useUIStore } from "../../stores/ui";
import { SPATIAL_HANDOFF_KEY } from "../../lib/spatialHandoff";
import {
  DIVE_SCALE_THRESHOLD,
  LENS_NATIVE_FRACTION,
  LENS_SETTLE_MS,
  MAX_SCALE,
  MIN_SCALE,
  type Camera,
} from "./spatialGeometry";

export function useSpatialInteractions(args: Record<string, any>) {
  const {
    viewportRef,
    viewportRectRef,
    viewportSize,
    draggingNodeId,
    activatedTileId,
    setActivatedTileId,
    diving,
    scheduleCamera,
    cameraRef,
    flushCamera,
    zoomAroundPoint,
    setSelectedSpatialObject,
    setSelectedAttentionId,
    setStarboardOpen,
    setContextMenu,
    nodes,
    fitAllNodes,
  } = args;
  // Fisheye lens state (P16). `lensEngaged` is the held-Space flag;
  // `focalScreen` is the cursor position relative to the viewport rect at
  // engage time and updated live while engaged. `lensSettling` is true for
  // ~LENS_SETTLE_MS after engage/disengage so tiles get a CSS transition for
  // the pop-in / pop-out; while engaged + cursor-tracking it's false so tile
  // transforms follow the cursor without lag.
  const [lensEngaged, setLensEngaged] = useState(false);
  const [focalScreen, setFocalScreen] = useState<{ x: number; y: number } | null>(null);
  const [lensSettling, setLensSettling] = useState(false);
  const lastCursorRef = useRef<{ x: number; y: number } | null>(null);
  const pendingFocalRef = useRef<{ x: number; y: number } | null>(null);
  const focalRafRef = useRef<number | null>(null);
  const lensSettleTimerRef = useRef<number | null>(null);

  const lensRadius = useMemo(() => {
    if (!viewportSize.w || !viewportSize.h) return 0;
    return LENS_NATIVE_FRACTION * Math.min(viewportSize.w, viewportSize.h);
  }, [viewportSize.w, viewportSize.h]);

  const triggerLensSettle = useCallback(() => {
    setLensSettling(true);
    if (lensSettleTimerRef.current) {
      window.clearTimeout(lensSettleTimerRef.current);
    }
    lensSettleTimerRef.current = window.setTimeout(() => {
      setLensSettling(false);
      lensSettleTimerRef.current = null;
    }, LENS_SETTLE_MS + 10);
  }, []);

  // Cursor tracking (always-on; cheap). Used for both engage-time focal seed
  // and live focal updates while engaged.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const handler = (e: PointerEvent) => {
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const p = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      lastCursorRef.current = p;
      if (!lensEngaged) return;
      pendingFocalRef.current = p;
      if (focalRafRef.current === null) {
        focalRafRef.current = window.requestAnimationFrame(() => {
          focalRafRef.current = null;
          setFocalScreen(pendingFocalRef.current);
        });
      }
    };
    el.addEventListener("pointermove", handler);
    return () => el.removeEventListener("pointermove", handler);
  }, [lensEngaged]);

  useEffect(() => {
    return () => {
      if (focalRafRef.current !== null) window.cancelAnimationFrame(focalRafRef.current);
    };
  }, []);

  // Space hold-to-engage. Guards: input focus, modifiers, repeat, in-flight
  // pan, in-flight tile drag.
  useEffect(() => {
    const isInputFocused = () => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (e.repeat) return;
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
      if (isInputFocused()) return;
      if (panState.current) return;
      if (draggingNodeId) return;
      if (lensEngaged) return;
      e.preventDefault();
      setFocalScreen(lastCursorRef.current);
      setLensEngaged(true);
      triggerLensSettle();
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      if (!lensEngaged) return;
      setLensEngaged(false);
      triggerLensSettle();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [lensEngaged, draggingNodeId, triggerLensSettle]);

  // If a drag starts while the lens is held, drop the lens (drag math at the
  // lens edge would be non-linear — release first, drag second).
  useEffect(() => {
    if (draggingNodeId && lensEngaged) {
      setLensEngaged(false);
      triggerLensSettle();
    }
  }, [draggingNodeId, lensEngaged, triggerLensSettle]);
  const panState = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    cameraX: number;
    cameraY: number;
  } | null>(null);

  const onBgPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 || diving) return;
      // Pan starts on background space only. Tiles and landmarks own their
      // own click/selection semantics; Arrange mode is the only movement mode.
      // The world layer covers the entire viewport (absolute inset-0), so a strict
      // `target === currentTarget` check would only allow pan on the
      // viewport's literal edges — the gap area between tiles wouldn't
      // pan.
      const target = e.target as HTMLElement;
      if (target.closest("button,a,input,textarea,select")) return;
      if (target.closest("[data-tile-kind]")) return;
      if (activatedTileId) setActivatedTileId(null);
      // Pan supersedes lens — drop the lens if it's engaged.
      if (lensEngaged) {
        setLensEngaged(false);
        triggerLensSettle();
      }
      panState.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        cameraX: cameraRef.current.x,
        cameraY: cameraRef.current.y,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [diving, activatedTileId, lensEngaged, triggerLensSettle],
  );

  const onBgPointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    scheduleCamera({
      ...cameraRef.current,
      x: p.cameraX + (e.clientX - p.startX),
      y: p.cameraY + (e.clientY - p.startY),
    });
  }, [scheduleCamera]);

  const onBgPointerUp = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const p = panState.current;
    if (!p || p.pointerId !== e.pointerId) return;
    panState.current = null;
    flushCamera();
    if (
      isEmptySpaceClickGesture({
        startX: p.startX,
        startY: p.startY,
        endX: e.clientX,
        endY: e.clientY,
      })
    ) {
      setSelectedSpatialObject(null);
      setSelectedAttentionId(null);
      setStarboardOpen(false);
      setContextMenu(null);
    }
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }, [flushCamera]);

  // Beam-me-up handoff. Channel and widget detail routes set a sessionStorage
  // flag before navigating here; on mount we select the target node and land
  // at a safe overview zoom below the push-through dive threshold.
  const beamConsumedRef = useRef(false);
  useEffect(() => {
    if (beamConsumedRef.current) return;
    if (!nodes || nodes.length === 0) return;
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem(SPATIAL_HANDOFF_KEY);
    } catch {
      beamConsumedRef.current = true;
      return;
    }
    if (!raw) {
      beamConsumedRef.current = true;
      return;
    }
    try {
      sessionStorage.removeItem(SPATIAL_HANDOFF_KEY);
    } catch {
      // Ignore — flag will just expire on the timestamp check next time.
    }
    beamConsumedRef.current = true;
    let parsed: { kind?: string; channelId?: string; pinId?: string; ts?: number } | null = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    if (!parsed || typeof parsed.ts !== "number") return;
    if (Date.now() - parsed.ts > 5000) return;
    const tile = parsed.kind === "widgetPin" && parsed.pinId
      ? nodes.find((n: any) => {
          if (n.widget_pin_id === parsed!.pinId) return true;
          const origin = n.pin?.widget_origin;
          return !!origin
            && typeof origin === "object"
            && (origin as { source_dashboard_pin_id?: unknown }).source_dashboard_pin_id === parsed!.pinId;
        })
      : parsed.channelId
        ? nodes.find((n: any) => n.channel_id === parsed!.channelId)
        : null;
    if (!tile) return;
    if (tile.widget_pin_id) {
      setSelectedSpatialObject({ kind: "widget", nodeId: tile.id });
    } else if (tile.channel_id) {
      setSelectedSpatialObject({ kind: "channel", nodeId: tile.id });
    }
    const targetScale = DIVE_SCALE_THRESHOLD * 0.7;
    const tileCx = tile.world_x + tile.world_w / 2;
    const tileCy = tile.world_y + tile.world_h / 2;
    scheduleCamera(
      {
        scale: targetScale,
        x: rect.width / 2 - tileCx * targetScale,
        y: rect.height / 2 - tileCy * targetScale,
      },
      "immediate",
    );
  }, [nodes, viewportSize.w, viewportSize.h, scheduleCamera]);

  // Manual wheel listener with { passive: false } — React's synthetic onWheel
  // is passive by default, so preventDefault() would be silently ignored and
  // the page would scroll underneath.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    function handler(e: WheelEvent) {
      if (diving) return;
      if (e.target instanceof Element && e.target.closest("[data-starboard-panel='true']")) return;
      e.preventDefault();
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      zoomAroundPoint(
        Math.exp(-e.deltaY * 0.001),
        e.clientX - rect.left,
        e.clientY - rect.top,
      );
    }
    viewport.addEventListener("wheel", handler, { passive: false });
    return () => viewport.removeEventListener("wheel", handler);
  }, [diving, zoomAroundPoint]);

  // Keyboard shortcuts for the canvas chrome: `F` fits all nodes, `+` / `-`
  // zoom around the viewport center. Same input-focus / dive / drag guards
  // the lens-engage hook uses; modifier keys (Ctrl/Cmd/Alt) bail so OS
  // shortcuts like Cmd+= / Cmd+- (browser zoom) keep their native behavior.
  useEffect(() => {
    const isInputFocused = () => {
      const el = document.activeElement as HTMLElement | null;
      if (!el) return false;
      const tag = el.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
    };
    function handler(e: KeyboardEvent) {
      if (diving || draggingNodeId) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isInputFocused()) return;
      if (e.key === "f" || e.key === "F") {
        if (e.repeat || e.shiftKey) return;
        e.preventDefault();
        fitAllNodes();
        return;
      }
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        const rect = viewportRectRef.current;
        if (!rect.width || !rect.height) return;
        zoomAroundPoint(1.2, rect.width / 2, rect.height / 2);
        return;
      }
      if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        const rect = viewportRectRef.current;
        if (!rect.width || !rect.height) return;
        zoomAroundPoint(0.83, rect.width / 2, rect.height / 2);
        return;
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [diving, draggingNodeId, fitAllNodes, zoomAroundPoint]);

  // Touch long-press on canvas background previously opened a radial menu.
  // It now opens the global ⌘K palette instead — same canvas-aware menu the
  // keyboard shortcut shows. Only fires on the viewport background (not on
  // a tile / chrome) and only when the press doesn't drift > 8px during the
  // 350ms hold. Tile long-press is owned by dnd-kit's TouchSensor.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    let timer: number | null = null;
    let startX = 0;
    let startY = 0;
    const cancel = () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };
    const onDown = (e: PointerEvent) => {
      if (e.pointerType !== "touch") return;
      const target = e.target as HTMLElement | null;
      if (target && target.closest("[data-tile-kind]")) return;
      startX = e.clientX;
      startY = e.clientY;
      cancel();
      timer = window.setTimeout(() => {
        useUIStore.getState().openPalette();
        timer = null;
      }, 350);
    };
    const onMove = (e: PointerEvent) => {
      if (timer === null) return;
      if (Math.hypot(e.clientX - startX, e.clientY - startY) > 8) cancel();
    };
    viewport.addEventListener("pointerdown", onDown);
    viewport.addEventListener("pointermove", onMove);
    viewport.addEventListener("pointerup", cancel);
    viewport.addEventListener("pointercancel", cancel);
    return () => {
      cancel();
      viewport.removeEventListener("pointerdown", onDown);
      viewport.removeEventListener("pointermove", onMove);
      viewport.removeEventListener("pointerup", cancel);
      viewport.removeEventListener("pointercancel", cancel);
    };
  }, []);

  // Two-finger pinch zoom (mobile / trackpad). Captures all touch pointers on
  // the viewport regardless of whether they land on tiles or background, so a
  // second finger always escalates to pinch even mid tile-drag. While pinching
  // we suppress the single-finger pan and the dnd-kit tile drag (the latter
  // by sending preventDefault on the move). Anchor logic mirrors the wheel
  // handler: zoom around the initial midpoint, plus midpoint translation for
  // two-finger pan.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const pointers = new Map<number, { x: number; y: number }>();
    let pinch:
      | { distance: number; midpoint: { x: number; y: number }; camera: Camera }
      | null = null;

    function midpointAndDistance() {
      const pts = Array.from(pointers.values()).slice(0, 2);
      const [p1, p2] = pts;
      return {
        distance: Math.hypot(p1.x - p2.x, p1.y - p2.y),
        midpointClient: { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 },
      };
    }

    function onDown(e: PointerEvent) {
      if (e.pointerType !== "touch") return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size >= 2 && !pinch) {
        const rect = viewportRectRef.current;
        if (!rect.width || !rect.height) return;
        const { distance, midpointClient } = midpointAndDistance();
        pinch = {
          distance,
          midpoint: {
            x: midpointClient.x - rect.left,
            y: midpointClient.y - rect.top,
          },
          camera: cameraRef.current,
        };
        // Pinch overrides pan AND any in-flight tile drag.
        panState.current = null;
        if (lensEngaged) {
          setLensEngaged(false);
          triggerLensSettle();
        }
      }
    }

    function onMove(e: PointerEvent) {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (!pinch || pointers.size < 2) return;
      e.preventDefault();
      const rect = viewportRectRef.current;
      if (!rect.width || !rect.height) return;
      const { distance, midpointClient } = midpointAndDistance();
      const newMid = {
        x: midpointClient.x - rect.left,
        y: midpointClient.y - rect.top,
      };
      const factor = distance / pinch.distance;
      const c = pinch.camera;
      const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, c.scale * factor));
      const k = newScale / c.scale;
      const mx = pinch.midpoint.x;
      const my = pinch.midpoint.y;
      const dx = newMid.x - mx;
      const dy = newMid.y - my;
      scheduleCamera({
        scale: newScale,
        x: mx - (mx - c.x) * k + dx,
        y: my - (my - c.y) * k + dy,
      });
    }

    function onUp(e: PointerEvent) {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) {
        pinch = null;
        flushCamera();
      }
    }

    viewport.addEventListener("pointerdown", onDown, { capture: true });
    viewport.addEventListener("pointermove", onMove, { capture: true, passive: false });
    viewport.addEventListener("pointerup", onUp, { capture: true });
    viewport.addEventListener("pointercancel", onUp, { capture: true });
    return () => {
      viewport.removeEventListener("pointerdown", onDown, { capture: true });
      viewport.removeEventListener("pointermove", onMove, { capture: true });
      viewport.removeEventListener("pointerup", onUp, { capture: true });
      viewport.removeEventListener("pointercancel", onUp, { capture: true });
    };
  }, [lensEngaged, triggerLensSettle, scheduleCamera, flushCamera]);



  return {
    lensEngaged,
    setLensEngaged,
    focalScreen,
    lensSettling,
    lensRadius,
    triggerLensSettle,
    panState,
    onBgPointerDown,
    onBgPointerMove,
    onBgPointerUp,
  };
}
