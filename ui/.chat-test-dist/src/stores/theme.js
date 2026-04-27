import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
const storage = createJSONStorage(() => localStorage);
export const useThemeStore = create()(persist((set) => ({
    mode: "dark",
    toggle: () => set((s) => ({ mode: s.mode === "dark" ? "light" : "dark" })),
    setMode: (mode) => set({ mode }),
}), {
    name: "agent-theme",
    storage,
}));
