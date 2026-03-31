import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

type Visibility = "always" | "threshold";

interface UsageHudState {
  visibility: Visibility;
  cycleVisibility: () => void;
  setVisibility: (v: Visibility) => void;
}

const CYCLE: Visibility[] = ["always", "threshold"];

const storage =
  Platform.OS === "web"
    ? createJSONStorage(() => localStorage)
    : createJSONStorage(() => AsyncStorage);

export const useUsageHudStore = create<UsageHudState>()(
  persist(
    (set) => ({
      visibility: "always",
      cycleVisibility: () =>
        set((s) => {
          const idx = CYCLE.indexOf(s.visibility);
          return { visibility: CYCLE[(idx + 1) % CYCLE.length] };
        }),
      setVisibility: (visibility) => set({ visibility }),
    }),
    {
      name: "agent-usage-hud",
      storage,
      merge: (persisted, current) => {
        const p = persisted as Partial<UsageHudState> | undefined;
        const vis = p?.visibility;
        return {
          ...current,
          ...p,
          // Fix stale "never" values from before removal
          visibility: vis === "always" || vis === "threshold" ? vis : "always",
        };
      },
    },
  ),
);
