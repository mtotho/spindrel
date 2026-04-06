"""Auto-generate the endpoint catalog from FastAPI route introspection.

At startup, ``build_endpoint_catalog(app)`` walks every registered route,
extracts scope info from ``require_scopes()`` closures, and returns a list
of ``{scope, method, path, description}`` dicts — the same shape the old
static ``ENDPOINT_CATALOG`` had.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

logger = logging.getLogger(__name__)

# Paths excluded from the catalog (auth, health-check, proxies, etc.)
_EXCLUDED_PREFIXES = (
    "/auth",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
)

_EXCLUDED_EXACT = {
    "/api/v1/discover",
    "/transcribe",
}

_EXCLUDED_SUFFIXES = (
    "/editor/{path:path}",
    "/ui/{path:path}",
)

# Manual notes for important endpoints (keyed by (method, path))
ENDPOINT_NOTES: dict[tuple[str, str], str] = {
    ("POST", "/chat/stream"): "Returns Server-Sent Events. Events: skill_context, memory_context, tool_start, tool_result, response, error.",
    ("POST", "/chat"): "Non-streaming. Returns full response synchronously.",
    ("POST", "/api/v1/sessions/{id}/messages"): "If run_agent=true, returns {task_id} for async processing.",
    ("GET", "/api/v1/tasks/{id}"): "Status: pending → running → complete | failed. Poll at 5s+ intervals.",
    ("DELETE", "/api/v1/admin/bots/{id}"): "Returns 204 on success. 403 if system bot. 409 if bot has active channels without force.",
    ("POST", "/api/v1/admin/operations/restart"): "Requires confirm: true in body.",
    ("GET", "/api/v1/admin/server-logs"): "level is minimum severity filter. logger is prefix-matched.",
    ("GET", "/api/v1/admin/turns"): "after accepts relative durations (30m, 2h, 1d) or ISO timestamps. Newest-first.",
    ("POST", "/api/v1/channels/{id}/messages"): "If run_agent=true, returns {task_id} for async processing.",
    ("GET", "/api/v1/channels/{id}/events"): "Server-Sent Events stream for real-time channel updates.",
}


def _is_excluded(path: str) -> bool:
    """Check if a route path should be excluded from the catalog."""
    if path in _EXCLUDED_EXACT:
        return True
    for prefix in _EXCLUDED_PREFIXES:
        if path.startswith(prefix):
            return True
    for suffix in _EXCLUDED_SUFFIXES:
        if path.endswith(suffix):
            return True
    # Attachment file download uses query-param token (not standard auth)
    if "/attachments/" in path and path.endswith("/file"):
        return True
    return False


def _extract_scope_from_dependency(dep_func: Any) -> str | None:
    """Extract the scope string from a require_scopes() closure.

    require_scopes(*scopes) returns an inner _check function whose
    __closure__ contains the scopes tuple.  We identify it by qualname.
    """
    qualname = getattr(dep_func, "__qualname__", "")
    if "require_scopes" not in qualname:
        return None

    closure = getattr(dep_func, "__closure__", None)
    if not closure:
        return None

    for cell in closure:
        try:
            val = cell.cell_contents
            if isinstance(val, tuple) and val and isinstance(val[0], str):
                # require_scopes(*scopes) stores scopes as a tuple of strings
                # Return the first scope (primary scope for the endpoint)
                return val[0]
        except ValueError:
            continue
    return None


def _extract_scope_from_endpoint(endpoint: Any) -> str | None:
    """Extract scope from an endpoint function's default parameter values."""
    try:
        sig = inspect.signature(endpoint)
    except (ValueError, TypeError):
        return None

    for param in sig.parameters.values():
        default = param.default
        if not hasattr(default, "dependency"):
            continue
        scope = _extract_scope_from_dependency(default.dependency)
        if scope is not None:
            return scope
    return None


def _extract_scope_from_route_deps(route: APIRoute) -> str | None:
    """Extract scope from route-level dependencies (e.g. router(dependencies=[...]))."""
    for dep in route.dependencies:
        dep_func = dep.dependency if hasattr(dep, "dependency") else None
        if dep_func is None:
            continue
        scope = _extract_scope_from_dependency(dep_func)
        if scope is not None:
            return scope
    return None


def _get_description(route: APIRoute) -> str:
    """Get a human-readable description for a route."""
    if route.summary:
        return route.summary
    if route.description:
        # Take just the first line of multi-line descriptions
        return route.description.split("\n")[0].strip()
    # Fall back to the function name, humanized
    name = route.name or ""
    return name.replace("_", " ").strip().capitalize()


def build_endpoint_catalog(app: FastAPI) -> list[dict]:
    """Build the endpoint catalog by introspecting all registered routes.

    Returns a list of dicts with keys: scope, method, path, description.
    Optional keys: notes.
    """
    catalog: list[dict] = []
    seen: set[tuple[str, str, str | None]] = set()  # (method, path, scope)

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        path = route.path
        if _is_excluded(path):
            continue

        # Extract scope — try endpoint params first, then route-level deps
        scope = _extract_scope_from_endpoint(route.endpoint)
        if scope is None:
            scope = _extract_scope_from_route_deps(route)

        description = _get_description(route)

        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = (method, path, scope)
            if key in seen:
                continue
            seen.add(key)

            entry: dict[str, Any] = {
                "scope": scope,
                "method": method,
                "path": path,
                "description": description,
            }

            # Add manual notes if available
            notes = ENDPOINT_NOTES.get((method, path))
            if notes:
                entry["notes"] = notes

            catalog.append(entry)

    # Sort by scope (None last), then path, then method
    catalog.sort(key=lambda e: (e["scope"] or "zzz", e["path"], e["method"]))

    logger.info("Built endpoint catalog: %d entries", len(catalog))
    return catalog
