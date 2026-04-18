import { useMemo } from "react";
import { useUpcomingActivity } from "../../../api/hooks/useUpcomingActivity";

/** Count of items scheduled within the remainder of today (for the rail badge). */
export function useTodayUpcomingCount(): number {
  const { data: items } = useUpcomingActivity(50);
  return useMemo(() => {
    if (!items) return 0;
    const endOfDay = new Date();
    endOfDay.setHours(23, 59, 59, 999);
    let count = 0;
    for (const it of items) {
      if (!it.scheduled_at) continue;
      if (new Date(it.scheduled_at).getTime() <= endOfDay.getTime()) count++;
    }
    return count;
  }, [items]);
}
