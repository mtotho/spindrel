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

    def transcribe(self, audio_bytes: bytes) -> str | None:
        """Send raw float32 PCM audio to the server for transcription.

        Returns transcribed text, or None if the server doesn't support it.
        """
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

    def close(self):
        self._http.close()
