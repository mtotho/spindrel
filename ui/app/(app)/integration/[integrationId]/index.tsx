
import { getApiBase } from "@/src/api/client";
import { useParams } from "react-router-dom";
import { useAuthStore } from "@/src/stores/auth";
import { IntegrationFrame } from "@/src/components/integration/IntegrationFrame";

/**
 * Index page for an integration — loads the root of the integration's web UI.
 * Handles /integration/{integrationId} (no sub-path).
 */
export default function IntegrationIndex() {
  const { integrationId } = useParams<{ integrationId: string }>();
  const serverUrl = useAuthStore((s) => s.serverUrl);

  const src = `${getApiBase()}/integrations/${integrationId}/ui/`;

  return (
    <div style={{ flex: 1 }}>
      <IntegrationFrame src={src} />
    </div>
  );
}
