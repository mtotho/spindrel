import uuid
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
