import { View, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { useWorkspaces } from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";

/**
 * Single workspace mode: redirect to the default workspace's detail page.
 */
export default function WorkspacesScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: workspaces, isLoading } = useWorkspaces();

  useEffect(() => {
    if (!isLoading && workspaces?.[0]) {
      router.replace(`/admin/workspaces/${workspaces[0].id}` as any);
    }
  }, [isLoading, workspaces, router]);

  return (
    <View className="flex-1 bg-surface items-center justify-center">
      <ActivityIndicator color={t.accent} />
    </View>
  );
}
