import "../global.css";
import { useEffect } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/src/stores/auth";
import { useHydrated } from "@/src/hooks/useHydrated";

export { ErrorBoundary } from "expo-router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function AuthGate({ children }: { children: React.ReactNode }) {
  const isConfigured = useAuthStore((s) => s.isConfigured);
  const hydrated = useHydrated();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (!hydrated) return;

    const inAuthGroup = segments[0] === "(auth)";

    if (!isConfigured && !inAuthGroup) {
      router.replace("/(auth)/login");
    } else if (isConfigured && inAuthGroup) {
      router.replace("/(app)");
    }
  }, [isConfigured, hydrated, segments]);

  if (!hydrated) {
    return (
      <View style={{ flex: 1, backgroundColor: "#111111", alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color="#3b82f6" />
        <Text style={{ color: "#666666", marginTop: 8, fontSize: 12 }}>Loading...</Text>
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <AuthGate>
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="(app)" />
          </Stack>
          <StatusBar style="light" />
        </AuthGate>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
