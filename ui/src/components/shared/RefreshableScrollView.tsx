import React, { useRef, useCallback } from "react";
import { useThemeTokens } from "../../theme/tokens";

const THRESHOLD = 70;

interface Props {
  refreshing: boolean;
  onRefresh: () => void;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
  contentContainerStyle?: React.CSSProperties;
}

export function RefreshableScrollView({
  refreshing,
  onRefresh,
  children,
  style,
  className,
  contentContainerStyle,
}: Props) {
  const t = useThemeTokens();
  const outerRef = useRef<HTMLDivElement>(null);
  const pullY = useRef(0);
  const startY = useRef(0);
  const pulling = useRef(false);
  const indicatorRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const refreshingRef = useRef(false);
  refreshingRef.current = refreshing;

  const resetVisuals = useCallback(() => {
    if (indicatorRef.current) {
      indicatorRef.current.style.height = "0px";
      indicatorRef.current.style.opacity = "0";
    }
    if (contentRef.current) {
      contentRef.current.style.transform = "translateY(0)";
    }
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (refreshingRef.current) return;
      const el = outerRef.current;
      if (!el || el.scrollTop > 0) return;
      startY.current = e.clientY;
      pullY.current = 0;
      pulling.current = true;
    },
    []
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!pulling.current) return;
      const dy = e.clientY - startY.current;
      if (dy <= 0) {
        pullY.current = 0;
        resetVisuals();
        return;
      }
      // Dampen the pull (50%)
      const damped = Math.min(dy * 0.5, THRESHOLD * 2);
      pullY.current = damped;

      if (indicatorRef.current) {
        indicatorRef.current.style.height = `${Math.min(damped, THRESHOLD)}px`;
        indicatorRef.current.style.opacity = String(
          Math.min(damped / THRESHOLD, 1)
        );
      }
      if (contentRef.current) {
        contentRef.current.style.transform = `translateY(${damped}px)`;
      }
    },
    [resetVisuals]
  );

  const onPointerUp = useCallback(() => {
    if (!pulling.current) return;
    pulling.current = false;

    if (pullY.current >= THRESHOLD && !refreshingRef.current) {
      // Snap to refreshing position
      if (indicatorRef.current) {
        indicatorRef.current.style.height = `${THRESHOLD}px`;
        indicatorRef.current.style.opacity = "1";
      }
      if (contentRef.current) {
        contentRef.current.style.transition = "transform 0.2s ease";
        contentRef.current.style.transform = `translateY(${THRESHOLD}px)`;
        // Remove transition after animation
        setTimeout(() => {
          if (contentRef.current) contentRef.current.style.transition = "";
        }, 200);
      }
      onRefresh();
    } else {
      // Snap back
      if (contentRef.current) {
        contentRef.current.style.transition = "transform 0.2s ease";
        contentRef.current.style.transform = "translateY(0)";
        setTimeout(() => {
          if (contentRef.current) contentRef.current.style.transition = "";
        }, 200);
      }
      resetVisuals();
    }
    pullY.current = 0;
  }, [onRefresh, resetVisuals]);

  // Reset visuals when refreshing finishes
  const prevRefreshing = useRef(refreshing);
  if (prevRefreshing.current && !refreshing) {
    // Schedule reset after render
    requestAnimationFrame(() => {
      if (contentRef.current) {
        contentRef.current.style.transition = "transform 0.2s ease";
        contentRef.current.style.transform = "translateY(0)";
        setTimeout(() => {
          if (contentRef.current) contentRef.current.style.transition = "";
        }, 200);
      }
      resetVisuals();
    });
  }
  prevRefreshing.current = refreshing;

  return (
    <div
      ref={outerRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className={className}
      style={{
        display: "block",
        flex: 1,
        overflowY: "auto",
        overflowX: "hidden",
        position: "relative",
        WebkitOverflowScrolling: "touch",
        ...(typeof style === "object" && !Array.isArray(style) ? style : {}),
      }}
    >
      {/* Pull indicator */}
      <div
        ref={indicatorRef}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 0,
          opacity: 0,
          display: "flex", flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          zIndex: 10,
        }}
      >
        <div className="chat-spinner" />
      </div>

      {/* Content wrapper */}
      <div
        ref={contentRef}
        style={{
          willChange: "transform",
          ...(typeof contentContainerStyle === "object" &&
          !Array.isArray(contentContainerStyle)
            ? contentContainerStyle
            : {}),
        }}
      >
        {children}
      </div>
    </div>
  );
}
