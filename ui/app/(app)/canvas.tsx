import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { MobileHub } from "@/src/components/home/MobileHub";
import { SpatialCanvas } from "@/src/components/spatial-canvas/SpatialCanvas";

/**
 * Dedicated `/canvas` route. Mirrors `/` responsive behavior — mobile gets
 * the sectioned home hub (the spatial canvas is desktop-only), desktop
 * gets the canvas. Keeps deep links and "Open canvas" affordances safe to
 * follow regardless of viewport.
 */
export default function CanvasPage() {
  const columns = useResponsiveColumns();
  if (columns === "single") return <MobileHub />;
  return (
    <div className="relative flex-1 min-h-0">
      <SpatialCanvas />
    </div>
  );
}
