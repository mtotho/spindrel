import { useRouter, useNavigationContainerRef } from "expo-router";
import { useCallback } from "react";
import { Platform } from "react-native";

/**
 * Safe go-back that falls back to a parent route when there's no history.
 * Prevents "GO_BACK was not handled by any navigator" warnings.
 *
 * On web, prefers browser history (window.history) since Expo Router's
 * canGoBack() doesn't always reflect actual browser history state.
 */
export function useGoBack(fallback: string) {
  const router = useRouter();
  const nav = useNavigationContainerRef();

  return useCallback(() => {
    if (Platform.OS === "web" && window.history.length > 1) {
      router.back();
    } else if (nav?.canGoBack()) {
      router.back();
    } else {
      router.push(fallback as any);
    }
  }, [router, nav, fallback]);
}
