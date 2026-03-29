import { useRef, useCallback } from "react";
import { useThemeTokens } from "../../theme/tokens";

interface ResizeHandleProps {
  direction: "horizontal" | "vertical";
  onResize: (delta: number) => void;
}

export function ResizeHandle({ direction, onResize }: ResizeHandleProps) {
  const t = useThemeTokens();
  const dragging = useRef(false);
  const lastPos = useRef(0);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      lastPos.current = direction === "horizontal" ? e.clientX : e.clientY;

      const onMouseMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const pos = direction === "horizontal" ? ev.clientX : ev.clientY;
        const delta = pos - lastPos.current;
        lastPos.current = pos;
        onResize(delta);
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
      document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
    },
    [direction, onResize]
  );

  const isHorizontal = direction === "horizontal";

  return (
    <div
      onMouseDown={onMouseDown}
      style={{
        width: isHorizontal ? 5 : "100%",
        height: isHorizontal ? "100%" : 5,
        cursor: isHorizontal ? "col-resize" : "row-resize",
        background: "transparent",
        position: "relative",
        flexShrink: 0,
        zIndex: 10,
      }}
    >
      <div
        style={{
          position: "absolute",
          [isHorizontal ? "left" : "top"]: 2,
          [isHorizontal ? "width" : "height"]: 1,
          [isHorizontal ? "height" : "width"]: "100%",
          background: t.surfaceBorder,
          top: isHorizontal ? 0 : undefined,
          left: isHorizontal ? undefined : 0,
        }}
      />
    </div>
  );
}
