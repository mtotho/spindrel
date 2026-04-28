import { useSearchParams } from "react-router-dom";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { MobileHub } from "@/src/components/home/MobileHub";
import { SpatialCanvas } from "@/src/components/spatial-canvas/SpatialCanvas";

/**
 * Root route `/`. Desktop → spatial canvas (workspace-scope infinite plane
 * of channel + widget tiles, see `Track - Spatial Canvas`). Mobile → the
 * sectioned mobile hub (`MobileHub`) — channel list plus alert /
 * upcoming / memory / pinned-widget / bloat sections.
 */
export default function Home() {
  const columns = useResponsiveColumns();
  const [searchParams] = useSearchParams();
  if (columns === "single") return <MobileHub />;
  return (
    <div className="relative flex-1 min-h-0">
      <SpatialCanvas initialFlyToChannelId={searchParams.get("channel")} initialFlyToNodeId={searchParams.get("node")} />
    </div>
  );
}
