import { Navigate, useSearchParams } from "react-router-dom";
import { HomeDashboard } from "@/src/components/home/HomeDashboard";

/**
 * Root route `/`. Traditional responsive home dashboard for desktop and
 * mobile. Spatial deep-link params are forwarded to the canonical `/spatial`
 * route so old canvas entry points keep working.
 */
export default function Home() {
  const [searchParams] = useSearchParams();
  if (searchParams.has("channel") || searchParams.has("node")) {
    const query = searchParams.toString();
    return <Navigate to={`/spatial${query ? `?${query}` : ""}`} replace />;
  }
  return <HomeDashboard />;
}
