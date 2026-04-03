import json
import uuid
from collections.abc import Generator
from typing import Any

import httpx


class AgentClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self._base_url = base_url
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def chat(
        self, message: str, session_id: uuid.UUID, bot_id: str, client_id: str = "cli"
    ) -> dict[str, Any]:
        resp = self._http.post(
            "/chat",
            json={
                "message": message,
                "session_id": str(session_id),
                "client_id": client_id,
                "bot_id": bot_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def chat_stream(
        self,
        message: str,
        session_id: uuid.UUID,
        bot_id: str,
        client_id: str = "cli",
        channel_id: str | None = None,
        model_override: str | None = None,
        model_provider_id_override: str | None = None,
        attachments: list[dict] | None = None,
        audio_data: str | None = None,
        audio_format: str | None = None,
        audio_native: bool | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream SSE events from the agent loop. Yields parsed event dicts."""
        body: dict[str, Any] = {
            "message": message,
            "session_id": str(session_id),
            "client_id": client_id,
            "bot_id": bot_id,
        }
        if channel_id is not None:
            body["channel_id"] = channel_id
        if model_override is not None:
            body["model_override"] = model_override
        if model_provider_id_override is not None:
            body["model_provider_id_override"] = model_provider_id_override
        if attachments:
            body["attachments"] = attachments
        if audio_data is not None:
            body["audio_data"] = audio_data
        if audio_format is not None:
            body["audio_format"] = audio_format
        if audio_native is not None:
            body["audio_native"] = audio_native

        with self._http.stream(
            "POST",
            "/chat/stream",
            json=body,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    yield json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

    def submit_tool_result(self, request_id: str, result: str) -> None:
        resp = self._http.post(
            "/chat/tool_result",
            json={"request_id": request_id, "result": result},
        )
        resp.raise_for_status()

    def cancel(self, bot_id: str, client_id: str = "cli") -> dict:
        """Cancel an in-progress agent loop."""
        resp = self._http.post(
            "/chat/cancel",
            json={"bot_id": bot_id, "client_id": client_id},
        )
        resp.raise_for_status()
        return resp.json()

    def check_secrets(self, message: str) -> dict:
        """Pre-flight secret detection check."""
        resp = self._http.post(
            "/chat/check-secrets",
            json={"message": message},
        )
        resp.raise_for_status()
        return resp.json()

    def list_sessions(self, client_id: str | None = None) -> list[dict]:
        params = {}
        if client_id:
            params["client_id"] = client_id
        resp = self._http.get("/sessions", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_session(self, session_id: uuid.UUID) -> dict:
        resp = self._http.get(f"/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    def delete_session(self, session_id: uuid.UUID) -> None:
        resp = self._http.delete(f"/sessions/{session_id}")
        resp.raise_for_status()

    def transcribe(self, audio_bytes: bytes) -> str | None:
        """Send raw float32 PCM audio to the server for transcription."""
        try:
            resp = self._http.post(
                "/transcribe",
                content=audio_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
            resp.raise_for_status()
            return resp.json().get("text") or None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def summarize_session(self, session_id: uuid.UUID) -> dict:
        resp = self._http.post(f"/sessions/{session_id}/summarize")
        resp.raise_for_status()
        return resp.json()

    def list_bots(self) -> list[dict]:
        resp = self._http.get("/bots")
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict:
        resp = self._http.get("/health")
        resp.raise_for_status()
        return resp.json()

    def list_tools(self) -> list[dict]:
        resp = self._http.get("/api/v1/admin/tools")
        resp.raise_for_status()
        return resp.json()

    def execute_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        resp = self._http.post(
            f"/api/v1/admin/tools/{tool_name}/execute",
            json={"arguments": arguments or {}},
        )
        resp.raise_for_status()
        return resp.json()

    # --- New API methods ---

    def get_task(self, task_id: str) -> dict:
        """Get task status by ID."""
        resp = self._http.get(f"/api/v1/admin/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    def list_channels(self, bot_id: str | None = None) -> dict:
        """List channels with optional bot_id filter. Returns paginated response."""
        params: dict[str, Any] = {"page_size": 100}
        if bot_id:
            params["bot_id"] = bot_id
        resp = self._http.get("/api/v1/admin/channels", params=params)
        resp.raise_for_status()
        return resp.json()

    def decide_approval(self, approval_id: str, approved: bool) -> dict:
        """Decide on a pending approval request."""
        resp = self._http.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json={"approved": approved, "decided_by": "cli:user"},
        )
        resp.raise_for_status()
        return resp.json()

    def create_api_key(self, name: str, scopes: list[str] | None = None) -> dict:
        """Create a new API key. Returns the full key (shown only once)."""
        resp = self._http.post(
            "/api/v1/admin/api-keys",
            json={"name": name, "scopes": scopes or []},
        )
        resp.raise_for_status()
        return resp.json()

    def close(self):
        self._http.close()
