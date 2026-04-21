import { useRef, useCallback, useEffect, useState } from "react";
import { useThemeTokens } from "../../theme/tokens";

interface ResizeHandleProps {
  direction: "horizontal" | "vertical";
  onResize: (delta: number) => void;
  /** Hide the 1px divider entirely — still grabs drag events.
   *  Use when the surrounding panels already visually separate themselves. */
  invisible?: boolean;
}

/** Full-screen transparent overlay injected for the duration of a drag.
 *  Iframes (widget previews, file viewers) otherwise swallow pointermove +
 *  pointerup when the cursor crosses them, leaving the handle "stuck" to
 *  the cursor because the parent document never sees the release. A top-
 *  layer div with the resize cursor keeps all pointer events on the parent. */
function mountDragShield(cursor: string): () => void {
  const shield = document.createElement("div");
  shield.style.cssText = `
    position: fixed;
    inset: 0;
    z-index: 2147483647;
    cursor: ${cursor};
    background: transparent;
  `;
  document.body.appendChild(shield);
  return () => {
    if (shield.parentNode) shield.parentNode.removeChild(shield);
  };
}

export function ResizeHandle({ direction, onResize, invisible = false }: ResizeHandleProps) {
  const t = useThemeTokens();
  const dragging = useRef(false);
  const lastPos = useRef(0);
  const shieldTeardownRef = useRef<(() => void) | null>(null);
  const [hovered, setHovered] = useState(false);
  // Keep a ref so the move handler always calls the latest callback
  const onResizeRef = useRef(onResize);
  useEffect(() => { onResizeRef.current = onResize; });

  // Safety-belt teardown if the component unmounts mid-drag.
  useEffect(
    () => () => {
      if (shieldTeardownRef.current) {
        shieldTeardownRef.current();
        shieldTeardownRef.current = null;
      }
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    },
    [],
  );

  const endDrag = useCallback(() => {
    dragging.current = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    if (shieldTeardownRef.current) {
      shieldTeardownRef.current();
      shieldTeardownRef.current = null;
    }
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      // Left-click / primary touch / pen only. Ignore secondary buttons so
      // right-click on the divider doesn't kick off a ghost drag.
      if (e.button !== 0 && e.pointerType === "mouse") return;
      e.preventDefault();

      const cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      dragging.current = true;
      lastPos.current = direction === "horizontal" ? e.clientX : e.clientY;
      document.body.style.cursor = cursor;
      document.body.style.userSelect = "none";
      shieldTeardownRef.current = mountDragShield(cursor);

      // setPointerCapture routes every subsequent pointer event for this
      // pointerId to the handle, regardless of what element the pointer is
      // physically over — including iframes. That's the actual fix for the
      // "handle stuck to cursor after releasing over an iframe" bug.
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        // Some browsers throw if the element is not connected; fall back to
        // the document-level listeners below which still handle most cases.
      }
    },
    [direction],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      const pos = direction === "horizontal" ? e.clientX : e.clientY;
      const delta = pos - lastPos.current;
      lastPos.current = pos;
      onResizeRef.current(delta);
    },
    [direction],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        // ignored
      }
      endDrag();
    },
    [endDrag],
  );

  // pointercancel fires when the browser revokes pointer capture (system
  // gesture, tab lose-focus). Must end the drag or the handle stays "stuck".
  const onPointerCancel = useCallback(() => {
    if (!dragging.current) return;
    endDrag();
  }, [endDrag]);

  const isHorizontal = direction === "horizontal";

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: isHorizontal ? 9 : "100%",
        height: isHorizontal ? "100%" : 9,
        cursor: isHorizontal ? "col-resize" : "row-resize",
        background: "transparent",
        position: "relative",
        flexShrink: 0,
        zIndex: 10,
        touchAction: "none", // prevent browser scroll/zoom during drag
      }}
    >
      <div
        style={{
          position: "absolute",
          [isHorizontal ? "left" : "top"]: 4,
          [isHorizontal ? "width" : "height"]: 1,
          [isHorizontal ? "height" : "width"]: "100%",
          background: invisible
            ? (hovered ? `${t.accent}55` : "transparent")
            : (hovered ? t.accent : t.surfaceBorder),
          top: isHorizontal ? 0 : undefined,
          left: isHorizontal ? undefined : 0,
          transition: "background 0.15s ease, width 0.15s ease, height 0.15s ease",
          ...(hovered && isHorizontal ? { width: 2, left: 3 } : {}),
          ...(hovered && !isHorizontal ? { height: 2, top: 3 } : {}),
        }}
      />
    </div>
  );
}
