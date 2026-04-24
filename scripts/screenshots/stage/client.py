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
    ) -> dict:
        """Create a channel (or return the existing one with matching client_id).

        The ``POST /api/v1/channels`` handler goes through ``get_or_create_channel``
        which dedupes on ``client_id`` — reruns are safe.
        """
        body = {
            "client_id": client_id,
            "bot_id": bot_id,
            "name": name or client_id,
            "private": private,
        }
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
