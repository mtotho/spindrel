import { useAuthStore } from "../stores/auth";

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

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const { serverUrl, apiKey } = useAuthStore.getState();
  if (!serverUrl) throw new Error("Server not configured");

  const url = `${serverUrl}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
    ...(options.headers as Record<string, string>),
  };

  const res = await fetch(url, { ...options, headers });

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
