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
 * Fix mobile-web viewport, safe areas, and iOS keyboard behavior.
 *
 * Production HTML may lack viewport-fit=cover, safe area padding, and the
 * visualViewport keyboard handler. We inject all of that client-side here
 * so it works regardless of how the HTML is generated.
 */
function useWebViewportFix() {
  useEffect(() => {
    const vp = document.querySelector('meta[name="viewport"]');
    if (vp) {
      vp.setAttribute(
        "content",
        "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover",
      );
    }

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

    const vv = window.visualViewport;
    if (!vv || !root) return;

    const initialHeight = vv.height;
    let pending = false;

    function sync() {
      pending = false;
      if (!root || !vv) return;
      root.style.top = vv.offsetTop + "px";
      root.style.height = vv.height + "px";
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
