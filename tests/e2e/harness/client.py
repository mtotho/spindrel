"""E2E HTTP client for interacting with the agent-server."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from .streaming import StreamEvent, StreamResult

if TYPE_CHECKING:
    from .config import E2EConfig


@dataclass
class ChatResponse:
    """Response from the non-streaming /chat endpoint."""

    session_id: str
    response: str
    client_actions: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class E2EClient:
    """Async HTTP client for E2E testing against a running agent-server."""

    def __init__(self, config: E2EConfig) -> None:
        self.config = config
        self.default_bot_id = config.bot_id
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(config.request_timeout),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- Chat endpoints --

    async def chat(
        self,
        message: str,
        bot_id: str | None = None,
        channel_id: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a message to the non-streaming /chat endpoint."""
        payload: dict[str, Any] = {
            "message": message,
            "bot_id": bot_id or self.default_bot_id,
            "msg_metadata": {"sender_type": "human", "source": "e2e-test"},
            **kwargs,
        }
        if channel_id:
            payload["channel_id"] = channel_id

        resp = await self._client.post("/chat", json=payload)
        resp.raise_for_status()
        body = resp.json()

        return ChatResponse(
            session_id=body.get("session_id", ""),
            response=body.get("response", ""),
            client_actions=body.get("client_actions", []),
            raw=body,
        )

    async def chat_stream(
        self,
        message: str,
        bot_id: str | None = None,
        channel_id: str | None = None,
        **kwargs: Any,
    ) -> StreamResult:
        """Send a message to the streaming /chat/stream endpoint and collect all events."""
        payload: dict[str, Any] = {
            "message": message,
            "bot_id": bot_id or self.default_bot_id,
            "msg_metadata": {"sender_type": "human", "source": "e2e-test"},
            **kwargs,
        }
        if channel_id:
            payload["channel_id"] = channel_id

        result = StreamResult()

        async with self._client.stream("POST", "/chat/stream", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                result.raw_lines.append(line)
                event = StreamEvent.from_line(line)
                if event:
                    result.add_event(event)

        return result

    # -- Admin/utility endpoints --

    async def health(self) -> dict:
        """GET /health or /api/v1/admin/health (tries admin first for richer data)."""
        resp = await self._client.get("/api/v1/admin/health")
        if resp.status_code == 200:
            return resp.json()
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def list_bots(self) -> list[dict]:
        """GET /bots."""
        resp = await self._client.get("/bots")
        resp.raise_for_status()
        data = resp.json()
        return data["bots"] if isinstance(data, dict) and "bots" in data else data

    async def list_channels(self) -> list[dict]:
        """GET /api/v1/admin/channels."""
        resp = await self._client.get("/api/v1/admin/channels")
        resp.raise_for_status()
        data = resp.json()
        return data["channels"] if isinstance(data, dict) and "channels" in data else data

    # -- Generic HTTP methods --

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.post(path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.put(path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.delete(path, **kwargs)

    # -- Helpers --

    @staticmethod
    def new_channel_id() -> str:
        """Generate a unique channel ID for test isolation."""
        return str(uuid.uuid4())
