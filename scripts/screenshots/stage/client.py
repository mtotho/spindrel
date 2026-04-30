"""Thin HTTP client for the e2e agent-server API.

Idempotent helpers keyed on ``screenshot:*`` prefixes so reruns dedupe by
client_id / bot id. Uses the admin-scoped API key for all mutations; no JWT
path here (the browser layer handles JWTs for localStorage seeding).
"""
from __future__ import annotations

import logging
import time
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

    def update_bot(self, bot_id: str, **fields: Any) -> dict:
        """PATCH a bot's config. Only fields named in ``BotUpdateIn`` are honored.

        Used by chat-content stagers to enable delegation (``delegation_config``),
        pin tools that would otherwise sit behind discovery (``pinned_tools``),
        or enroll skills (``skills``) on the screenshot bot just for the time
        the capture is staged. Idempotent — PATCH replaces only the provided
        keys; reruns reapply the same values.
        """
        if self._dry_run:
            logger.info("DRY-RUN PATCH /admin/bots/%s fields=%s", bot_id, sorted(fields))
            return {"id": bot_id, "dry_run": True}
        r = self._http.patch(f"/api/v1/admin/bots/{bot_id}", json=fields)
        if r.status_code >= 400:
            logger.error("PATCH /admin/bots/%s -> %s body=%s",
                         bot_id, r.status_code, r.text[:300])
        r.raise_for_status()
        return r.json()

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

    def update_channel_settings(self, channel_id: str, **fields: Any) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN PATCH /admin/channels/%s/settings fields=%s", channel_id, sorted(fields))
            return {"id": channel_id, "dry_run": True, **fields}
        r = self._http.patch(f"/api/v1/admin/channels/{channel_id}/settings", json=fields)
        if r.status_code >= 400:
            logger.error(
                "PATCH /admin/channels/%s/settings -> %s body=%s",
                channel_id,
                r.status_code,
                r.text[:300],
            )
        r.raise_for_status()
        return r.json()

    def purge_test_channels(self) -> list[str]:
        """Delete every channel whose ``client_id`` is not in the allow-list.

        Allow-list: ``screenshot:*`` (our staged scenario channels),
        ``orchestrator:*`` (Orchestrator-managed home/system channels),
        and the bare ``default`` channel.

        Returns the list of deleted ``client_id`` values for logging.
        Idempotent: a clean instance returns an empty list. Safe to run
        before every capture — production channels never use the patterns
        we delete (`chat:e2e:*`, `e2e-test:*`, `dbg-*`, `frag-*`,
        `smoke-*`, etc. are all test-runner debris).
        """
        deleted: list[str] = []
        for ch in self.list_channels():
            cid = ch.get("client_id") or ""
            if cid.startswith("screenshot:"):
                continue
            if cid.startswith("orchestrator:"):
                continue
            if cid == "default":
                continue
            if self._dry_run:
                deleted.append(cid)
                continue
            try:
                self.delete_channel(ch["id"])
                deleted.append(cid)
            except Exception as e:
                logger.warning("purge: failed to delete %s: %s", cid, e)
        return deleted

    # --- workspaces --------------------------------------------------------

    def list_workspaces(self) -> list[dict]:
        """List workspaces. The API path is `/api/v1/workspaces` (no admin
        prefix — the admin variant returns 404)."""
        return self._get("/api/v1/workspaces").json()

    # --- projects ---------------------------------------------------------

    def list_projects(self) -> list[dict]:
        r = self._http.get("/api/v1/projects")
        if r.status_code == 404:
            raise RuntimeError(
                "Project screenshot staging requires an e2e server with /api/v1/projects. "
                "Deploy the Project workspace API/UI before running `stage --only project-workspace`."
            )
        r.raise_for_status()
        return r.json()

    def ensure_project(
        self,
        *,
        workspace_id: str,
        name: str,
        slug: str,
        root_path: str,
        description: str | None = None,
        prompt: str | None = None,
        prompt_file_path: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "workspace_id": workspace_id,
            "name": name,
            "slug": slug,
            "root_path": root_path,
            "description": description,
            "prompt": prompt,
            "prompt_file_path": prompt_file_path,
        }
        existing = next((p for p in self.list_projects() if p.get("slug") == slug), None)
        if existing:
            if self._dry_run:
                logger.info("DRY-RUN PATCH /projects/%s body=%s", existing.get("id"), body)
                return {**existing, **body}
            r = self._http.patch(f"/api/v1/projects/{existing['id']}", json=body)
            if r.status_code >= 400:
                logger.error("PATCH /projects/%s -> %s body=%s", existing["id"], r.status_code, r.text[:300])
            r.raise_for_status()
            return r.json()
        return self._post("/api/v1/projects", json=body).json()

    def update_project(self, project_id: str, **fields: Any) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN PATCH /projects/%s fields=%s", project_id, sorted(fields))
            return {"id": project_id, **fields}
        r = self._http.patch(f"/api/v1/projects/{project_id}", json=fields)
        if r.status_code >= 400:
            logger.error("PATCH /projects/%s -> %s body=%s", project_id, r.status_code, r.text[:300])
        r.raise_for_status()
        return r.json()

    def list_project_blueprints(self) -> list[dict]:
        r = self._http.get("/api/v1/projects/blueprints")
        if r.status_code == 404:
            raise RuntimeError(
                "Project Blueprint screenshot staging requires an e2e server with /api/v1/projects/blueprints."
            )
        r.raise_for_status()
        return r.json()

    def ensure_project_blueprint(
        self,
        *,
        name: str,
        slug: str,
        default_root_path_pattern: str,
        description: str | None = None,
        prompt: str | None = None,
        prompt_file_path: str | None = None,
        folders: list[str] | None = None,
        files: dict[str, str] | None = None,
        knowledge_files: dict[str, str] | None = None,
        repos: list[dict] | None = None,
        setup_commands: list[dict] | None = None,
        env: dict[str, str] | None = None,
        required_secrets: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "description": description,
            "default_root_path_pattern": default_root_path_pattern,
            "prompt": prompt,
            "prompt_file_path": prompt_file_path,
            "folders": folders or [],
            "files": files or {},
            "knowledge_files": knowledge_files or {},
            "repos": repos or [],
            "setup_commands": setup_commands or [],
            "env": env or {},
            "required_secrets": required_secrets or [],
        }
        existing = next((b for b in self.list_project_blueprints() if b.get("slug") == slug), None)
        if existing:
            if self._dry_run:
                logger.info("DRY-RUN PATCH /projects/blueprints/%s body=%s", existing.get("id"), body)
                return {**existing, **body}
            r = self._http.patch(f"/api/v1/projects/blueprints/{existing['id']}", json=body)
            if r.status_code >= 400:
                logger.error("PATCH /projects/blueprints/%s -> %s body=%s", existing["id"], r.status_code, r.text[:300])
            r.raise_for_status()
            return r.json()
        return self._post("/api/v1/projects/blueprints", json=body).json()

    def create_project_from_blueprint(
        self,
        *,
        blueprint_id: str,
        workspace_id: str,
        name: str,
        slug: str,
        root_path: str,
        secret_bindings: dict[str, str | None] | None = None,
    ) -> dict:
        existing = next((p for p in self.list_projects() if p.get("slug") == slug), None)
        if existing:
            return existing
        return self._post(
            "/api/v1/projects/from-blueprint",
            json={
                "blueprint_id": blueprint_id,
                "workspace_id": workspace_id,
                "name": name,
                "slug": slug,
                "root_path": root_path,
                "secret_bindings": secret_bindings or {},
            },
        ).json()

    def update_project_secret_bindings(self, project_id: str, bindings: dict[str, str | None]) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN PATCH /projects/%s/secret-bindings bindings=%s", project_id, sorted(bindings))
            return {"id": project_id, "dry_run": True}
        r = self._http.patch(f"/api/v1/projects/{project_id}/secret-bindings", json={"bindings": bindings})
        if r.status_code >= 400:
            logger.error("PATCH /projects/%s/secret-bindings -> %s body=%s", project_id, r.status_code, r.text[:300])
        r.raise_for_status()
        return r.json()

    def get_project_setup(self, project_id: str) -> dict:
        r = self._http.get(f"/api/v1/projects/{project_id}/setup")
        if r.status_code == 404:
            raise RuntimeError(
                "Project setup screenshot staging requires an e2e server with /api/v1/projects/{id}/setup."
            )
        r.raise_for_status()
        return r.json()

    def run_project_setup(self, project_id: str) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN POST /projects/%s/setup/runs", project_id)
            return {"id": "dry-run", "status": "succeeded", "dry_run": True}
        r = self._http.post(f"/api/v1/projects/{project_id}/setup/runs")
        if r.status_code >= 400:
            logger.error("POST /projects/%s/setup/runs -> %s body=%s", project_id, r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()

    def create_project_instance(self, project_id: str) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN POST /projects/%s/instances", project_id)
            return {"id": "dry-run-instance", "status": "ready", "dry_run": True}
        r = self._http.post(f"/api/v1/projects/{project_id}/instances", json={"owner_kind": "manual"})
        if r.status_code >= 400:
            logger.error("POST /projects/%s/instances -> %s body=%s", project_id, r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()

    def create_project_run_receipt(self, project_id: str, payload: dict[str, Any]) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN POST /projects/%s/run-receipts keys=%s", project_id, sorted(payload))
            return {"id": "dry-run-receipt", "project_id": project_id, **payload}
        r = self._http.post(f"/api/v1/projects/{project_id}/run-receipts", json=payload)
        if r.status_code == 404:
            logger.warning("POST /projects/%s/run-receipts unavailable; capture shim will seed receipt UI", project_id)
            return {"id": "missing-run-receipt-endpoint", "project_id": project_id, **payload}
        if r.status_code >= 400:
            logger.error("POST /projects/%s/run-receipts -> %s body=%s", project_id, r.status_code, r.text[:500])
        r.raise_for_status()
        return r.json()

    # --- skills ------------------------------------------------------------

    def list_skills(self, *, limit: int = 100) -> list[dict]:
        """List skills (admin scope so all bot/folder roots are visible)."""
        return self._get("/api/v1/admin/skills", params={"limit": limit}).json()

    # --- chat --------------------------------------------------------------

    def send_message(self, *, channel_id: str, text: str) -> dict:
        """Send a single message. Returns the 202 body. Caller waits separately."""
        return self._post(
            "/chat",
            json={"channel_id": channel_id, "message": text},
        ).json()

    def start_session_plan_mode(self, session_id: str) -> dict:
        """Flip a session into ``planning`` mode so ``publish_plan`` is allowed."""
        if self._dry_run:
            logger.info("DRY-RUN POST /sessions/%s/plan/start", session_id)
            return {"dry_run": True}
        # ``sessions.router`` is mounted at /sessions (no /api/v1 prefix).
        r = self._http.post(f"/sessions/{session_id}/plan/start", json={})
        r.raise_for_status()
        return r.json()

    def get_active_session_id(self, channel_id: str) -> str | None:
        # Public ``GET /channels/{id}`` includes ``active_session_id``; the
        # admin variant strips it (only the public schema carries it).
        r = self._http.get(f"/api/v1/channels/{channel_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("active_session_id")

    def reset_channel(self, channel_id: str) -> dict:
        """Start a fresh session on the channel — the prior conversation is preserved.

        Used before ``seed_turn`` so each chat-content capture renders a clean
        single-turn conversation instead of accumulating from prior runs.
        """
        if self._dry_run:
            logger.info("DRY-RUN POST /channels/%s/reset", channel_id)
            return {"channel_id": channel_id, "dry_run": True}
        r = self._http.post(f"/api/v1/channels/{channel_id}/reset", json={})
        r.raise_for_status()
        return r.json()

    def get_channel_state(self, channel_id: str) -> dict:
        r = self._http.get(f"/api/v1/channels/{channel_id}/state")
        r.raise_for_status()
        return r.json()

    def list_channel_workspace_files(
        self,
        channel_id: str,
        *,
        include_data: bool = False,
        data_prefix: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"include_data": include_data}
        if data_prefix:
            params["data_prefix"] = data_prefix
        r = self._http.get(
            f"/api/v1/channels/{channel_id}/workspace/files",
            params=params,
        )
        r.raise_for_status()
        return r.json().get("files", [])

    def delete_channel_workspace_file(self, channel_id: str, path: str) -> None:
        if self._dry_run:
            logger.info("DRY-RUN DELETE /channels/%s/workspace/files path=%s", channel_id, path)
            return
        r = self._http.delete(
            f"/api/v1/channels/{channel_id}/workspace/files",
            params={"path": path},
        )
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def write_channel_workspace_file(self, channel_id: str, path: str, content: str) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN PUT /channels/%s/workspace/files/content path=%s", channel_id, path)
            return {"path": path, "dry_run": True}
        r = self._http.put(
            f"/api/v1/channels/{channel_id}/workspace/files/content",
            params={"path": path},
            json={"content": content},
        )
        r.raise_for_status()
        return r.json()

    def write_workspace_file(self, workspace_id: str, path: str, content: str) -> dict:
        if self._dry_run:
            logger.info("DRY-RUN PUT /workspaces/%s/files/content path=%s", workspace_id, path)
            return {"path": path, "dry_run": True}
        r = self._http.put(
            f"/api/v1/workspaces/{workspace_id}/files/content",
            params={"path": path},
            json={"content": content},
        )
        r.raise_for_status()
        return r.json()

    def list_session_messages(self, session_id: str, *, limit: int = 20) -> list[dict]:
        r = self._http.get(
            f"/api/v1/sessions/{session_id}/messages",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json()

    def list_channel_sessions(self, channel_id: str, *, limit: int = 20) -> list[dict]:
        r = self._http.get(
            f"/api/v1/channels/{channel_id}/sessions",
            params={"limit": limit},
        )
        r.raise_for_status()
        return r.json().get("sessions", [])

    def seed_turn(
        self,
        *,
        channel_id: str,
        message: str,
        bot_id: str | None = None,
        expected_tool: str | None = None,
        timeout_s: float = 120.0,
        poll_interval_s: float = 1.5,
        wait_subagents: bool = False,
        subagent_timeout_s: float = 180.0,
    ) -> dict:
        """Drive the agent loop deterministically for chat-content captures.

        Posts a user turn, polls ``/channels/{id}/state`` until ``active_turns``
        drains (the canonical "done thinking" signal), and — when
        ``expected_tool`` is set — verifies the latest assistant message's
        ``tool_calls`` includes the named tool. Raises ``RuntimeError`` if the
        turn does not settle in ``timeout_s`` or if the expected tool was not
        called (so a flaky model selection fails the staging step instead of
        producing a misleading screenshot).

        Returns the final assistant ``MessageOut`` dict so callers can inspect
        ``tool_calls`` / ``metadata`` if they need to chain assertions.
        """
        if self._dry_run:
            logger.info(
                "DRY-RUN seed_turn channel=%s expected_tool=%s msg=%r",
                channel_id, expected_tool, message[:80],
            )
            return {"role": "assistant", "content": "", "tool_calls": [], "dry_run": True}

        body: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if bot_id:
            body["bot_id"] = bot_id
        chat_resp = self._post("/chat", json=body).json()
        session_id = chat_resp.get("session_id")
        if not session_id:
            raise RuntimeError(f"seed_turn: /chat response missing session_id: {chat_resp}")

        deadline = time.monotonic() + timeout_s
        last_state: dict | None = None
        while time.monotonic() < deadline:
            time.sleep(poll_interval_s)
            last_state = self.get_channel_state(channel_id)
            # spawn_subagents schedules ephemeral _subagent_* sub-sessions
            # whose turn entries land in active_turns with is_primary=False.
            # The parent's UI message is finalized as soon as the tool call
            # returns; subagent activity continues in the background and is
            # irrelevant to the screenshot. Filter so only primary (parent)
            # turns gate the poll.
            primary = [
                t for t in (last_state.get("active_turns") or [])
                if t.get("is_primary", True)
            ]
            if not primary:
                break
        else:
            raise RuntimeError(
                f"seed_turn: turn did not settle within {timeout_s}s "
                f"(last active_turns={last_state.get('active_turns') if last_state else None})"
            )

        if wait_subagents:
            # Subagent turns render their own WEB SEARCH / READ_FILE rows on
            # the parent channel with a typing cursor while still in flight,
            # which would leak a "still streaming" artifact into a capture.
            # Wait once more — until ALL turns drain — so the subagent row
            # paints its final body. Best-effort: timeout exits silently
            # (the parent message is already complete; subagent might still
            # be working but a partial render is the worst case, not a
            # broken capture).
            sub_deadline = time.monotonic() + subagent_timeout_s
            while time.monotonic() < sub_deadline:
                time.sleep(poll_interval_s)
                state = self.get_channel_state(channel_id)
                if not state.get("active_turns"):
                    break

        msgs = self.list_session_messages(session_id, limit=30)
        latest_assistant = next(
            (m for m in reversed(msgs) if m.get("role") == "assistant"),
            None,
        )
        if latest_assistant is None:
            raise RuntimeError(
                f"seed_turn: no assistant message found after settle "
                f"(session_id={session_id})"
            )

        if expected_tool:
            tool_calls = latest_assistant.get("tool_calls") or []
            names: list[str] = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or tc.get("name")
                if name:
                    names.append(name)
            if expected_tool not in names:
                raise RuntimeError(
                    f"seed_turn: expected tool {expected_tool!r} in tool_calls, "
                    f"got {names!r} (session_id={session_id})"
                )

        return latest_assistant

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

    # --- workspace spatial canvas -----------------------------------------

    def list_spatial_nodes(self) -> list[dict]:
        """List spatial nodes — also seeds rows for any channel/bot that
        doesn't yet have a position. Idempotent: callers can use this purely
        as a "force phyllotaxis seeding" trigger before captures."""
        return self._get("/api/v1/workspace/spatial/nodes").json().get("nodes", [])

    def pin_canvas_widget(
        self,
        *,
        tool_name: str,
        envelope: dict,
        source_kind: str = "channel",
        source_channel_id: str | None = None,
        source_bot_id: str | None = None,
        display_label: str | None = None,
        world_x: float | None = None,
        world_y: float | None = None,
        world_w: float | None = None,
        world_h: float | None = None,
    ) -> dict:
        """Atomically pin a widget onto the workspace spatial canvas.

        Wraps ``POST /api/v1/workspace/spatial/widget-pins`` which creates the
        ``widget_dashboard_pins`` row on the reserved ``workspace:spatial``
        slug AND its matching ``workspace_spatial_nodes`` row in one
        transaction. Use this instead of ``create_pin(dashboard_key=
        "workspace:spatial", ...)`` so the canvas node is in the same commit
        as the pin row.
        """
        body: dict[str, Any] = {
            "source_kind": source_kind,
            "tool_name": tool_name,
            "envelope": envelope,
        }
        if source_channel_id:
            body["source_channel_id"] = source_channel_id
        if source_bot_id:
            body["source_bot_id"] = source_bot_id
        if display_label:
            body["display_label"] = display_label
        if world_x is not None:
            body["world_x"] = world_x
        if world_y is not None:
            body["world_y"] = world_y
        if world_w is not None:
            body["world_w"] = world_w
        if world_h is not None:
            body["world_h"] = world_h
        return self._post(
            "/api/v1/workspace/spatial/widget-pins",
            json=body,
        ).json()

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

    def create_scheduled_task(
        self,
        *,
        bot_id: str,
        title: str,
        prompt: str,
        channel_id: str | None = None,
        scheduled_at: str | None = None,
        recurrence: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "bot_id": bot_id,
            "title": title,
            "prompt": prompt,
            "task_type": "scheduled",
        }
        if channel_id:
            body["channel_id"] = channel_id
        if scheduled_at:
            body["scheduled_at"] = scheduled_at
        if recurrence:
            body["recurrence"] = recurrence
        return self._post("/api/v1/admin/tasks", json=body).json()

    def list_admin_tasks(
        self,
        *,
        bot_id: str | None = None,
        channel_id: str | None = None,
        task_type: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if bot_id:
            params["bot_id"] = bot_id
        if channel_id:
            params["channel_id"] = channel_id
        if task_type:
            params["task_type"] = task_type
        return self._get("/api/v1/admin/tasks", params=params).json().get("tasks", [])

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

    # --- integrations lifecycle ------------------------------------------

    def set_integration_status(self, *, integration_id: str, status: str) -> dict:
        """Toggle an integration between ``available`` and ``enabled``.

        Idempotent on the server side — returning early when the requested
        status equals the current one.
        """
        if self._dry_run:
            logger.info("DRY-RUN PUT /admin/integrations/%s/status -> %s", integration_id, status)
            return {"integration_id": integration_id, "status": status, "dry_run": True}
        r = self._http.put(
            f"/api/v1/admin/integrations/{integration_id}/status",
            json={"status": status},
        )
        if r.status_code >= 400:
            logger.error("PUT /integrations/%s/status -> %s body=%s",
                         integration_id, r.status_code, r.text[:300])
        r.raise_for_status()
        return r.json()

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

    def set_heartbeat(
        self,
        *,
        channel_id: str,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
        prompt: str | None = None,
        model: str | None = None,
        dispatch_mode: str | None = None,
        append_spatial_prompt: bool | None = None,
    ) -> dict:
        """Update heartbeat config (interval, prompt, dispatch, etc.).

        Wraps ``PATCH /admin/channels/{id}/heartbeat`` (also accepts PUT) per
        ``app/routers/api_v1_admin/channels.py:1246``. Only fields that are
        non-None are sent — the server uses ``model_dump(exclude_unset=True)``
        and applies them as a partial update.
        """
        body: dict[str, Any] = {}
        if enabled is not None:
            body["enabled"] = enabled
        if interval_minutes is not None:
            body["interval_minutes"] = interval_minutes
        if prompt is not None:
            body["prompt"] = prompt
        if model is not None:
            body["model"] = model
        if dispatch_mode is not None:
            body["dispatch_mode"] = dispatch_mode
        if append_spatial_prompt is not None:
            body["append_spatial_prompt"] = append_spatial_prompt
        if self._dry_run:
            logger.info("DRY-RUN PATCH /admin/channels/%s/heartbeat body=%s", channel_id, body)
            return {"channel_id": channel_id, "dry_run": True, **body}
        r = self._http.patch(
            f"/api/v1/admin/channels/{channel_id}/heartbeat",
            json=body,
        )
        if r.status_code >= 400:
            logger.error(
                "PATCH /admin/channels/%s/heartbeat -> %s body=%s",
                channel_id, r.status_code, r.text[:300],
            )
        r.raise_for_status()
        return r.json()

    # --- webhooks ----------------------------------------------------------

    def list_webhooks(self) -> list[dict]:
        r = self._http.get("/api/v1/admin/webhooks")
        r.raise_for_status()
        return r.json()

    def ensure_webhook(
        self,
        *,
        name: str,
        url: str,
        events: list[str],
        description: str = "",
        is_active: bool = True,
    ) -> dict:
        """Create a webhook (or return the existing one with the same ``name``).

        The admin API does not enforce name-uniqueness, so reruns must dedupe
        client-side. We key on ``name`` because ``screenshot:*`` prefixing is
        not honored by the webhook model (no ``client_id``).
        """
        for existing in self.list_webhooks():
            if existing.get("name") == name:
                return existing
        body = {
            "name": name,
            "url": url,
            "events": events,
            "is_active": is_active,
            "description": description,
        }
        return self._post("/api/v1/admin/webhooks", json=body).json().get("endpoint", {})

    def delete_webhook(self, webhook_id: str) -> None:
        r = self._http.delete(f"/api/v1/admin/webhooks/{webhook_id}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

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
