import { useAuthStore } from "../stores/auth";

/**
 * Mirror of the backend `has_scope()` semantics at
 * `app/services/api_keys.py:518`. Kept in parity so UI hide/disable
 * decisions match the 403 the endpoint would produce.
 */
function parseScope(scope: string): [string, string] {
  const parts = scope.split(":");
  if (parts.length >= 2) return [parts[0], parts[1]];
  return [scope, ""];
}

export function hasScope(keyScopes: readonly string[], required: string): boolean {
  if (keyScopes.includes("admin")) return true;
  if (keyScopes.includes(required)) return true;

  const [reqResource, reqAction] = parseScope(required);

  for (const s of keyScopes) {
    const [sResource, sAction] = parseScope(s);

    if (reqAction === "read" && sAction === "write" && reqResource === sResource) {
      return true;
    }

    if (reqResource.startsWith(sResource + ".")) {
      if (sAction === reqAction) return true;
      if (sAction === "write" && reqAction === "read") return true;
    }

    if (required.startsWith(s + ":")) return true;

    if (
      sAction === "*" &&
      (reqResource === sResource || reqResource.startsWith(sResource + "."))
    ) {
      return true;
    }
  }

  return false;
}

/**
 * Hook: does the current user have the given scope?
 *
 * Source of truth is the user's effective scopes hydrated from `/auth/me`.
 * Admin users have `["admin"]` which covers every scope. Users with no
 * provisioned API key get `[]` and fail every check — matching the
 * backend's fail-closed behavior in `require_scopes()`.
 */
export function useScope(scope: string): boolean {
  const user = useAuthStore((s) => s.user);
  if (!user) return false;
  return hasScope(user.scopes ?? [], scope);
}

/** Multi-scope check — true iff EVERY scope is granted. */
export function useScopes(...scopes: string[]): boolean {
  const user = useAuthStore((s) => s.user);
  if (!user) return false;
  const userScopes = user.scopes ?? [];
  return scopes.every((s: string) => hasScope(userScopes, s));
}

/** Any-of: true iff AT LEAST ONE of the given scopes is granted. */
export function useAnyScope(...scopes: string[]): boolean {
  const user = useAuthStore((s) => s.user);
  if (!user) return false;
  const userScopes = user.scopes ?? [];
  return scopes.some((s: string) => hasScope(userScopes, s));
}

export function useIsAdmin(): boolean {
  const user = useAuthStore((s) => s.user);
  return !!user?.is_admin;
}
