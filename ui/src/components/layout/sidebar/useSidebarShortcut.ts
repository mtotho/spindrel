import { useEffect } from "react";
import { useUIStore } from "../../../stores/ui";

/** ⌘\ / Ctrl+\ toggles the desktop sidebar panel (not the rail). */
export function useSidebarShortcut() {
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "\\") {
        e.preventDefault();
        toggleSidebar();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleSidebar]);
}
