import { useCallback, useEffect, useRef, useState } from "react";
import type { SpatialNode } from "../../api/hooks/useWorkspaceSpatial";
import {
  CAMERA_STORAGE_KEY,
  DEFAULT_CAMERA,
  MAX_SCALE,
  MIN_SCALE,
  clampCamera,
  loadStoredCamera,
  type Camera,
} from "./spatialGeometry";

const CAMERA_IDLE_COMMIT_MS = 140;
const CAMERA_MOVING_CLASS_MS = 520;

export function cameraTransform(camera: Camera): string {
  return `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
}

export function useSpatialCamera({
  diving,
  nodes,
}: {
  diving: boolean;
  nodes: SpatialNode[] | undefined;
}) {
  const [camera, setCamera] = useState<Camera>(() => loadStoredCamera());
  const viewportRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef(camera);
  const viewportRectRef = useRef({ left: 0, top: 0, width: 0, height: 0 });
  const pendingCameraRef = useRef<Camera | null>(null);
  const cameraRafRef = useRef<number | null>(null);
  const cameraCommitTimerRef = useRef<number | null>(null);
  const cameraMovingTimerRef = useRef<number | null>(null);
  const [cameraMoving, setCameraMoving] = useState(false);
  const [viewportSize, setViewportSize] = useState<{ w: number; h: number }>({
    w: 0,
    h: 0,
  });

  useEffect(() => {
    if (diving) return;
    const id = window.setTimeout(() => {
      try {
        localStorage.setItem(CAMERA_STORAGE_KEY, JSON.stringify(camera));
      } catch {
        /* quota / disabled storage — silently skip */
      }
    }, 180);
    return () => window.clearTimeout(id);
  }, [camera, diving]);

  const applyCameraTransform = useCallback((next: Camera) => {
    const world = worldRef.current;
    if (world) world.style.transform = cameraTransform(next);
  }, []);

  const markCameraMoving = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.classList.add("spatial-camera-moving");
    setCameraMoving(true);
    if (cameraMovingTimerRef.current !== null) {
      window.clearTimeout(cameraMovingTimerRef.current);
    }
    cameraMovingTimerRef.current = window.setTimeout(() => {
      viewport.classList.remove("spatial-camera-moving");
      setCameraMoving(false);
      cameraMovingTimerRef.current = null;
    }, CAMERA_MOVING_CLASS_MS);
  }, []);

  const commitCameraState = useCallback((next: Camera) => {
    const clamped = clampCamera(next);
    cameraRef.current = clamped;
    pendingCameraRef.current = null;
    applyCameraTransform(clamped);
    setCamera((curr) =>
      curr.x === clamped.x && curr.y === clamped.y && curr.scale === clamped.scale
        ? curr
        : clamped,
    );
  }, [applyCameraTransform]);

  const scheduleCamera = useCallback((next: Camera, commit: "idle" | "immediate" = "idle") => {
    const clamped = clampCamera(next);
    cameraRef.current = clamped;
    pendingCameraRef.current = clamped;

    if (cameraRafRef.current === null) {
      cameraRafRef.current = window.requestAnimationFrame(() => {
        cameraRafRef.current = null;
        const pending = pendingCameraRef.current;
        if (pending) applyCameraTransform(pending);
      });
    }

    if (commit === "immediate") {
      if (cameraCommitTimerRef.current !== null) {
        window.clearTimeout(cameraCommitTimerRef.current);
        cameraCommitTimerRef.current = null;
      }
      commitCameraState(clamped);
      return;
    }

    markCameraMoving();
    if (cameraCommitTimerRef.current !== null) {
      window.clearTimeout(cameraCommitTimerRef.current);
    }
    cameraCommitTimerRef.current = window.setTimeout(() => {
      cameraCommitTimerRef.current = null;
      commitCameraState(cameraRef.current);
    }, CAMERA_IDLE_COMMIT_MS);
  }, [applyCameraTransform, commitCameraState, markCameraMoving]);

  const flushCamera = useCallback(() => {
    if (cameraCommitTimerRef.current !== null) {
      window.clearTimeout(cameraCommitTimerRef.current);
      cameraCommitTimerRef.current = null;
    }
    commitCameraState(cameraRef.current);
  }, [commitCameraState]);

  useEffect(() => {
    cameraRef.current = camera;
    applyCameraTransform(camera);
  }, [camera, applyCameraTransform]);

  useEffect(() => {
    return () => {
      if (cameraRafRef.current !== null) window.cancelAnimationFrame(cameraRafRef.current);
      if (cameraCommitTimerRef.current !== null) window.clearTimeout(cameraCommitTimerRef.current);
      if (cameraMovingTimerRef.current !== null) window.clearTimeout(cameraMovingTimerRef.current);
    };
  }, []);

  const updateViewportMetrics = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    viewportRectRef.current = {
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
    };
    setViewportSize((curr) =>
      curr.w === r.width && curr.h === r.height ? curr : { w: r.width, h: r.height },
    );
  }, []);

  const pointerToWorld = useCallback((clientX: number, clientY: number) => {
    const rect = viewportRectRef.current;
    const c = cameraRef.current;
    if (!rect.width || !rect.height) return null;
    return {
      x: (clientX - rect.left - c.x) / c.scale,
      y: (clientY - rect.top - c.y) / c.scale,
    };
  }, []);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    updateViewportMetrics();
    const ro = new ResizeObserver(updateViewportMetrics);
    ro.observe(el);
    return () => ro.disconnect();
  }, [updateViewportMetrics]);

  const zoomAroundPoint = useCallback(
    (factor: number, cx: number, cy: number) => {
      const c = cameraRef.current;
      const newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, c.scale * factor));
      const k = newScale / c.scale;
      scheduleCamera({
        scale: newScale,
        x: cx - (cx - c.x) * k,
        y: cy - (cy - c.y) * k,
      });
    },
    [scheduleCamera],
  );

  const fitAllNodes = useCallback(() => {
    const rect = viewportRectRef.current;
    if (!rect.width || !rect.height) return;
    const list = nodes ?? [];
    if (list.length === 0) {
      scheduleCamera(DEFAULT_CAMERA, "immediate");
      return;
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of list) {
      if (n.world_x < minX) minX = n.world_x;
      if (n.world_y < minY) minY = n.world_y;
      if (n.world_x + n.world_w > maxX) maxX = n.world_x + n.world_w;
      if (n.world_y + n.world_h > maxY) maxY = n.world_y + n.world_h;
    }
    const bboxW = Math.max(1, maxX - minX);
    const bboxH = Math.max(1, maxY - minY);
    const margin = 0.08;
    const targetScale = Math.max(
      MIN_SCALE,
      Math.min(
        MAX_SCALE,
        Math.min(
          rect.width / (bboxW * (1 + margin * 2)),
          rect.height / (bboxH * (1 + margin * 2)),
        ),
      ),
    );
    const cx = minX + bboxW / 2;
    const cy = minY + bboxH / 2;
    scheduleCamera({
      scale: targetScale,
      x: rect.width / 2 - cx * targetScale,
      y: rect.height / 2 - cy * targetScale,
    }, "immediate");
  }, [nodes, scheduleCamera]);

  return {
    camera,
    viewportRef,
    worldRef,
    cameraRef,
    viewportRectRef,
    cameraMoving,
    viewportSize,
    scheduleCamera,
    flushCamera,
    pointerToWorld,
    zoomAroundPoint,
    fitAllNodes,
  };
}
