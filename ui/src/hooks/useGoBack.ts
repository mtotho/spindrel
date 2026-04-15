import { useNavigate } from "react-router-dom";
import { useCallback } from "react";

/**
 * Safe go-back that falls back to a parent route when there's no in-app history.
 *
 * If there's no in-app stack (direct page load, refresh, external link),
 * navigates to the fallback route instead of relying on browser history
 * (which can exit the app or go to unrelated pages).
 */
export function useGoBack(fallback: string) {
  const navigate = useNavigate();

  return useCallback(() => {
    // window.history.length > 1 is a heuristic — it's not perfect because
    // the browser may have non-app history entries. But it matches the
    // old canGoBack() behavior closely enough for our use case.
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate(fallback, { replace: true });
    }
  }, [navigate, fallback]);
}
