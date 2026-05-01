import { useAuthStore, getAuthToken } from "../stores/auth";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** FastAPI-style `{"detail": "..."}` body — extract the human message.
   *  Also handles `{"detail": {"message": "...", ...}}` where endpoints
   *  return a structured error payload (e.g. widget-auth mint carries
   *  ``reason``/``bot_id``/``pin_id`` alongside the message). */
  get detail(): string | null {
    if (typeof this.body !== "string") return null;
    try {
      const parsed = JSON.parse(this.body);
      if (parsed && typeof parsed.detail === "string") return parsed.detail;
      if (
        parsed &&
        typeof parsed.detail === "object" &&
        parsed.detail !== null &&
        typeof parsed.detail.message === "string"
      ) {
        return parsed.detail.message;
      }
    } catch {
      // Not JSON — return the raw text if it's short enough to be a message
      if (this.body.length < 500) return this.body;
    }
    return null;
  }
}

type RefreshResult =
  | { ok: true; token: string }
  | { ok: false; clearAuth: boolean };

let refreshInFlight: Promise<RefreshResult> | null = null;
let refreshBlockedUntil = 0;

function retryDelayMs(res: Response): number {
  const retryAfter = res.headers.get("Retry-After");
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
    const dateMs = Date.parse(retryAfter);
    if (Number.isFinite(dateMs)) return Math.max(0, dateMs - Date.now());
  }
  return res.status === 429 ? 60_000 : 5_000;
}

/** Try to refresh the access token using the stored refresh token.
 *  Concurrent 401s share one refresh call so an expired access token does not
 *  stampede /auth/refresh and trip the auth rate limiter. */
async function doRefresh(): Promise<RefreshResult> {
  const { serverUrl, refreshToken } = useAuthStore.getState();
  if (!serverUrl || !refreshToken) return { ok: false, clearAuth: false };
  if (Date.now() < refreshBlockedUntil) return { ok: false, clearAuth: false };
  try {
    const res = await fetch(`${serverUrl}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      // 401/403 means the stored refresh token is no longer usable. 429,
      // network errors, and 5xx are transient; keep the session so the next
      // request can retry instead of forcing an unnecessary login.
      if (res.status === 429 || res.status >= 500) {
        refreshBlockedUntil = Date.now() + retryDelayMs(res);
      }
      return { ok: false, clearAuth: res.status === 401 || res.status === 403 };
    }
    const data = await res.json() as { access_token?: string };
    if (!data.access_token) return { ok: false, clearAuth: false };
    useAuthStore.getState().setAccessToken(data.access_token);
    refreshBlockedUntil = 0;
    return { ok: true, token: data.access_token };
  } catch {
    refreshBlockedUntil = Date.now() + 5_000;
    return { ok: false, clearAuth: false };
  }
}

function tryRefresh(): Promise<RefreshResult> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const { serverUrl } = useAuthStore.getState();
  if (!serverUrl) throw new Error("Server not configured");

  const token = getAuthToken();
  const url = `${serverUrl}${path}`;
  const method = (options.method ?? "GET").toUpperCase();
  const hasBody = options.body != null;
  const headers: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string>),
  };
  if (hasBody && !headers["Content-Type"] && method !== "GET" && method !== "HEAD") {
    headers["Content-Type"] = "application/json";
  }

  let res = await fetch(url, { ...options, headers });

  // Auto-refresh on 401 if we have a refresh token
  if (res.status === 401 && useAuthStore.getState().refreshToken) {
    const refresh = await tryRefresh();
    if (refresh.ok) {
      headers.Authorization = `Bearer ${refresh.token}`;
      res = await fetch(url, { ...options, headers });
    } else if (refresh.clearAuth) {
      // Refresh token is invalid or expired — clear auth and force re-login.
      useAuthStore.getState().clear();
    }
  }

  if (!res.ok) {
    const body = await res.text().catch(() => null);
    throw new ApiError(
      res.status,
      `API error ${res.status}: ${res.statusText}`,
      body
    );
  }

  if (res.status === 204) return undefined as T;
  return await res.json() as T;
}

/** Like apiFetch but returns raw text instead of parsing JSON. */
export async function apiFetchText(
  path: string,
  options: RequestInit = {},
): Promise<string> {
  const { serverUrl } = useAuthStore.getState();
  if (!serverUrl) throw new Error("Server not configured");

  const token = getAuthToken();
  const url = `${serverUrl}${path}`;
  const headers: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string>),
  };

  let res = await fetch(url, { ...options, headers });

  if (res.status === 401 && useAuthStore.getState().refreshToken) {
    const refresh = await tryRefresh();
    if (refresh.ok) {
      headers.Authorization = `Bearer ${refresh.token}`;
      res = await fetch(url, { ...options, headers });
    } else if (refresh.clearAuth) {
      useAuthStore.getState().clear();
    }
  }

  if (!res.ok) {
    const body = await res.text().catch(() => null);
    throw new ApiError(res.status, `API error ${res.status}: ${res.statusText}`, body);
  }

  return res.text();
}
