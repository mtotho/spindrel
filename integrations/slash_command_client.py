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


@dataclass(frozen=True)
class SlashCommandAskTarget:
    bot_id: str
    label: str
    is_primary: bool = False
    is_member: bool = False


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

    async def _get_json(self, path: str, *, timeout: float = 10.0) -> Any:
        response = await self._http.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise SlashCommandClientError(_response_error(response))
        return response.json()

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

    async def list_channel_ask_targets(
        self,
        *,
        client_id: str,
        bot_id: str,
    ) -> list[SlashCommandAskTarget]:
        """Return the bots that can be actively addressed in this channel.

        The web UI lets any configured bot be added as a channel member. Active
        routing is narrower: the target set is the channel's primary bot plus
        configured member bots.
        """
        channel = await self.ensure_channel(client_id=client_id, bot_id=bot_id)
        channel_id = channel.get("id")
        if not channel_id:
            raise SlashCommandClientError("Server did not return a channel id.")

        full_channel = await self._get_json(f"/api/v1/channels/{channel_id}")
        if isinstance(full_channel, dict):
            channel = full_channel

        bot_labels = await self._bot_labels()
        primary_bot_id = str(channel.get("bot_id") or bot_id)
        targets: list[SlashCommandAskTarget] = [
            SlashCommandAskTarget(
                bot_id=primary_bot_id,
                label=bot_labels.get(primary_bot_id) or primary_bot_id,
                is_primary=True,
            )
        ]
        seen = {primary_bot_id}

        for member in channel.get("member_bots") or []:
            if not isinstance(member, dict):
                continue
            member_bot_id = str(member.get("bot_id") or "")
            if not member_bot_id or member_bot_id in seen:
                continue
            targets.append(
                SlashCommandAskTarget(
                    bot_id=member_bot_id,
                    label=str(
                        member.get("bot_name")
                        or bot_labels.get(member_bot_id)
                        or member_bot_id
                    ),
                    is_member=True,
                )
            )
            seen.add(member_bot_id)

        return targets

    async def _bot_labels(self) -> dict[str, str]:
        try:
            bots_payload = await self._get_json("/bots")
        except Exception:
            return {}
        if not isinstance(bots_payload, list):
            return {}
        labels: dict[str, str] = {}
        for bot in bots_payload:
            if not isinstance(bot, dict):
                continue
            bot_id = str(bot.get("id") or "")
            if not bot_id:
                continue
            labels[bot_id] = str(bot.get("name") or bot_id)
        return labels

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


def resolve_ask_target(
    targets: list[SlashCommandAskTarget],
    raw_target: str,
) -> SlashCommandAskTarget | None:
    target = raw_target.strip().lower()
    if not target:
        return None
    for candidate in targets:
        if candidate.bot_id.lower() == target or candidate.label.lower() == target:
            return candidate
    return None


def format_ask_target_options(
    targets: list[SlashCommandAskTarget],
    *,
    command: str = "/ask",
) -> str:
    if not targets:
        return "No bot targets are configured for this channel."

    lines = [
        f"Usage: `{command} <bot-id> <message>`",
        "",
        "Available in this channel:",
    ]
    for target in targets:
        role = "primary" if target.is_primary else "member"
        lines.append(f"  `{target.bot_id}` - {target.label} ({role})")
    return "\n".join(lines)


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
