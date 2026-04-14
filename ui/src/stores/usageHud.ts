import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface UsageHudState {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
}

const storage = createJSONStorage(() => localStorage);

export const useUsageHudStore = create<UsageHudState>()(
  persist(
    (set) => ({
      enabled: true,
      setEnabled: (enabled) => set({ enabled }),
    }),
    {
      name: "agent-usage-hud",
      storage,
      version: 1,
      migrate: () => ({ enabled: true }),
    },
  ),
);
