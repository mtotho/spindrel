import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

interface AuthState {
  serverUrl: string;
  apiKey: string;
  isConfigured: boolean;
  setServer: (url: string, key: string) => void;
  clear: () => void;
}

const storage =
  Platform.OS === "web"
    ? createJSONStorage(() => localStorage)
    : createJSONStorage(() => AsyncStorage);

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      serverUrl: "",
      apiKey: "",
      isConfigured: false,
      setServer: (url: string, key: string) =>
        set({
          serverUrl: url.replace(/\/+$/, ""),
          apiKey: key,
          isConfigured: true,
        }),
      clear: () => set({ serverUrl: "", apiKey: "", isConfigured: false }),
    }),
    {
      name: "agent-auth",
      storage,
    }
  )
);
