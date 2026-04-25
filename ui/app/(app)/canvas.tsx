import { SpatialCanvas } from "@/src/components/spatial-canvas/SpatialCanvas";

/**
 * Dedicated `/canvas` route — always renders the spatial canvas regardless
 * of viewport size. Lets mobile reach the canvas for testing while `/`
 * stays responsive (mobile = channels list, desktop = canvas).
 */
export default function CanvasPage() {
  return (
    <div className="relative flex-1 min-h-0">
      <SpatialCanvas />
    </div>
  );
}
