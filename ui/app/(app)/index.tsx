import { useResponsiveColumns } from "@/src/hooks/useResponsiveColumns";
import { HomeGrid } from "@/src/components/home/HomeGrid";
import { HomeChannelsList } from "@/src/components/home/HomeChannelsList";

/**
 * Root route `/`. Desktop → full-screen palette-as-grid.
 * Mobile → vertical channels list (the hamburger already surfaces the palette).
 */
export default function Home() {
  const columns = useResponsiveColumns();
  if (columns === "single") return <HomeChannelsList />;
  return <HomeGrid />;
}
