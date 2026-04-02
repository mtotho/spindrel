import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

interface UsageHudState {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
}

const storage =
  Platform.OS === "web"
    ? createJSONStorage(() => localStorage)
    : createJSONStorage(() => AsyncStorage);

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
