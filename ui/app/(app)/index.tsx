import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { HomeChannelsList } from "@/src/components/home/HomeChannelsList";
import { SpatialCanvas } from "@/src/components/spatial-canvas/SpatialCanvas";

/**
 * Root route `/`. Desktop → spatial canvas (workspace-scope infinite plane
 * of channel + widget tiles, see `Track - Spatial Canvas`). Mobile keeps
 * the vertical channels list (canvas is desktop-only through P11).
 */
export default function Home() {
  const columns = useResponsiveColumns();
  if (columns === "single") return <HomeChannelsList />;
  return (
    <div className="relative flex-1 min-h-0">
      <SpatialCanvas />
    </div>
  );
}
