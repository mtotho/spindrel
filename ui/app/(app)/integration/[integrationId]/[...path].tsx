import { View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useAuthStore } from "@/src/stores/auth";
import { IntegrationFrame } from "@/src/components/integration/IntegrationFrame";

/**
 * Catch-all page for integration web UIs.
 *
 * Builds the iframe src from the integration ID and remaining path segments,
 * pointing at the FastAPI-served static build:
 *   /integrations/{integrationId}/ui/{path}
 */
export default function IntegrationCatchAll() {
  const { integrationId, path } = useLocalSearchParams<{
    integrationId: string;
    path: string[];
  }>();
  const serverUrl = useAuthStore((s) => s.serverUrl);

  // Build the iframe src URL
  const subPath = Array.isArray(path) ? path.join("/") : path || "";
  const src = `${serverUrl}/integrations/${integrationId}/ui/${subPath}`;

  return (
    <View style={{ flex: 1 }}>
      <IntegrationFrame src={src} />
    </View>
  );
}
