import { Navigate, useSearchParams } from "react-router-dom";
import { attentionDeckHref } from "@/src/lib/hubRoutes";

export default function HubCommandCenterPage() {
  const [searchParams] = useSearchParams();
  const requestedItemId = searchParams.get("item");
  const requestedMode = searchParams.get("mode");
  return <Navigate to={attentionDeckHref({ itemId: requestedItemId, mode: requestedMode === "runs" ? "runs" : null })} replace />;
}
