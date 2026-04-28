import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
/** Return the best bearer token available: accessToken > apiKey > "" */
export function getAuthToken() {
    const { accessToken, apiKey } = useAuthStore.getState();
    return accessToken || apiKey;
}
const storage = createJSONStorage(() => localStorage);
export const useAuthStore = create()(persist((set) => ({
    serverUrl: "",
    apiKey: "",
    accessToken: "",
    refreshToken: "",
    user: null,
    isConfigured: false,
    // Legacy: server URL + API key (no user identity)
    setServer: (url, key) => set({
        serverUrl: url.replace(/\/+$/, ""),
        apiKey: key,
        accessToken: "",
        refreshToken: "",
        user: null,
        isConfigured: true,
    }),
    // JWT auth: server URL + tokens + user
    setAuth: (serverUrl, tokens, user) => set({
        serverUrl: serverUrl.replace(/\/+$/, ""),
        apiKey: "",
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
        user,
        isConfigured: true,
    }),
    setAccessToken: (token) => set({ accessToken: token }),
    updateUser: (user) => set({ user }),
    clear: () => set({
        serverUrl: "",
        apiKey: "",
        accessToken: "",
        refreshToken: "",
        user: null,
        isConfigured: false,
    }),
}), {
    name: "agent-auth",
    storage,
}));
