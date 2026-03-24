import { useRouter, useNavigationContainerRef } from "expo-router";
import { useCallback } from "react";

/**
 * Safe go-back that falls back to a parent route when there's no history.
 * Prevents "GO_BACK was not handled by any navigator" warnings.
 */
export function useGoBack(fallback: string) {
  const router = useRouter();
  const nav = useNavigationContainerRef();

  return useCallback(() => {
    if (nav?.canGoBack()) {
      router.back();
    } else {
      router.replace(fallback as any);
    }
  }, [router, nav, fallback]);
}
