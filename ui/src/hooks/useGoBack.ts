import { useRouter, useNavigationContainerRef } from "expo-router";
import { useCallback } from "react";

/**
 * Safe go-back that falls back to a parent route when there's no in-app history.
 *
 * Uses React Navigation's canGoBack() to detect real in-app history.
 * If there's no in-app stack (direct page load, refresh, external link),
 * navigates to the fallback route instead of relying on browser history
 * (which can exit the app or go to unrelated pages).
 */
export function useGoBack(fallback: string) {
  const router = useRouter();
  const nav = useNavigationContainerRef();

  return useCallback(() => {
    if (nav?.canGoBack()) {
      router.back();
    } else {
      // No in-app history — replace so the dead-end page isn't left in history
      router.replace(fallback as any);
    }
  }, [router, nav, fallback]);
}
