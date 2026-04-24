"""Thin HTTP client for the e2e agent-server API.

Idempotent helpers keyed on ``screenshot:*`` prefixes so reruns dedupe by
client_id / bot id. Uses the admin-scoped API key for all mutations; no JWT
path here (the browser layer handles JWTs for localStorage seeding).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(30.0, read=120.0)


class SpindrelClient:
    def __init__(self, api_url: str, api_key: str, *, dry_run: bool = False) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._dry_run = dry_run
        self._http = httpx.Client(
            base_url=self._api_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=_DEFAULT_TIMEOUT,
        )

    # --- internal helpers --------------------------------------------------

    def _get(self, path: str, **kw) -> httpx.Response:
        r = self._http.get(path, **kw)
        r.raise_for_status()
        return r

    def _post(self, path: str, *, json: dict | None = None, **kw) -> httpx.Response:
        if self._dry_run:
            logger.info("DRY-RUN POST %s json=%s", path, json)
            return httpx.Response(200, json={"id": "dry-run", "dry_run": True})
        r = self._http.post(path, json=json, **kw)
        if r.status_code >= 400:
            logger.error("POST %s -> %s body=%s", path, r.status_code, r.text[:500])
        r.raise_for_status()
        return r

    def _delete(self, path: str, **kw) -> httpx.Response:
        if self._dry_run:
            logger.info("DRY-RUN DELETE %s", path)
            return httpx.Response(204)
        r = self._http.delete(path, **kw)
        r.raise_for_status()
        return r

    # --- bots --------------------------------------------------------------

    def get_bot(self, bot_id: str) -> dict | None:
        r = self._http.get(f"/api/v1/admin/bots/{bot_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def ensure_bot(
        self,
        *,
        bot_id: str,
        name: str,
        model: str,
        system_prompt: str = "",
        model_provider_id: str | None = None,
    ) -> dict:
        existing = self.get_bot(bot_id)
        if existing:
            return existing
        body: dict[str, Any] = {
            "id": bot_id,
            "name": name,
            "model": model,
            "system_prompt": system_prompt,
        }
        if model_provider_id:
            body["model_provider_id"] = model_provider_id
        return self._post("/api/v1/admin/bots", json=body).json()

    def delete_bot(self, bot_id: str) -> None:
        r = self._http.delete(f"/api/v1/admin/bots/{bot_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    # --- channels ----------------------------------------------------------

    def ensure_channel(
        self,
        *,
        client_id: str,
        bot_id: str = "default",
        name: str | None = None,
        private: bool = False,
        category: str | None = None,
    ) -> dict:
        """Create a channel (or return the existing one with matching client_id).

        The ``POST /api/v1/channels`` handler goes through ``get_or_create_channel``
        which dedupes on ``client_id`` — reruns are safe. ``category`` lands in
        ``metadata_["category"]`` and is re-applied on every POST, so reruns keep
        the grouping correct even after the row already exists.
        """
        body: dict[str, Any] = {
            "client_id": client_id,
            "bot_id": bot_id,
            "name": name or client_id,
            "private": private,
        }
        if category is not None:
            body["category"] = category
        return self._post("/api/v1/channels", json=body).json()

    def list_channels(self) -> list[dict]:
        return self._get("/api/v1/admin/channels", params={"page_size": 100}).json().get("channels", [])

    def delete_channel(self, channel_id: str) -> None:
        # Public channels router exposes DELETE — admin router only has skill/
        # binding sub-deletes. Path: /api/v1/channels/{id}.
        r = self._http.delete(f"/api/v1/channels/{channel_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    # --- chat --------------------------------------------------------------

    def send_message(self, *, channel_id: str, text: str) -> dict:
        """Send a single message. Returns the 202 body. Caller waits separately."""
        return self._post(
            "/chat",
            json={"channel_id": channel_id, "message": text},
        ).json()

    # --- dashboard pins ----------------------------------------------------

    def list_pins(self, *, dashboard_key: str) -> list[dict]:
        r = self._http.get("/api/v1/widgets/dashboard", params={"slug": dashboard_key})
        r.raise_for_status()
        return r.json().get("pins", [])

    def create_pin(
        self,
        *,
        dashboard_key: str,
        tool_name: str,
        envelope: dict,
        source_kind: str = "channel",
        source_channel_id: str | None = None,
        source_bot_id: str | None = None,
        display_label: str | None = None,
        zone: str | None = None,
        grid_layout: dict | None = None,
        widget_config: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "source_kind": source_kind,
            "tool_name": tool_name,
            "envelope": envelope,
            "dashboard_key": dashboard_key,
        }
        if source_channel_id:
            body["source_channel_id"] = source_channel_id
        if source_bot_id:
            body["source_bot_id"] = source_bot_id
        if display_label:
            body["display_label"] = display_label
        if zone:
            body["zone"] = zone
        if grid_layout:
            body["grid_layout"] = grid_layout
        if widget_config:
            body["widget_config"] = widget_config
        return self._post("/api/v1/widgets/dashboard/pins", json=body).json()

    def delete_pin(self, pin_id: str) -> None:
        r = self._http.delete(f"/api/v1/widgets/dashboard/pins/{pin_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def patch_pins_layout(
        self,
        *,
        dashboard_key: str,
        items: list[dict],
    ) -> dict:
        """Bulk-commit grid coordinates for existing pins.

        ``items`` is a list of ``{id, x, y, w, h, zone?}`` dicts. Used to
        reconcile layouts on rerun — the POST /pins route creates with a
        ``grid_layout`` but does not update it on duplicate ``display_label``.
        """
        if self._dry_run:
            logger.info("DRY-RUN PATCH /pins/layout items=%d", len(items))
            return {}
        body = {"dashboard_key": dashboard_key, "items": items}
        # The route is POST /dashboard/pins/layout (bulk commit), not PATCH —
        # don't let the name "patch" on this helper mislead.
        r = self._http.post("/api/v1/widgets/dashboard/pins/layout", json=body)
        if r.status_code >= 400:
            logger.error("POST /pins/layout -> %s body=%s", r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()

    # --- tasks / pipelines -------------------------------------------------

    def create_pipeline(
        self,
        *,
        bot_id: str,
        title: str,
        steps: list[dict],
        channel_id: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "bot_id": bot_id,
            "title": title,
            "task_type": "pipeline",
            "steps": steps,
        }
        if channel_id:
            body["channel_id"] = channel_id
        return self._post("/api/v1/admin/tasks", json=body).json()

    def list_tasks(self, *, bot_id: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"task_type": "pipeline"}
        if bot_id:
            params["bot_id"] = bot_id
        return self._get("/api/v1/admin/tasks", params=params).json().get("tasks", [])

    def delete_task(self, task_id: str) -> None:
        r = self._http.delete(f"/api/v1/admin/tasks/{task_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    # --- secrets / mcp / skills / heartbeats / bindings --------------------
    # Used by docs_repair staging; all idempotent via GET-then-POST.

    def list_secret_values(self) -> list[dict]:
        r = self._http.get("/api/v1/admin/secret-values/")
        r.raise_for_status()
        payload = r.json()
        return payload if isinstance(payload, list) else payload.get("items", [])

    def create_secret_value(self, *, name: str, value: str, description: str = "") -> dict:
        return self._post(
            "/api/v1/admin/secret-values/",
            json={"name": name, "value": value, "description": description},
        ).json()

    def delete_secret_value(self, secret_id: str) -> None:
        r = self._http.delete(f"/api/v1/admin/secret-values/{secret_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def list_mcp_servers(self) -> list[dict]:
        r = self._http.get("/api/v1/admin/mcp-servers")
        r.raise_for_status()
        payload = r.json()
        return payload if isinstance(payload, list) else payload.get("items", [])

    def ensure_mcp_server(
        self,
        *,
        server_id: str,
        display_name: str,
        url: str,
        is_enabled: bool = True,
        config: dict | None = None,
    ) -> dict:
        for s in self.list_mcp_servers():
            if s.get("id") == server_id:
                return s
        body: dict[str, Any] = {
            "id": server_id,
            "display_name": display_name,
            "url": url,
            "is_enabled": is_enabled,
            "config": config or {},
        }
        return self._post("/api/v1/admin/mcp-servers", json=body).json()

    def delete_mcp_server(self, server_id: str) -> None:
        r = self._http.delete(f"/api/v1/admin/mcp-servers/{server_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def ensure_skill(self, *, skill_id: str, name: str, content: str) -> dict:
        # Skills route accepts unique ``id`` on POST; 409 on duplicate.
        r = self._http.post(
            "/api/v1/admin/skills",
            json={"id": skill_id, "name": name, "content": content},
        )
        if r.status_code == 409:
            # Fetch existing (GET by id path)
            g = self._http.get(f"/api/v1/admin/skills/{skill_id}")
            g.raise_for_status()
            return g.json()
        r.raise_for_status()
        return r.json()

    def delete_skill(self, skill_id: str) -> None:
        r = self._http.delete(f"/api/v1/admin/skills/{skill_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def toggle_heartbeat(self, *, channel_id: str, enabled: bool) -> dict:
        return self._post(
            f"/api/v1/admin/channels/{channel_id}/heartbeat/toggle",
            json={"enabled": enabled},
        ).json()

    def create_channel_binding(
        self,
        *,
        channel_id: str,
        integration_type: str,
        client_id: str,
        display_name: str | None = None,
        dispatch_config: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "integration_type": integration_type,
            "client_id": client_id,
        }
        if display_name:
            body["display_name"] = display_name
        if dispatch_config:
            body["dispatch_config"] = dispatch_config
        r = self._http.post(
            f"/api/v1/channels/{channel_id}/integrations",
            json=body,
        )
        # 409 means a binding with the same (channel, client_id) already exists.
        if r.status_code == 409:
            listing = self._http.get(f"/api/v1/channels/{channel_id}/integrations")
            listing.raise_for_status()
            for b in listing.json().get("bindings", []):
                if b.get("client_id") == client_id:
                    return b
        r.raise_for_status()
        return r.json()

    # --- auth (for JWT minting used by the browser layer) ------------------

    def login(self, *, email: str, password: str) -> dict:
        """Mint access + refresh tokens via the normal login route.

        Returns ``{"access_token": ..., "refresh_token": ..., "user": {...}}``.
        Used by the capture layer to seed the browser's localStorage under
        the Zustand persist key ``agent-auth``.
        """
        r = httpx.post(
            f"{self._api_url}/auth/login",
            json={"email": email, "password": password},
            timeout=_DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    # --- context -----------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "SpindrelClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
