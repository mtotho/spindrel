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
    // Also update theme-color meta tag (created by useWebViewportFix if missing)
    let meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) {
      meta = document.createElement("meta");
      (meta as HTMLMetaElement).name = "theme-color";
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", mode === "dark" ? "#111111" : "#fafafa");
  }, [mode]);
}

/**
 * Fix mobile-web viewport, safe areas, and iOS keyboard behavior.
 *
 * +html.tsx customizations don't survive `expo export --output single`, so the
 * production HTML uses Expo's default template which lacks viewport-fit=cover,
 * safe area padding, and the visualViewport keyboard handler.  We inject all
 * of that client-side here so it works regardless of how the HTML is generated.
 */
function useWebViewportFix() {
  useEffect(() => {
    if (Platform.OS !== "web") return;

    // 1. Fix viewport meta — add viewport-fit=cover so env(safe-area-inset-*)
    //    returns real values, disable user zoom to prevent iOS double-tap zoom.
    const vp = document.querySelector('meta[name="viewport"]');
    if (vp) {
      vp.setAttribute(
        "content",
        "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover"
      );
    }

    // 2. Ensure all required meta tags and links exist.
    //    +html.tsx provides these for the dev server but expo export drops them.
    const ensureMeta = (name: string, content: string) => {
      if (!document.querySelector(`meta[name="${name}"]`)) {
        const m = document.createElement("meta");
        m.name = name;
        m.content = content;
        document.head.appendChild(m);
      }
    };
    ensureMeta("apple-mobile-web-app-capable", "yes");
    ensureMeta("apple-mobile-web-app-status-bar-style", "black-translucent");
    ensureMeta("theme-color", "#111111");

    const ensureLink = (rel: string, href: string) => {
      if (!document.querySelector(`link[rel="${rel}"][href="${href}"]`)) {
        const l = document.createElement("link");
        l.rel = rel;
        l.href = href;
        document.head.appendChild(l);
      }
    };
    ensureLink("manifest", "/manifest.json");
    ensureLink("apple-touch-icon", "/assets/images/icon-192.png");

    // 3. Style #root: fixed position, safe area padding, full viewport height.
    const root = document.getElementById("root");
    if (root) {
      Object.assign(root.style, {
        position: "fixed",
        top: "0",
        left: "0",
        right: "0",
        height: "100dvh",
        overflow: "hidden",
        paddingTop: "env(safe-area-inset-top, 0px)",
        paddingBottom: "env(safe-area-inset-bottom, 0px)",
        paddingLeft: "env(safe-area-inset-left, 0px)",
        paddingRight: "env(safe-area-inset-right, 0px)",
      });
    }

    // 4. VisualViewport handler — the only reliable way to handle the iOS
    //    keyboard.  CSS dvh doesn't shrink for the keyboard, only for the
    //    address bar.  And on iOS, focusing an input scrolls the layout
    //    viewport, shifting fixed elements out of view (offsetTop > 0).
    const vv = window.visualViewport;
    if (!vv || !root) return;

    const initialHeight = vv.height;
    let pending = false;

    function sync() {
      pending = false;
      if (!root || !vv) return;
      // Track visual viewport position — iOS scrolls the layout viewport
      // when the keyboard opens, pushing fixed elements behind the status bar.
      root.style.top = vv.offsetTop + "px";
      root.style.height = vv.height + "px";

      // When keyboard is open (viewport significantly smaller than initial),
      // clear bottom safe area — the keyboard replaces the home indicator.
      if (vv.height < initialHeight * 0.85) {
        root.style.paddingBottom = "0px";
      } else {
        root.style.paddingBottom = "env(safe-area-inset-bottom, 0px)";
      }
    }

    function onViewportChange() {
      if (!pending) {
        pending = true;
        requestAnimationFrame(sync);
      }
    }

    vv.addEventListener("resize", onViewportChange);
    vv.addEventListener("scroll", onViewportChange);

    return () => {
      vv.removeEventListener("resize", onViewportChange);
      vv.removeEventListener("scroll", onViewportChange);
    };
  }, []);
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const isConfigured = useAuthStore((s) => s.isConfigured);
  const mode = useThemeStore((s) => s.mode);
  const hydrated = useHydrated();
  const segments = useSegments();
  const router = useRouter();

  useApplyThemeClass();
  useWebViewportFix();

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
