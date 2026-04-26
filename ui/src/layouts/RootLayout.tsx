import { useEffect, Suspense } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/src/stores/auth";
import { useThemeStore } from "@/src/stores/theme";
import { useHydrated } from "@/src/hooks/useHydrated";
import { Spinner } from "@/src/components/shared/Spinner";
import { AttentionHubDrawerRoot } from "@/src/components/spatial-canvas/SpatialAttentionLayer";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

// Expose queryClient on window for screenshot/video recording scripts.
// Lets stage drivers seed synthetic data (e.g. an imminent UpcomingItem)
// for demo flythroughs without round-tripping through real backend state.
if (typeof window !== "undefined") {
  (window as unknown as { __spindrelQueryClient?: QueryClient }).__spindrelQueryClient =
    queryClient;
}

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

const AUTH_PATHS = ["/login", "/setup"];

function AuthGate({ children }: { children: React.ReactNode }) {
  const isConfigured = useAuthStore((s) => s.isConfigured);
  const mode = useThemeStore((s) => s.mode);
  const hydrated = useHydrated();
  const location = useLocation();
  const navigate = useNavigate();

  useApplyThemeClass();

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

function GlobalDrawers() {
  const isConfigured = useAuthStore((s) => s.isConfigured);
  if (!isConfigured) return null;
  return <AttentionHubDrawerRoot />;
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
          <GlobalDrawers />
        </Suspense>
      </AuthGate>
    </QueryClientProvider>
  );
}
