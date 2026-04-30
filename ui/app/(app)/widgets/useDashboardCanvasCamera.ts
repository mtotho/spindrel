import { useCallback, useEffect, useRef, useState } from "react";
import {
  DASHBOARD_CAMERA_MAX_SCALE,
  DASHBOARD_CAMERA_MIN_SCALE,
  clampDashboardCamera,
  type DashboardCamera,
} from "@/src/lib/channelDashboardFreeform";

const CAMERA_IDLE_COMMIT_MS = 120;
const DEFAULT_CAMERA: DashboardCamera = { x: 0, y: 0, scale: 1 };

function storageKey(slug: string): string {
  return `channel-dashboard-camera:${slug}`;
}

function loadStoredCamera(slug: string): DashboardCamera {
  if (typeof window === "undefined") return DEFAULT_CAMERA;
  try {
    const raw = window.localStorage.getItem(storageKey(slug));
    if (!raw) return DEFAULT_CAMERA;
    return clampDashboardCamera(JSON.parse(raw) as DashboardCamera);
  } catch {
    return DEFAULT_CAMERA;
  }
}

export function dashboardCameraTransform(camera: DashboardCamera): string {
  return `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
}

export function useDashboardCanvasCamera(slug: string) {
  const [camera, setCamera] = useState<DashboardCamera>(() => loadStoredCamera(slug));
  const [viewportSize, setViewportSize] = useState({ w: 0, h: 0 });
  const viewportRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef(camera);
  const viewportRectRef = useRef({ left: 0, top: 0, width: 0, height: 0 });
  const pendingCameraRef = useRef<DashboardCamera | null>(null);
  const cameraRafRef = useRef<number | null>(null);
  const cameraCommitTimerRef = useRef<number | null>(null);

  const applyCameraTransform = useCallback((next: DashboardCamera) => {
    if (worldRef.current) worldRef.current.style.transform = dashboardCameraTransform(next);
  }, []);

  const commitCameraState = useCallback((next: DashboardCamera) => {
    const clamped = clampDashboardCamera(next);
    cameraRef.current = clamped;
    pendingCameraRef.current = null;
    applyCameraTransform(clamped);
    setCamera((curr) =>
      curr.x === clamped.x && curr.y === clamped.y && curr.scale === clamped.scale
        ? curr
        : clamped,
    );
  }, [applyCameraTransform]);

  const scheduleCamera = useCallback((next: DashboardCamera, commit: "idle" | "immediate" = "idle") => {
    const clamped = clampDashboardCamera(next);
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
      if (cameraCommitTimerRef.current !== null) window.clearTimeout(cameraCommitTimerRef.current);
      cameraCommitTimerRef.current = null;
      commitCameraState(clamped);
      return;
    }

    if (cameraCommitTimerRef.current !== null) window.clearTimeout(cameraCommitTimerRef.current);
    cameraCommitTimerRef.current = window.setTimeout(() => {
      cameraCommitTimerRef.current = null;
      commitCameraState(cameraRef.current);
    }, CAMERA_IDLE_COMMIT_MS);
  }, [applyCameraTransform, commitCameraState]);

  const updateViewportMetrics = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    viewportRectRef.current = { left: r.left, top: r.top, width: r.width, height: r.height };
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

  const zoomAroundPoint = useCallback((factor: number, clientX: number, clientY: number) => {
    const rect = viewportRectRef.current;
    const c = cameraRef.current;
    const nextScale = Math.max(DASHBOARD_CAMERA_MIN_SCALE, Math.min(DASHBOARD_CAMERA_MAX_SCALE, c.scale * factor));
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    const k = nextScale / c.scale;
    scheduleCamera({
      scale: nextScale,
      x: localX - (localX - c.x) * k,
      y: localY - (localY - c.y) * k,
    });
  }, [scheduleCamera]);

  useEffect(() => {
    cameraRef.current = camera;
    applyCameraTransform(camera);
  }, [camera, applyCameraTransform]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    updateViewportMetrics();
    const ro = new ResizeObserver(updateViewportMetrics);
    ro.observe(el);
    window.addEventListener("resize", updateViewportMetrics);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", updateViewportMetrics);
    };
  }, [updateViewportMetrics]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      try {
        window.localStorage.setItem(storageKey(slug), JSON.stringify(camera));
      } catch {
        /* storage disabled */
      }
    }, 160);
    return () => window.clearTimeout(id);
  }, [camera, slug]);

  useEffect(() => {
    return () => {
      if (cameraRafRef.current !== null) window.cancelAnimationFrame(cameraRafRef.current);
      if (cameraCommitTimerRef.current !== null) window.clearTimeout(cameraCommitTimerRef.current);
    };
  }, []);

  return {
    camera,
    cameraRef,
    viewportRef,
    worldRef,
    viewportRectRef,
    viewportSize,
    scheduleCamera,
    pointerToWorld,
    zoomAroundPoint,
    updateViewportMetrics,
  };
}
