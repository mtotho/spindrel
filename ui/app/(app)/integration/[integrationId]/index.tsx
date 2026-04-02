import { View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useAuthStore } from "@/src/stores/auth";
import { IntegrationFrame } from "@/src/components/integration/IntegrationFrame";

/**
 * Index page for an integration — loads the root of the integration's web UI.
 * Handles /integration/{integrationId} (no sub-path).
 */
export default function IntegrationIndex() {
  const { integrationId } = useLocalSearchParams<{ integrationId: string }>();
  const serverUrl = useAuthStore((s) => s.serverUrl);

  const src = `${serverUrl}/integrations/${integrationId}/ui/`;

  return (
    <View style={{ flex: 1 }}>
      <IntegrationFrame src={src} />
    </View>
  );
}
