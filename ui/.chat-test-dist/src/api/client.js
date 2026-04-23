import { useAuthStore, getAuthToken } from "../stores/auth";
export class ApiError extends Error {
    status;
    body;
    constructor(status, message, body) {
        super(message);
        this.status = status;
        this.body = body;
        this.name = "ApiError";
    }
    /** FastAPI-style `{"detail": "..."}` body — extract the human message.
     *  Also handles `{"detail": {"message": "...", ...}}` where endpoints
     *  return a structured error payload (e.g. widget-auth mint carries
     *  ``reason``/``bot_id``/``pin_id`` alongside the message). */
    get detail() {
        if (typeof this.body !== "string")
            return null;
        try {
            const parsed = JSON.parse(this.body);
            if (parsed && typeof parsed.detail === "string")
                return parsed.detail;
            if (parsed &&
                typeof parsed.detail === "object" &&
                parsed.detail !== null &&
                typeof parsed.detail.message === "string") {
                return parsed.detail.message;
            }
        }
        catch {
            // Not JSON — return the raw text if it's short enough to be a message
            if (this.body.length < 500)
                return this.body;
        }
        return null;
    }
}
/** Try to refresh the access token using the stored refresh token.
 *  Returns the new access token on success, null on failure. */
async function tryRefresh() {
    const { serverUrl, refreshToken } = useAuthStore.getState();
    if (!serverUrl || !refreshToken)
        return null;
    try {
        const res = await fetch(`${serverUrl}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!res.ok)
            return null;
        const data = await res.json();
        useAuthStore.getState().setAccessToken(data.access_token);
        return data.access_token;
    }
    catch {
        return null;
    }
}
export async function apiFetch(path, options = {}) {
    const { serverUrl } = useAuthStore.getState();
    if (!serverUrl)
        throw new Error("Server not configured");
    const token = getAuthToken();
    const url = `${serverUrl}${path}`;
    const headers = {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
    };
    let res = await fetch(url, { ...options, headers });
    // Auto-refresh on 401 if we have a refresh token
    if (res.status === 401 && useAuthStore.getState().refreshToken) {
        const newToken = await tryRefresh();
        if (newToken) {
            headers.Authorization = `Bearer ${newToken}`;
            res = await fetch(url, { ...options, headers });
        }
        else {
            // Refresh failed — clear auth and force re-login
            useAuthStore.getState().clear();
        }
    }
    if (!res.ok) {
        const body = await res.text().catch(() => null);
        throw new ApiError(res.status, `API error ${res.status}: ${res.statusText}`, body);
    }
    if (res.status === 204)
        return undefined;
    return res.json();
}
/** Like apiFetch but returns raw text instead of parsing JSON. */
export async function apiFetchText(path, options = {}) {
    const { serverUrl } = useAuthStore.getState();
    if (!serverUrl)
        throw new Error("Server not configured");
    const token = getAuthToken();
    const url = `${serverUrl}${path}`;
    const headers = {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
    };
    let res = await fetch(url, { ...options, headers });
    if (res.status === 401 && useAuthStore.getState().refreshToken) {
        const newToken = await tryRefresh();
        if (newToken) {
            headers.Authorization = `Bearer ${newToken}`;
            res = await fetch(url, { ...options, headers });
        }
        else {
            useAuthStore.getState().clear();
        }
    }
    if (!res.ok) {
        const body = await res.text().catch(() => null);
        throw new ApiError(res.status, `API error ${res.status}: ${res.statusText}`, body);
    }
    return res.text();
}
