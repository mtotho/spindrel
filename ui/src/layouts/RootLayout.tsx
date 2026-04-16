import { useEffect, Suspense } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/src/stores/auth";
import { useThemeStore } from "@/src/stores/theme";
import { useHydrated } from "@/src/hooks/useHydrated";
import { Spinner } from "@/src/components/shared/Spinner";

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
    const el = document.documentElement;
    if (mode === "dark") {
      el.classList.add("dark");
    } else {
      el.classList.remove("dark");
    }
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
 * Mobile-web viewport: iOS keyboard handling.
 *
 * Base layout (position, height, safe-area padding) is set via CSS on #root
 * in global.css using 100dvh — this tracks the visible viewport correctly on
 * mobile (no bottom cutoff from browser chrome). Only when the iOS keyboard
 * opens do we override to pixel-based height so the app shrinks above the
 * keyboard.
 */
function useWebViewportFix() {
  useEffect(() => {
    const root = document.getElementById("root");
    const vv = window.visualViewport;
    if (!root || !vv) return;

    const initialHeight = vv.height;
    let pending = false;
    let keyboardOpen = false;

    function sync() {
      pending = false;
      if (!root || !vv) return;

      const isKeyboard = vv.height < initialHeight * 0.85;

      if (isKeyboard) {
        root.style.top = vv.offsetTop + "px";
        root.style.height = vv.height + "px";
        root.style.paddingBottom = "0px";
        keyboardOpen = true;
      } else if (keyboardOpen) {
        root.style.top = "";
        root.style.height = "";
        root.style.paddingBottom = "";
        keyboardOpen = false;
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

const AUTH_PATHS = ["/login", "/setup"];

function AuthGate({ children }: { children: React.ReactNode }) {
  const isConfigured = useAuthStore((s) => s.isConfigured);
  const mode = useThemeStore((s) => s.mode);
  const hydrated = useHydrated();
  const location = useLocation();
  const navigate = useNavigate();

  useApplyThemeClass();
  useWebViewportFix();

  useEffect(() => {
    if (!hydrated) return;

    const inAuth = AUTH_PATHS.some((p) => location.pathname.startsWith(p));

    if (!isConfigured && !inAuth) {
      navigate("/login", { replace: true });
    } else if (isConfigured && inAuth) {
      navigate("/", { replace: true });
    }
  }, [isConfigured, hydrated, location.pathname, navigate]);

  if (!hydrated) {
    const bg = mode === "dark" ? "#111111" : "#fafafa";
    return (
      <div
        style={{
          display: "flex", flexDirection: "column",
          flex: 1,
          backgroundColor: bg,
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
        }}
      >
        <Spinner size={24} />
        <span style={{ color: mode === "dark" ? "#666666" : "#a3a3a3", marginTop: 8, fontSize: 12 }}>Loading...</span>
      </div>
    );
  }

  return <>{children}</>;
}

export function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <Suspense
          fallback={
            <div
              style={{
                display: "flex", flexDirection: "column",
                flex: 1,
                alignItems: "center",
                justifyContent: "center",
                height: "100%",
              }}
            >
              <Spinner size={24} />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </AuthGate>
    </QueryClientProvider>
  );
}
