import { useRef, useCallback, useEffect, useState } from "react";
import { useThemeTokens } from "../../theme/tokens";

interface ResizeHandleProps {
  direction: "horizontal" | "vertical";
  onResize: (delta: number) => void;
  /** Hide the 1px divider entirely — still grabs drag events.
   *  Use when the surrounding panels already visually separate themselves. */
  invisible?: boolean;
}

export function ResizeHandle({ direction, onResize, invisible = false }: ResizeHandleProps) {
  const t = useThemeTokens();
  const dragging = useRef(false);
  const lastPos = useRef(0);
  const [hovered, setHovered] = useState(false);
  // Keep a ref so the move handler always calls the latest callback
  const onResizeRef = useRef(onResize);
  useEffect(() => { onResizeRef.current = onResize; });

  const startDrag = useCallback(
    (startPos: number) => {
      dragging.current = true;
      lastPos.current = startPos;
      document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
    },
    [direction],
  );

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      startDrag(direction === "horizontal" ? e.clientX : e.clientY);

      const onMouseMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const pos = direction === "horizontal" ? ev.clientX : ev.clientY;
        const delta = pos - lastPos.current;
        lastPos.current = pos;
        onResizeRef.current(delta);
      };

      const onMouseUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [direction, startDrag],
  );

  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (e.touches.length !== 1) return;
      const touch = e.touches[0];
      startDrag(direction === "horizontal" ? touch.clientX : touch.clientY);

      const onTouchMove = (ev: TouchEvent) => {
        if (!dragging.current || ev.touches.length !== 1) return;
        ev.preventDefault(); // prevent scroll while dragging
        const pos = direction === "horizontal" ? ev.touches[0].clientX : ev.touches[0].clientY;
        const delta = pos - lastPos.current;
        lastPos.current = pos;
        onResizeRef.current(delta);
      };

      const onTouchEnd = () => {
        dragging.current = false;
        document.removeEventListener("touchmove", onTouchMove);
        document.removeEventListener("touchend", onTouchEnd);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.addEventListener("touchmove", onTouchMove, { passive: false });
      document.addEventListener("touchend", onTouchEnd);
    },
    [direction, startDrag],
  );

  const isHorizontal = direction === "horizontal";

  return (
    <div
      onMouseDown={onMouseDown}
      onTouchStart={onTouchStart}
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
