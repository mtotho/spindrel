
import { useParams } from "react-router-dom";
import { useAuthStore } from "@/src/stores/auth";
import { IntegrationFrame } from "@/src/components/integration/IntegrationFrame";

/**
 * Catch-all page for integration web UI sub-paths.
 *
 * Builds the iframe src from the integration ID and remaining path segments,
 * pointing at the FastAPI-served static build:
 *   /integrations/{integrationId}/ui/{path}
 */
export default function IntegrationCatchAll() {
  const { integrationId, "*": subPath } = useParams();
  const serverUrl = useAuthStore((s) => s.serverUrl);

  const src = `${serverUrl}/integrations/${integrationId}/ui/${subPath}`;

  return (
    <div style={{ flex: 1 }}>
      <IntegrationFrame src={src} />
    </div>
  );
}
