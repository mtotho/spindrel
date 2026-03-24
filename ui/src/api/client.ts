import { useAuthStore, getAuthToken } from "../stores/auth";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Try to refresh the access token using the stored refresh token.
 *  Returns the new access token on success, null on failure. */
async function tryRefresh(): Promise<string | null> {
  const { serverUrl, refreshToken } = useAuthStore.getState();
  if (!serverUrl || !refreshToken) return null;
  try {
    const res = await fetch(`${serverUrl}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    useAuthStore.getState().setAccessToken(data.access_token);
    return data.access_token as string;
  } catch {
    return null;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const { serverUrl } = useAuthStore.getState();
  if (!serverUrl) throw new Error("Server not configured");

  const token = getAuthToken();
  const url = `${serverUrl}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers as Record<string, string>),
  };

  let res = await fetch(url, { ...options, headers });

  // Auto-refresh on 401 if we have a refresh token
  if (res.status === 401 && useAuthStore.getState().refreshToken) {
    const newToken = await tryRefresh();
    if (newToken) {
      headers.Authorization = `Bearer ${newToken}`;
      res = await fetch(url, { ...options, headers });
    } else {
      // Refresh failed — clear auth and force re-login
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
  return res.json();
}

export { ApiError };
