import { Navigate, useLocation } from "react-router-dom";

/**
 * Legacy `/canvas` route. `/spatial` is the canonical spatial canvas URL.
 */
export default function CanvasPage() {
  const location = useLocation();
  return <Navigate to={`/spatial${location.search}${location.hash}`} replace />;
}
