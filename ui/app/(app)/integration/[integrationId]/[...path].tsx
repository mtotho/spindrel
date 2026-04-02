import { View } from "react-native";
import { useLocalSearchParams } from "expo-router";
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
  const params = useLocalSearchParams();
  const integrationId = params.integrationId as string;
  const serverUrl = useAuthStore((s) => s.serverUrl);

  // path can be string, string[], or undefined depending on Expo Router
  const rawPath = params.path;
  let subPath = "";
  if (Array.isArray(rawPath)) {
    subPath = rawPath.join("/");
  } else if (typeof rawPath === "string") {
    subPath = rawPath;
  }

  const src = `${serverUrl}/integrations/${integrationId}/ui/${subPath}`;

  return (
    <View style={{ flex: 1 }}>
      <IntegrationFrame src={src} />
    </View>
  );
}
