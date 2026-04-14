import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

type ThemeMode = "light" | "dark";

interface ThemeState {
  mode: ThemeMode;
  toggle: () => void;
  setMode: (m: ThemeMode) => void;
}

const storage = createJSONStorage(() => localStorage);

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: "dark",
      toggle: () => set((s) => ({ mode: s.mode === "dark" ? "light" : "dark" })),
      setMode: (mode) => set({ mode }),
    }),
    {
      name: "agent-theme",
      storage,
    }
  )
);
