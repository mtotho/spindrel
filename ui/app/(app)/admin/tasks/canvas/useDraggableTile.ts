import { useCallback, useRef, useState } from "react";

export interface TilePos { x: number; y: number }

interface Options {
  position: TilePos;
  onChange: (pos: TilePos) => void;
}

/**
 * useDraggableTile — pointer-to-world drag for absolutely-positioned tiles
 * on the canvas plane. No zoom/scale yet — direct pixel mapping.
 *
 * Returns:
 *   - dragHandleProps: spread onto the drag handle (header)
 *   - tileStyle: position + transform for the outer tile element
 *   - dragging: true while a pointer drag is in progress
 */
export function useDraggableTile({ position, onChange }: Options) {
  const [dragging, setDragging] = useState(false);
  const grabOffset = useRef<{ dx: number; dy: number } | null>(null);
  const transient = useRef<TilePos | null>(null);
  const [, force] = useState(0);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    const target = e.currentTarget;
    const tileEl = target.closest("[data-canvas-tile]") as HTMLElement | null;
    if (!tileEl) return;
    const rect = tileEl.getBoundingClientRect();
    grabOffset.current = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
    transient.current = position;
    target.setPointerCapture(e.pointerId);
    setDragging(true);
    e.preventDefault();
  }, [position]);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (!grabOffset.current) return;
    const target = e.currentTarget;
    const tileEl = target.closest("[data-canvas-tile]") as HTMLElement | null;
    if (!tileEl) return;
    const planeEl = tileEl.parentElement;
    if (!planeEl) return;
    const planeRect = planeEl.getBoundingClientRect();
    const x = e.clientX - planeRect.left - grabOffset.current.dx;
    const y = e.clientY - planeRect.top - grabOffset.current.dy;
    transient.current = { x: Math.max(0, x), y: Math.max(0, y) };
    force((n) => n + 1);
  }, []);

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (!grabOffset.current) return;
    const final = transient.current ?? position;
    grabOffset.current = null;
    transient.current = null;
    setDragging(false);
    onChange(final);
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* noop */ }
  }, [onChange, position]);

  const livePos = transient.current ?? position;

  return {
    dragHandleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      style: { cursor: dragging ? "grabbing" : "grab", touchAction: "none" } as const,
    },
    tileStyle: {
      position: "absolute" as const,
      left: livePos.x,
      top: livePos.y,
      zIndex: dragging ? 30 : 5,
    },
    dragging,
  };
}
