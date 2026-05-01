import { useSearchParams } from "react-router-dom";
import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { HomeDashboard } from "@/src/components/home/HomeDashboard";
import { SpatialCanvas } from "@/src/components/spatial-canvas/SpatialCanvas";

/**
 * Canonical `/spatial` route. The full spatial canvas remains desktop-first;
 * mobile falls back to the normal home dashboard so deep links stay usable.
 */
export default function SpatialPage() {
  const columns = useResponsiveColumns();
  const [searchParams] = useSearchParams();
  if (columns === "single") return <HomeDashboard />;
  return (
    <div className="relative flex-1 min-h-0">
      <SpatialCanvas initialFlyToChannelId={searchParams.get("channel")} initialFlyToNodeId={searchParams.get("node")} />
    </div>
  );
}
