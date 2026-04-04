/**
 * Auth bridge for embedded integration dashboards.
 *
 * When loaded inside the main app's iframe, receives auth token and theme
 * via postMessage. When running standalone (dev mode), falls back to
 * reading from localStorage (same-origin with the agent server).
 */

type ThemeMode = "light" | "dark";
type ThemeListener = (mode: ThemeMode) => void;

let _token: string | null = null;
let _serverUrl: string | null = null;
let _theme: ThemeMode = "dark";
const _themeListeners = new Set<ThemeListener>();

/** Try to read auth from localStorage (works same-origin or standalone). */
function readFromLocalStorage(): void {
  try {
    const raw = localStorage.getItem("agent-auth");
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const state = parsed?.state;
    if (!state) return;
    _token = state.accessToken || state.apiKey || null;
    _serverUrl = state.serverUrl || null;
  } catch {
    // ignore parse errors
  }
}

/** Try to read theme from localStorage. */
function readThemeFromLocalStorage(): void {
  try {
    const raw = localStorage.getItem("agent-theme");
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const mode = parsed?.state?.mode;
    if (mode === "light" || mode === "dark") {
      _theme = mode;
    }
  } catch {
    // ignore
  }
}

/** Listen for postMessage events from parent window. */
function listenForMessages(): void {
  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || typeof data !== "object") return;

    if (data.type === "spindrel:auth") {
      if (data.token) _token = data.token;
      if (data.serverUrl) _serverUrl = data.serverUrl;
    }

    if (data.type === "spindrel:theme") {
      const mode = data.mode;
      if (mode === "light" || mode === "dark") {
        _theme = mode;
        _themeListeners.forEach((fn) => fn(mode));
      }
    }
  });
}

// Initialize on module load
readFromLocalStorage();
readThemeFromLocalStorage();
listenForMessages();

/** Get the current auth token. */
export function getToken(): string | null {
  return _token;
}

/** Get the server URL (used for standalone mode). */
export function getServerUrl(): string | null {
  return _serverUrl;
}

/** Get the current theme mode. */
export function getTheme(): ThemeMode {
  return _theme;
}

/** Whether we're running inside the main app's iframe. */
export function isEmbedded(): boolean {
  try {
    return window.parent !== window;
  } catch {
    return false;
  }
}

/** Subscribe to theme changes. Returns unsubscribe function. */
export function onThemeChange(fn: ThemeListener): () => void {
  _themeListeners.add(fn);
  return () => _themeListeners.delete(fn);
}
