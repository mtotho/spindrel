import { useEffect } from "react";
import { useUIStore } from "../stores/ui";

/** Ctrl+Shift+Space (Cmd+Shift+Space on mac) toggles the Spatial Canvas
 *  overlay. The overlay mounts above the route Outlet without unmounting it,
 *  so active SSE streams and route state survive open/close. */
export function useSpatialOverlayShortcut() {
  const toggle = useUIStore((s) => s.toggleSpatialOverlay);
  const close = useUIStore((s) => s.closeSpatialOverlay);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === "Space") {
        e.preventDefault();
        toggle();
        return;
      }
      if (e.key === "Escape" && useUIStore.getState().spatialOverlayOpen) {
        close();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggle, close]);
}
