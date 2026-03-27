import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Hook for pull-to-refresh on list/detail pages.
 * Refetches all active queries on the current page (or specific keys if provided).
 */
export function usePageRefresh(queryKeys?: string[][]) {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      if (queryKeys) {
        await Promise.all(
          queryKeys.map((key) => queryClient.refetchQueries({ queryKey: key }))
        );
      } else {
        await queryClient.refetchQueries({ type: "active" });
      }
    } finally {
      setRefreshing(false);
    }
  }, [queryClient, queryKeys]);

  return { refreshing, onRefresh } as const;
}
