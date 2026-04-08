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
        client_id: str | None = None,
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
        if client_id:
            payload["client_id"] = client_id

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
        client_id: str | None = None,
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
        if client_id:
            payload["client_id"] = client_id

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

    # -- Bot admin endpoints --

    async def create_bot(self, bot_data: dict[str, Any]) -> dict:
        """POST /api/v1/admin/bots — create a bot, return BotOut."""
        resp = await self._client.post("/api/v1/admin/bots", json=bot_data)
        resp.raise_for_status()
        return resp.json()

    async def get_bot(self, bot_id: str) -> dict:
        """GET /api/v1/admin/bots/{bot_id} — return BotOut."""
        resp = await self._client.get(f"/api/v1/admin/bots/{bot_id}")
        resp.raise_for_status()
        return resp.json()

    async def update_bot(self, bot_id: str, updates: dict[str, Any]) -> dict:
        """PATCH /api/v1/admin/bots/{bot_id} — return updated BotOut."""
        resp = await self._client.patch(f"/api/v1/admin/bots/{bot_id}", json=updates)
        resp.raise_for_status()
        return resp.json()

    async def delete_bot(self, bot_id: str, force: bool = True) -> None:
        """DELETE /api/v1/admin/bots/{bot_id}."""
        resp = await self._client.delete(
            f"/api/v1/admin/bots/{bot_id}", params={"force": str(force).lower()}
        )
        resp.raise_for_status()

    # -- Channel admin endpoints --

    async def get_channel(self, channel_id: str) -> dict:
        """GET /api/v1/admin/channels/{channel_id} — return ChannelDetailOut."""
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_channel_settings(self, channel_id: str) -> dict:
        """GET /api/v1/admin/channels/{channel_id}/settings."""
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}/settings")
        resp.raise_for_status()
        return resp.json()

    async def update_channel_settings(
        self, channel_id: str, updates: dict[str, Any]
    ) -> dict:
        """PATCH /api/v1/admin/channels/{channel_id}/settings."""
        resp = await self._client.patch(
            f"/api/v1/admin/channels/{channel_id}/settings", json=updates
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_channel(self, channel_id: str) -> None:
        """DELETE /api/v1/channels/{channel_id}."""
        resp = await self._client.delete(f"/api/v1/channels/{channel_id}")
        # 204 = deleted, 404 = already gone — both are fine
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    # -- Generic HTTP methods --

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.post(path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.put(path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.patch(path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.delete(path, **kwargs)

    # -- Bot member endpoints (multi-bot channels) --

    async def create_channel(self, channel_data: dict[str, Any]) -> dict:
        """POST /api/v1/channels — create a channel, return ChannelOut."""
        resp = await self._client.post("/api/v1/channels", json=channel_data)
        resp.raise_for_status()
        return resp.json()

    async def list_bot_members(self, channel_id: str) -> list[dict]:
        """GET /api/v1/channels/{channel_id}/bot-members."""
        resp = await self._client.get(f"/api/v1/channels/{channel_id}/bot-members")
        resp.raise_for_status()
        return resp.json()

    async def add_bot_member(self, channel_id: str, bot_id: str) -> dict:
        """POST /api/v1/channels/{channel_id}/bot-members."""
        resp = await self._client.post(
            f"/api/v1/channels/{channel_id}/bot-members",
            json={"bot_id": bot_id},
        )
        resp.raise_for_status()
        return resp.json()

    async def remove_bot_member(self, channel_id: str, bot_id: str) -> None:
        """DELETE /api/v1/channels/{channel_id}/bot-members/{bot_id}."""
        resp = await self._client.delete(
            f"/api/v1/channels/{channel_id}/bot-members/{bot_id}"
        )
        resp.raise_for_status()

    async def update_bot_member_config(
        self, channel_id: str, bot_id: str, config: dict[str, Any]
    ) -> dict:
        """PATCH /api/v1/channels/{channel_id}/bot-members/{bot_id}/config."""
        resp = await self._client.patch(
            f"/api/v1/channels/{channel_id}/bot-members/{bot_id}/config",
            json=config,
        )
        resp.raise_for_status()
        return resp.json()

    # -- Helpers --

    async def create_temp_bot(
        self,
        model: str,
        provider_id: str | None = None,
        tools: list[str] | None = None,
        system_prompt: str = "You are a test bot. Follow instructions exactly.",
    ) -> str:
        """Create a temporary bot for testing. Returns bot_id. Caller must delete."""
        bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
        bot_data: dict[str, Any] = {
            "id": bot_id,
            "name": f"E2E Temp ({model})",
            "model": model,
            "system_prompt": system_prompt,
            "local_tools": tools or ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        }
        if provider_id:
            bot_data["provider_id"] = provider_id
        await self.create_bot(bot_data)
        return bot_id

    @staticmethod
    def new_channel_id() -> str:
        """Generate a unique channel ID for test isolation."""
        return str(uuid.uuid4())

    @staticmethod
    def new_client_id(prefix: str = "e2e-test") -> str:
        """Generate a unique client_id for channel creation."""
        return f"{prefix}:{uuid.uuid4().hex[:12]}"

    @staticmethod
    def derive_channel_id(client_id: str) -> str:
        """Derive the channel UUID that the server will create for a client_id.

        Mirrors app/services/channels.py:derive_channel_id().
        """
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"channel:{client_id}"))
