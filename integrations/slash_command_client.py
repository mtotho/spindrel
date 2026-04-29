"""Reusable client for integration-owned slash command surfaces.

Integrations such as Slack and Discord own transport details: ack/defer,
platform argument parsing, message splitting, and local platform-only commands.
The command semantics live on the agent server behind
``/api/v1/slash-commands/execute`` so harness and non-harness channels cannot
drift between web, Slack, Discord, and future integrations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class SlashCommandExecution:
    command_id: str
    result_type: str
    payload: dict[str, Any]
    fallback_text: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SlashCommandExecution":
        return cls(
            command_id=str(payload.get("command_id") or ""),
            result_type=str(payload.get("result_type") or ""),
            payload=dict(payload.get("payload") or {}),
            fallback_text=str(payload.get("fallback_text") or ""),
        )


class SlashCommandClientError(RuntimeError):
    """Raised when the slash-command host rejects or fails a command."""


class SlashCommandClient:
    """HTTP client for the backend slash-command host."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._http = http or httpx.AsyncClient()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def ensure_channel(self, *, client_id: str, bot_id: str) -> dict[str, Any]:
        response = await self._http.post(
            f"{self.base_url}/api/v1/channels",
            json={"client_id": client_id, "bot_id": bot_id},
            headers=self._headers(),
            timeout=10.0,
        )
        if response.status_code >= 400:
            raise SlashCommandClientError(_response_error(response))
        return dict(response.json())

    async def execute(
        self,
        *,
        command_id: str,
        channel_id: str | None = None,
        session_id: str | None = None,
        current_session_id: str | None = None,
        args: list[str] | None = None,
    ) -> SlashCommandExecution:
        body: dict[str, Any] = {
            "command_id": command_id,
            "args": list(args or []),
        }
        if channel_id:
            body["channel_id"] = channel_id
        if session_id:
            body["session_id"] = session_id
        if current_session_id:
            body["current_session_id"] = current_session_id

        response = await self._http.post(
            f"{self.base_url}/api/v1/slash-commands/execute",
            json=body,
            headers=self._headers(),
            timeout=120.0,
        )
        if response.status_code >= 400:
            raise SlashCommandClientError(_response_error(response))
        return SlashCommandExecution.from_payload(dict(response.json()))

    async def execute_for_client_channel(
        self,
        *,
        client_id: str,
        bot_id: str,
        command_id: str,
        args: list[str] | None = None,
        current_session_id: str | None = None,
    ) -> SlashCommandExecution:
        channel = await self.ensure_channel(client_id=client_id, bot_id=bot_id)
        channel_id = channel.get("id")
        if not channel_id:
            raise SlashCommandClientError("Server did not return a channel id.")
        return await self.execute(
            command_id=command_id,
            channel_id=str(channel_id),
            current_session_id=current_session_id,
            args=args,
        )


def _response_error(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except Exception:
        detail = None
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if detail:
        return str(detail)
    text = response.text.strip()
    if text:
        return text[:500]
    return f"HTTP {response.status_code}"
