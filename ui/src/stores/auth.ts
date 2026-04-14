import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  integration_config: Record<string, any>;
  is_admin: boolean;
  auth_method: string;
}

interface AuthState {
  serverUrl: string;
  apiKey: string; // kept for API-key-only mode
  accessToken: string;
  refreshToken: string;
  user: AuthUser | null;
  isConfigured: boolean;

  setServer: (url: string, key: string) => void; // legacy API key mode
  setAuth: (
    serverUrl: string,
    tokens: { access_token: string; refresh_token: string },
    user: AuthUser
  ) => void;
  setAccessToken: (token: string) => void;
  updateUser: (user: AuthUser) => void;
  clear: () => void;
}

/** Return the best bearer token available: accessToken > apiKey > "" */
export function getAuthToken(): string {
  const { accessToken, apiKey } = useAuthStore.getState();
  return accessToken || apiKey;
}

const storage = createJSONStorage(() => localStorage);

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      serverUrl: "",
      apiKey: "",
      accessToken: "",
      refreshToken: "",
      user: null,
      isConfigured: false,

      // Legacy: server URL + API key (no user identity)
      setServer: (url: string, key: string) =>
        set({
          serverUrl: url.replace(/\/+$/, ""),
          apiKey: key,
          accessToken: "",
          refreshToken: "",
          user: null,
          isConfigured: true,
        }),

      // JWT auth: server URL + tokens + user
      setAuth: (serverUrl, tokens, user) =>
        set({
          serverUrl: serverUrl.replace(/\/+$/, ""),
          apiKey: "",
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          user,
          isConfigured: true,
        }),

      setAccessToken: (token: string) => set({ accessToken: token }),

      updateUser: (user: AuthUser) => set({ user }),

      clear: () =>
        set({
          serverUrl: "",
          apiKey: "",
          accessToken: "",
          refreshToken: "",
          user: null,
          isConfigured: false,
        }),
    }),
    {
      name: "agent-auth",
      storage,
    }
  )
);
