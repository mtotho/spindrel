import "../global.css";
import { useEffect } from "react";
import { View, Text, ActivityIndicator, Platform } from "react-native";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/src/stores/auth";
import { useThemeStore } from "@/src/stores/theme";
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

/** Apply or remove the `dark` class on <html> so CSS variables switch. */
function useApplyThemeClass() {
  const mode = useThemeStore((s) => s.mode);
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const el = document.documentElement;
    if (mode === "dark") {
      el.classList.add("dark");
    } else {
      el.classList.remove("dark");
    }
    // Also update theme-color meta tag
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", mode === "dark" ? "#111111" : "#fafafa");
  }, [mode]);
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const isConfigured = useAuthStore((s) => s.isConfigured);
  const mode = useThemeStore((s) => s.mode);
  const hydrated = useHydrated();
  const segments = useSegments();
  const router = useRouter();

  useApplyThemeClass();

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
    const bg = mode === "dark" ? "#111111" : "#fafafa";
    const spinnerColor = "#3b82f6";
    const textColor = mode === "dark" ? "#666666" : "#a3a3a3";
    return (
      <View style={{ flex: 1, backgroundColor: bg, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={spinnerColor} />
        <Text style={{ color: textColor, marginTop: 8, fontSize: 12 }}>Loading...</Text>
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  const mode = useThemeStore((s) => s.mode);
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <AuthGate>
          <Stack screenOptions={{ headerShown: false }}>
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="(app)" />
          </Stack>
          <StatusBar style={mode === "dark" ? "light" : "dark"} />
        </AuthGate>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
