"""DiscordRenderer — Phase F of the Integration Delivery refactor.

Mirror of ``integrations/slack/renderer.py``. Replaces the legacy
``integrations/discord/dispatcher.py`` (the main-process queued path)
and the in-subprocess long-poll path that drove ``stream_chat`` from
the Discord bot process. The Discord subprocess now just enqueues
turns via ``submit_chat`` (POST /chat → 202) and the main-process
DiscordRenderer consumes the channel-events bus to render the response.

Discord's REST API rate limit story is gentler than Slack's — the per-
channel bucket is 5 messages per 5 seconds for ``POST .../messages``
and one ``PATCH .../messages/{id}`` per 0.25s. We still use a shared
``SlackRateLimiter`` instance (renamed conceptually) so the same
debounce semantics apply: tokens accumulate, edits coalesce on a 0.8s
window, the safety pass picks up queued text after a flush completes.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import ClassVar

import httpx

from integrations.sdk import (
    Capability, ChannelEvent, ChannelEventKind,
    DispatchTarget, OutboundAction, DeliveryReceipt,
    ToolOutputDisplay, ToolResultRenderingSupport,
    get_channel_for_integration,
    renderer_registry,
)
from integrations.discord.client import bot_attribution
from integrations.discord.formatting import format_response_for_discord, split_for_discord
from integrations.discord.target import DiscordTarget
from integrations.discord.tool_result_adapter import build_tool_result_payload

logger = logging.getLogger(__name__)


# Tunables — match the Slack values for cross-renderer consistency.
# Discord can technically push faster but the user-visible bug is the
# same shape (rapid edits → cache lag), so the same coalesce window
# fixes it on Discord too.
STREAM_FLUSH_INTERVAL = 0.8
STREAM_MAX_CHARS = 1900  # Discord max is 2000; leave headroom for the trailing ellipsis


_http = httpx.AsyncClient(timeout=30.0)
DISCORD_API = "https://discord.com/api/v10"


class _DiscordTurnContext:
    """Per-turn streaming state for one Discord placeholder message."""

    __slots__ = (
        "bot_id",
        "channel_id",
        "thinking_message_id",
        "accumulated_text",
        "last_flush_at",
        "flush_lock",
        "pending_text",
    )

    def __init__(self, bot_id: str, channel_id: str) -> None:
        self.bot_id = bot_id
        self.channel_id = channel_id
        self.thinking_message_id: str | None = None
        self.accumulated_text: str = ""
        self.last_flush_at: float = time.monotonic()
        self.flush_lock = asyncio.Lock()
        self.pending_text: str | None = None


class _DiscordRenderRegistry:
    """Per-channel, per-turn ``_DiscordTurnContext`` registry."""

    def __init__(self) -> None:
        self._by_channel: dict[str, dict[str, _DiscordTurnContext]] = {}

    def get_or_create(
        self, channel_id: str, turn_id: str, *, bot_id: str
    ) -> _DiscordTurnContext:
        bucket = self._by_channel.setdefault(channel_id, {})
        ctx = bucket.get(turn_id)
        if ctx is None:
            ctx = _DiscordTurnContext(bot_id=bot_id, channel_id=channel_id)
            bucket[turn_id] = ctx
        return ctx

    def get(self, channel_id: str, turn_id: str) -> _DiscordTurnContext | None:
        bucket = self._by_channel.get(channel_id)
        return bucket.get(turn_id) if bucket else None

    def find_by_turn_id(self, turn_id: str) -> tuple[str, _DiscordTurnContext] | None:
        """Look up a turn context by turn_id across all channels.

        Returns ``(channel_id, ctx)`` if found, else ``None``. Used by
        the ``NEW_MESSAGE`` placeholder handoff to locate the streaming
        context via the message's ``correlation_id`` (which equals the
        turn_id).
        """
        for channel_id, bucket in self._by_channel.items():
            ctx = bucket.get(turn_id)
            if ctx is not None:
                return (channel_id, ctx)
        return None

    def discard(self, channel_id: str, turn_id: str) -> None:
        bucket = self._by_channel.get(channel_id)
        if bucket is None:
            return
        bucket.pop(turn_id, None)
        if not bucket:
            del self._by_channel[channel_id]

    def reset(self) -> None:
        self._by_channel.clear()


discord_render_contexts = _DiscordRenderRegistry()


class DiscordRenderer:
    """Channel renderer for Discord delivery.

    Capability set excludes ``THREADING`` (Discord threads exist but the
    delivery layer doesn't model them yet) and ``REACTIONS`` (we use
    Discord reactions only as inbound hourglass acks, not as outbound
    state). Approval buttons map to Discord components instead of Block
    Kit blocks.
    """

    integration_id: ClassVar[str] = "discord"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.RICH_TEXT,
        Capability.ATTACHMENTS,
        Capability.IMAGE_UPLOAD,
        Capability.FILE_UPLOAD,
        Capability.STREAMING_EDIT,
        Capability.RICH_TOOL_RESULTS,
        Capability.APPROVAL_BUTTONS,
        Capability.DISPLAY_NAMES,
        Capability.MENTIONS,
    })
    tool_result_rendering: ClassVar[ToolResultRenderingSupport | None] = (
        ToolResultRenderingSupport.from_manifest({
            "modes": ["compact", "full", "none"],
            "content_types": [
                "text/plain",
                "text/markdown",
                "application/json",
                "application/vnd.spindrel.components+json",
                "application/vnd.spindrel.diff+text",
                "application/vnd.spindrel.file-listing+json",
            ],
            "view_keys": [
                "core.search_results",
                "core.command_result",
                "core.machine_target_status",
            ],
            "interactive": False,
            "unsupported_fallback": "badge",
            "placement": "same_message",
            "limits": {
                "max_table_rows": 12,
                "max_links": 8,
                "max_code_chars": 1700,
            },
        })
    )

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, DiscordTarget):
            return DeliveryReceipt.failed(
                f"DiscordRenderer received non-discord target: {type(target).__name__}",
                retryable=False,
            )

        kind = event.kind
        try:
            if kind == ChannelEventKind.TURN_STARTED:
                return await self._handle_turn_started(event, target)
            if kind == ChannelEventKind.TURN_STREAM_TOKEN:
                return await self._handle_stream_token(event, target)
            if kind == ChannelEventKind.TURN_STREAM_TOOL_START:
                await self._force_flush(event, target)
                return DeliveryReceipt.ok()
            if kind == ChannelEventKind.TURN_STREAM_TOOL_RESULT:
                await self._force_flush(event, target)
                return DeliveryReceipt.skipped("tool_result subsumed by next stream flush")
            if kind == ChannelEventKind.TURN_ENDED:
                return await self._handle_turn_ended(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._handle_new_message(event, target)
            if kind == ChannelEventKind.APPROVAL_REQUESTED:
                return await self._handle_approval_requested(event, target)
        except Exception as exc:
            logger.exception("DiscordRenderer.render: unexpected failure for %s", kind.value)
            return DeliveryReceipt.failed(f"unexpected: {exc}", retryable=True)

        return DeliveryReceipt.skipped(f"discord does not handle {kind.value}")

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped("discord outbound actions are handled inline")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        # Discord doesn't expose a server-side delete-attachment API for
        # bot-uploaded files; the legacy dispatcher returned False here
        # too. The renderer mirrors that.
        return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_turn_started(
        self, event: ChannelEvent, target: DiscordTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        bot_id = getattr(payload, "bot_id", "") or ""
        turn_id = str(getattr(payload, "turn_id", "") or "")
        if not turn_id:
            return DeliveryReceipt.failed("turn_started without turn_id", retryable=False)

        ctx = discord_render_contexts.get_or_create(
            target.channel_id, turn_id, bot_id=bot_id
        )
        if ctx.thinking_message_id is not None:
            return DeliveryReceipt.ok(external_id=ctx.thinking_message_id)

        result = await self._post_message(
            target, content="\u23f3 *thinking...*",
        )
        if not result.success:
            return result
        message_id = (result.data or {}).get("id")
        ctx.thinking_message_id = message_id
        ctx.last_flush_at = time.monotonic()
        return DeliveryReceipt.ok(external_id=message_id)

    async def _handle_stream_token(
        self, event: ChannelEvent, target: DiscordTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        delta = getattr(payload, "delta", "") or ""
        ctx = discord_render_contexts.get(target.channel_id, turn_id)
        if ctx is None:
            ctx = discord_render_contexts.get_or_create(
                target.channel_id, turn_id,
                bot_id=getattr(payload, "bot_id", "") or "",
            )
        ctx.accumulated_text += delta
        return await self._maybe_flush(ctx, target)

    async def _handle_turn_ended(
        self, event: ChannelEvent, target: DiscordTarget
    ) -> DeliveryReceipt:
        """Serialize the final edit against any in-flight `_do_flush`.

        Same race as the Slack renderer: when the renderer is invoked
        via both ``subscribe_all`` and the outbox drainer, a streaming
        ``_do_flush`` PATCH can race with the final-result PATCH for the
        same message id. Acquire the per-turn ``flush_lock`` so the
        streaming flush completes first.
        """
        turn_id = str(getattr(event.payload, "turn_id", "") or "")
        ctx = discord_render_contexts.get(target.channel_id, turn_id)

        if ctx is not None:
            async with ctx.flush_lock:
                return await self._handle_turn_ended_locked(event, target, ctx)
        return await self._handle_turn_ended_locked(event, target, None)

    async def _handle_turn_ended_locked(
        self,
        event: ChannelEvent,
        target: DiscordTarget,
        ctx: "_DiscordTurnContext | None",
    ) -> DeliveryReceipt:
        """Streaming UX finalization — best-effort only.

        Updates the thinking placeholder with the final response text.
        Never posts new messages — that's the outbox's job via
        ``NEW_MESSAGE``. If the placeholder update fails, the outbox
        still delivers the message durably.
        """
        if ctx is None or not ctx.thinking_message_id:
            # No placeholder to update — outbox NEW_MESSAGE handles
            # delivery. Nothing for the streaming path to do.
            return DeliveryReceipt.ok()

        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        result_text = getattr(payload, "result", None) or ""
        error_text = getattr(payload, "error", None) or ""

        if result_text:
            body_text = result_text
        elif error_text:
            body_text = f"⚠️ *Agent error: {error_text}*"
        else:
            body_text = "*(no response)*"

        formatted = format_response_for_discord(body_text)
        chunks = split_for_discord(formatted) or [formatted]

        # Update the placeholder with the first chunk (best-effort).
        edit_result = await self._edit_message(
            target, ctx.thinking_message_id, chunks[0],
        )
        # Don't post overflow chunks here — NEW_MESSAGE owns final delivery.
        # The placeholder edit is purely cosmetic so the "thinking..." text
        # doesn't linger. If the edit fails, no loss — outbox delivers it.

        discord_render_contexts.discard(target.channel_id, turn_id)
        return DeliveryReceipt.ok(
            external_id=ctx.thinking_message_id,
        )

    async def _handle_new_message(
        self, event: ChannelEvent, target: DiscordTarget
    ) -> DeliveryReceipt:
        """Deliver a message to Discord (the durable path).

        This is the sole durable delivery path. If a streaming
        placeholder exists for this turn (via ``correlation_id``),
        update it with the final text (idempotent). Otherwise post
        as a new message. Matches the Slack renderer's handoff pattern
        documented in ``docs/integrations/design.md``.
        """
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"discord skips internal role={role}")
        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == "discord":
                return DeliveryReceipt.skipped(
                    "discord skips own-origin user message (echo prevention)"
                )

        text = getattr(msg, "content", "") or ""
        formatted = format_response_for_discord(text)
        chunks = split_for_discord(formatted) or [formatted]
        msg_metadata = getattr(msg, "metadata", None) or {}
        tool_results = msg_metadata.get("tool_results") or []
        display_mode = ToolOutputDisplay.COMPACT
        suffix = ""
        embeds: list[dict] = []
        if tool_results and role != "user":
            display_mode = await _resolve_tool_output_display(target.channel_id)
            suffix, embeds = build_tool_result_payload(
                tool_results,
                display_mode=display_mode,
                support=self.tool_result_rendering,
            )
            if suffix:
                chunks[0] = f"{chunks[0]}\n\n{suffix}" if chunks[0] else suffix

        # Placeholder handoff: if a thinking message exists for this turn,
        # update it with the first chunk instead of posting a new message.
        # The update is idempotent — if TURN_ENDED already wrote the same
        # text, this is a no-op from Discord's perspective.
        correlation_id = str(getattr(msg, "correlation_id", "") or "")
        ctx_info = (
            discord_render_contexts.find_by_turn_id(correlation_id)
            if correlation_id else None
        )
        placeholder_used = False
        if ctx_info is not None:
            ctx_channel_id, ctx = ctx_info
            if ctx.thinking_message_id:
                edit_result = await self._edit_message(
                    target, ctx.thinking_message_id, chunks[0], embeds=embeds,
                )
                if edit_result.success:
                    placeholder_used = True
                    chunks = chunks[1:]
                    embeds = []
            # Context cleanup — NEW_MESSAGE owns this.
            discord_render_contexts.discard(ctx_channel_id, correlation_id)

        # Post remaining chunks (all of them if no placeholder, or
        # overflow chunks if the placeholder took the first).
        for chunk in chunks:
            result = await self._post_message(target, content=chunk, embeds=embeds)
            embeds = []
            if not result.success:
                return result
        return DeliveryReceipt.ok()

    async def _handle_approval_requested(
        self, event: ChannelEvent, target: DiscordTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        approval_id = getattr(payload, "approval_id", "") or ""
        bot_id = getattr(payload, "bot_id", "") or ""
        tool_name = getattr(payload, "tool_name", "") or ""
        arguments = getattr(payload, "arguments", {}) or {}
        reason = getattr(payload, "reason", None)

        embed = _build_tool_approval_embed(bot_id, tool_name, arguments, reason)
        components = _build_tool_approval_components(approval_id, tool_name)

        body = {
            "content": (
                f"Tool approval required: {tool_name} (approval {approval_id})"
            ),
            "embeds": [embed],
            "components": components,
        }
        return await self._post_raw(target, body)

    # ------------------------------------------------------------------
    # Streaming helpers
    # ------------------------------------------------------------------

    async def _maybe_flush(
        self, ctx: _DiscordTurnContext, target: DiscordTarget
    ) -> DeliveryReceipt:
        now = time.monotonic()
        if now - ctx.last_flush_at < STREAM_FLUSH_INTERVAL:
            ctx.pending_text = ctx.accumulated_text
            return DeliveryReceipt.ok()
        if ctx.flush_lock.locked():
            ctx.pending_text = ctx.accumulated_text
            return DeliveryReceipt.ok()
        return await self._do_flush(ctx, target)

    async def _force_flush(
        self, event: ChannelEvent, target: DiscordTarget
    ) -> None:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        ctx = discord_render_contexts.get(target.channel_id, turn_id)
        if ctx is None or not ctx.accumulated_text:
            return
        await self._do_flush(ctx, target)

    async def _do_flush(
        self, ctx: _DiscordTurnContext, target: DiscordTarget
    ) -> DeliveryReceipt:
        async with ctx.flush_lock:
            if ctx.thinking_message_id is None:
                return DeliveryReceipt.ok()
            text = _truncate_for_stream(ctx.accumulated_text)
            result = await self._edit_message(target, ctx.thinking_message_id, text)
            ctx.last_flush_at = time.monotonic()

            # Safety pass — same pattern as SlackRenderer.
            if (
                ctx.pending_text is not None
                and ctx.pending_text != ctx.accumulated_text
            ):
                queued = ctx.pending_text
                ctx.pending_text = None
                queued_text = _truncate_for_stream(queued)
                await self._edit_message(target, ctx.thinking_message_id, queued_text)
                ctx.last_flush_at = time.monotonic()
            else:
                ctx.pending_text = None

            return result

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _post_message(
        self,
        target: DiscordTarget,
        *,
        content: str,
        embeds: list[dict] | None = None,
    ) -> "_DiscordCallResult":
        body = {"content": content}
        if embeds:
            body["embeds"] = embeds
        return await self._post_raw(target, body, return_call=True)

    async def _post_raw(
        self,
        target: DiscordTarget,
        body: dict,
        *,
        return_call: bool = False,
    ) -> DeliveryReceipt | "_DiscordCallResult":
        url = f"{DISCORD_API}/channels/{target.channel_id}/messages"
        result = await self._call(url, "POST", target.token, body)
        if return_call:
            return result
        return result.to_receipt()

    async def _edit_message(
        self,
        target: DiscordTarget,
        message_id: str,
        content: str,
        embeds: list[dict] | None = None,
    ) -> DeliveryReceipt:
        url = (
            f"{DISCORD_API}/channels/{target.channel_id}/messages/{message_id}"
        )
        body = {"content": content}
        if embeds:
            body["embeds"] = embeds
        result = await self._call(url, "PATCH", target.token, body)
        return result.to_receipt()

    async def _call(
        self, url: str, method: str, token: str, body: dict,
    ) -> "_DiscordCallResult":
        headers = {"Authorization": f"Bot {token}"}
        try:
            response = await _http.request(method, url, json=body, headers=headers)
        except httpx.RequestError as exc:
            logger.warning("DiscordRenderer: %s %s connection error: %s", method, url, exc)
            return _DiscordCallResult.failed(f"connection error: {exc}", retryable=True)

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            logger.warning(
                "DiscordRenderer: 429 on %s %s, Retry-After=%.1fs",
                method, url, retry_after,
            )
            return _DiscordCallResult.failed(
                f"discord 429 (Retry-After={retry_after}s)", retryable=True,
            )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if not response.is_success:
            retryable = response.status_code >= 500
            return _DiscordCallResult.failed(
                f"discord {method} HTTP {response.status_code}",
                retryable=retryable,
            )

        return _DiscordCallResult.ok(data)

    async def _upload_actions(
        self,
        target: DiscordTarget,
        actions: list,
    ) -> None:
        try:
            from integrations.discord.client import upload_file
        except Exception:
            logger.exception("DiscordRenderer: failed to import upload helper")
            return
        import base64
        for raw in actions:
            action = raw if isinstance(raw, dict) else _action_to_dict(raw)
            if action.get("type") not in ("upload_image", "upload_file"):
                continue
            data = action.get("data")
            if not data:
                continue
            try:
                img_bytes = base64.b64decode(data)
            except Exception:
                continue
            try:
                await upload_file(
                    target.token,
                    target.channel_id,
                    img_bytes,
                    action.get("filename") or "generated.png",
                    content=action.get("caption"),
                )
            except Exception:
                logger.exception("DiscordRenderer: upload_file failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_for_stream(text: str) -> str:
    text = (text or "").lstrip()
    if not text:
        return ""
    if len(text) > STREAM_MAX_CHARS - 4:
        return text[:STREAM_MAX_CHARS - 4] + " ..."
    return text + " ..."


def _action_to_dict(action) -> dict:
    if isinstance(action, dict):
        return action
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(action) and not isinstance(action, type):
            return asdict(action)
    except Exception:
        pass
    return {}


async def _resolve_tool_output_display(discord_channel_id: str) -> str:
    client_id = f"discord:{discord_channel_id}"
    try:
        channel = await get_channel_for_integration("discord", client_id)
        if channel is not None:
            return ToolOutputDisplay.normalize(channel.tool_output_display)
    except Exception:
        logger.debug("discord tool_output_display lookup failed, using default", exc_info=True)
    return ToolOutputDisplay.COMPACT


def _build_tool_approval_embed(
    bot_id: str, tool_name: str, arguments: dict, reason: str | None,
) -> dict:
    import json as _json
    args_preview = _json.dumps(arguments, indent=2)[:500]
    return {
        "title": "\U0001f512 Tool approval required",
        "color": 0xFF9900,
        "fields": [
            {"name": "Bot", "value": f"`{bot_id}`", "inline": True},
            {"name": "Tool", "value": f"`{tool_name}`", "inline": True},
            {"name": "Reason", "value": reason or "Policy requires approval", "inline": False},
            {"name": "Arguments", "value": f"```json\n{args_preview}\n```", "inline": False},
        ],
    }


def _build_tool_approval_components(
    approval_id: str, tool_name: str,
) -> list:
    tool_label = tool_name[:30] if len(tool_name) > 30 else tool_name
    row1 = [
        {
            "type": 2, "style": 3,
            "label": f"Allow {tool_label}",
            "custom_id": f"aa:{approval_id}",
        },
        {
            "type": 2, "style": 1,
            "label": "Approve this run",
            "custom_id": f"ap:{approval_id}",
        },
        {
            "type": 2, "style": 4,
            "label": "Deny",
            "custom_id": f"dn:{approval_id}",
        },
    ]
    return [{"type": 1, "components": row1}]


# ---------------------------------------------------------------------------
# Internal call result
# ---------------------------------------------------------------------------


class _DiscordCallResult:
    __slots__ = ("success", "data", "error", "retryable")

    def __init__(
        self,
        success: bool,
        *,
        data: dict | None = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.success = success
        self.data = data
        self.error = error
        self.retryable = retryable

    @classmethod
    def ok(cls, data: dict) -> "_DiscordCallResult":
        return cls(True, data=data)

    @classmethod
    def failed(cls, error: str, *, retryable: bool) -> "_DiscordCallResult":
        return cls(False, error=error, retryable=retryable)

    def to_receipt(self) -> DeliveryReceipt:
        if self.success:
            return DeliveryReceipt.ok(
                external_id=(self.data or {}).get("id") if self.data else None,
            )
        return DeliveryReceipt.failed(
            self.error or "unknown", retryable=self.retryable,
        )


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------


def _register() -> None:
    if renderer_registry.get(DiscordRenderer.integration_id) is None:
        renderer_registry.register(DiscordRenderer())


_register()
