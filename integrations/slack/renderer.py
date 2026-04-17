"""SlackRenderer — Phase F of the Integration Delivery refactor.

The single, in-process Slack delivery path. Replaces:

- ``integrations/slack/dispatcher.py`` (the legacy ``SlackDispatcher`` —
  the main-process queued path).
- ``integrations/slack/message_handlers.py:_run_dispatch`` (the
  in-subprocess long-poll path that posted directly to Slack).

The original user-reported bug — Slack mobile sometimes never refreshes
to the agent's final reply — was caused by these two paths racing each
other on ``chat.update`` storms with no shared rate limiter and no
coalesce window. SlackRenderer collapses both into one path with:

1. A single shared ``SlackRateLimiter`` (per-method token bucket).
2. A 0.8s ``chat.update`` coalesce window (matches the legacy debounce).
3. A "safety pass" — if a token arrives while a flush is in flight,
   the latest accumulated text is queued and one final ``chat.update``
   fires after the in-flight call completes.

The renderer subscribes to the channel-events bus via the registry
``app.integrations.renderer_registry``. NEW_MESSAGE events reach this
renderer via the outbox drainer ONLY — ``IntegrationDispatcherTask``
short-circuits outbox-durable kinds in its dispatch loop, so there is
no longer a "two paths racing for the same msg.id" foot-gun (see
``ChannelEventKind.is_outbox_durable``). Streaming kinds
(``TURN_STREAM_*``, ``TURN_STARTED``, ``TURN_ENDED``) still flow via
the bus because they're inherently ephemeral.
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
    ToolBadge, ToolOutputDisplay, extract_tool_badges,
)
from integrations.slack.client import bot_attribution
from integrations.slack.formatting import markdown_to_slack_mrkdwn, split_for_slack
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import (
    STREAM_FLUSH_INTERVAL,
    STREAM_MAX_CHARS,
    TurnContext,
    slack_render_contexts,
)
from integrations.slack.target import SlackTarget

logger = logging.getLogger(__name__)


# Module-level shared httpx client. Mirrors the per-helper clients in
# integrations/slack/client.py — we use a separate one here so the
# renderer's lifecycle is decoupled from the legacy helpers (which the
# renderer also calls into via ``post_message`` etc.).
_http = httpx.AsyncClient(timeout=30.0)


class SlackRenderer:
    """Channel renderer for Slack delivery.

    Capability declaration is the full Slack feature set. Anything the
    drainer passes us is something Slack supports — gating happens
    upstream so we don't have to handle the "Slack can't do this"
    case here.
    """

    integration_id: ClassVar[str] = "slack"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.RICH_TEXT,
        Capability.THREADING,
        Capability.REACTIONS,
        Capability.INLINE_BUTTONS,
        Capability.ATTACHMENTS,
        Capability.IMAGE_UPLOAD,
        Capability.FILE_UPLOAD,
        Capability.FILE_DELETE,
        Capability.STREAMING_EDIT,
        Capability.APPROVAL_BUTTONS,
        Capability.DISPLAY_NAMES,
        Capability.MENTIONS,
    })

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, SlackTarget):
            return DeliveryReceipt.failed(
                f"SlackRenderer received non-slack target: {type(target).__name__}",
                retryable=False,
            )

        kind = event.kind
        try:
            if kind == ChannelEventKind.TURN_STARTED:
                return await self._handle_turn_started(event, target)
            if kind == ChannelEventKind.TURN_STREAM_TOKEN:
                return await self._handle_stream_token(event, target)
            if kind == ChannelEventKind.TURN_STREAM_TOOL_START:
                return await self._handle_tool_start(event, target)
            if kind == ChannelEventKind.TURN_STREAM_TOOL_RESULT:
                # Tool results aren't rendered as their own message; the
                # next text_delta will resume the stream. Force-flush so
                # any queued text reaches the user before the tool runs.
                await self._force_flush(event, target)
                # Stash envelope for later Block Kit rendering in TURN_ENDED.
                payload = event.payload
                turn_id = str(getattr(payload, "turn_id", "") or "")
                envelope = getattr(payload, "envelope", None)
                if envelope and turn_id:
                    ctx = slack_render_contexts.get(target.channel_id, turn_id)
                    if ctx is None:
                        # Context may not exist if TURN_STARTED hasn't arrived
                        # yet (race) — create lazily so we don't lose envelopes.
                        ctx = slack_render_contexts.get_or_create(
                            target.channel_id, turn_id,
                            bot_id=getattr(payload, "bot_id", "") or "",
                        )
                    ctx.tool_envelopes.append(envelope)
                return DeliveryReceipt.skipped("tool_result subsumed by next stream flush")
            if kind == ChannelEventKind.TURN_ENDED:
                return await self._handle_turn_ended(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._handle_new_message(event, target)
            if kind == ChannelEventKind.MESSAGE_UPDATED:
                return await self._handle_message_updated(event, target)
            if kind == ChannelEventKind.APPROVAL_REQUESTED:
                return await self._handle_approval_requested(event, target)
            if kind == ChannelEventKind.ATTACHMENT_DELETED:
                return await self._handle_attachment_deleted(event, target)
        except Exception as exc:
            logger.exception("SlackRenderer.render: unexpected failure for %s", kind.value)
            return DeliveryReceipt.failed(f"unexpected: {exc}", retryable=True)

        # Anything else (workflow_progress, heartbeat, tool_activity,
        # delivery_failed, replay_lapsed, shutdown): silently skip. The
        # outbox drainer marks the row delivered with the skip reason.
        return DeliveryReceipt.skipped(f"slack does not handle {kind.value}")

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        # Phase F focuses on bus-driven rendering. Sideband
        # ``OutboundAction``s (image upload, reaction toggle, raw
        # approval) come through ``TurnEndedPayload.client_actions``
        # and are handled inside ``_handle_turn_ended``.
        return DeliveryReceipt.skipped("slack outbound actions are handled inline")

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        if not isinstance(target, SlackTarget):
            return False
        slack_file_id = (attachment_metadata or {}).get("slack_file_id")
        if not target.token or not slack_file_id:
            return False
        try:
            from integrations.slack.uploads import delete_slack_file
            return await delete_slack_file(target.token, slack_file_id)
        except Exception:
            logger.exception("SlackRenderer.delete_attachment failed for %s", slack_file_id)
            return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_turn_started(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        bot_id = getattr(payload, "bot_id", "") or ""
        turn_id = str(getattr(payload, "turn_id", "") or "")
        if not turn_id:
            return DeliveryReceipt.failed("turn_started without turn_id", retryable=False)

        ctx = slack_render_contexts.get_or_create(
            target.channel_id, turn_id, bot_id=bot_id
        )
        if ctx.thinking_ts is not None:
            # Idempotent — already posted the placeholder for this turn.
            return DeliveryReceipt.ok(external_id=ctx.thinking_ts)

        attrs = bot_attribution(bot_id) if bot_id else {}
        body: dict = {
            "channel": target.channel_id,
            "text": "\u23f3 _thinking..._",
            **attrs,
        }
        if target.thread_ts and target.reply_in_thread:
            body["thread_ts"] = target.thread_ts

        result = await self._call_slack("chat.postMessage", target.token, body)
        if not result.success:
            return result
        data = result.data or {}
        ctx.thinking_ts = data.get("ts")
        ctx.thinking_channel = data.get("channel")
        ctx.last_flush_at = time.monotonic()
        return DeliveryReceipt.ok(external_id=ctx.thinking_ts)

    async def _handle_stream_token(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        delta = getattr(payload, "delta", "") or ""
        ctx = slack_render_contexts.get(target.channel_id, turn_id)
        if ctx is None:
            # Stream token arrived without a turn_started — drop the
            # placeholder requirement and create one lazily so we don't
            # silently lose tokens.
            ctx = slack_render_contexts.get_or_create(
                target.channel_id, turn_id,
                bot_id=getattr(payload, "bot_id", "") or "",
            )

        ctx.accumulated_text += delta
        return await self._maybe_flush(ctx, target)

    async def _handle_tool_start(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        # Force-flush any pending text so the user sees what the agent
        # had so far before the tool runs. The tool name itself isn't
        # surfaced in the placeholder; the next text_delta resumes the
        # stream.
        await self._force_flush(event, target)
        return DeliveryReceipt.ok()

    async def _handle_turn_ended(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        """Serialize the final chat.update against any in-flight `_do_flush`.

        The renderer is invoked via two paths concurrently — the
        ``subscribe_all`` bus subscription in
        ``app/services/channel_renderers.py`` AND the outbox drainer in
        ``app/services/outbox_drainer.py``. If a streaming-token render
        is mid-flight inside ``_do_flush`` for the same turn when
        ``TURN_ENDED`` arrives via the *other* path, two ``chat.update``
        calls race against the same ``ts``. Slack ``chat.update`` is
        idempotent on ``ts`` but NOT on body — the resulting final
        state is non-deterministic. Acquire the per-turn ``flush_lock``
        before touching ``ts`` so the streaming flush completes first.
        """
        turn_id = str(getattr(event.payload, "turn_id", "") or "")
        ctx = slack_render_contexts.get(target.channel_id, turn_id)

        if ctx is not None:
            async with ctx.flush_lock:
                return await self._handle_turn_ended_locked(event, target, ctx)
        return await self._handle_turn_ended_locked(event, target, None)

    async def _handle_turn_ended_locked(
        self,
        event: ChannelEvent,
        target: SlackTarget,
        ctx: TurnContext | None,
    ) -> DeliveryReceipt:
        """Streaming UX finalization — best-effort only.

        Updates the thinking placeholder with the final response text.
        Never posts new messages — that's the outbox's job via
        NEW_MESSAGE. If the placeholder update fails, the outbox still
        delivers the message durably.
        """
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        bot_id = getattr(payload, "bot_id", "") or ""

        if ctx is None or not ctx.thinking_ts or not ctx.thinking_channel:
            # No placeholder to update — outbox NEW_MESSAGE handles
            # delivery. Nothing for the streaming path to do.
            return DeliveryReceipt.ok()

        result_text = getattr(payload, "result", None) or ""
        error_text = getattr(payload, "error", None) or ""

        if result_text:
            body_text = result_text
        elif error_text:
            body_text = f":warning: _Agent error: {error_text}_"
        else:
            body_text = "_(no response)_"

        slack_text = markdown_to_slack_mrkdwn(body_text)
        chunks = split_for_slack(slack_text) or [slack_text]
        attrs = bot_attribution(bot_id) if bot_id else {}

        # Update the thinking placeholder with the first chunk.
        update_body: dict = {
            "channel": ctx.thinking_channel,
            "ts": ctx.thinking_ts,
            "text": chunks[0],
            **attrs,
        }
        update_result = await self._call_slack(
            "chat.update", target.token, update_body
        )
        if not update_result.success:
            # Placeholder update failed — discard context so NEW_MESSAGE
            # falls through to posting as a new message.
            slack_render_contexts.discard(target.channel_id, turn_id)
            return update_result

        # Upload any image / file actions attached to the turn.
        # These are supplementary (not the message itself) and only
        # exist on TurnEndedPayload, so they stay here.
        client_actions = getattr(payload, "client_actions", None) or []
        if client_actions:
            await self._upload_actions(target, attrs, client_actions)

        # Do NOT discard context — NEW_MESSAGE needs the thinking_ts
        # to update the placeholder instead of posting a duplicate.
        # NEW_MESSAGE owns context cleanup.
        return DeliveryReceipt.ok(external_id=ctx.thinking_ts)

    async def _handle_new_message(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        # Internal roles are never user-facing. Without this filter the
        # renderer happily serializes raw tool-result JSON (e.g.
        # ``{"ok": true, "bytes": 1181}`` from file_ops.write) into a
        # Slack message, attributed to the bare Slack App name because
        # there's no bot actor to pass through ``bot_attribution``.
        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"slack skips internal role={role}")

        # Echo prevention. Slack-origin user messages reach the bus via
        # ``turn_worker._persist_and_publish_user_message`` publishing a
        # NEW_MESSAGE, which the IntegrationDispatcherTask then routes
        # right back to this renderer. Posting it would re-display the
        # user's own message in their own Slack channel as an APP post.
        # Cross-integration mirroring (user types in web UI, message
        # should appear in Slack) still works — those user messages
        # have a different ``metadata["source"]``.
        #
        # Primary signal: ``metadata["source"] == "slack"`` set by
        # ``integrations/slack/message_handlers.py:msg_metadata`` and
        # threaded through ``turn_worker._persist_and_publish_user_message``
        # onto the DomainMessage. Fallback: legacy ``slack:`` prefix on
        # ``actor.id`` for messages persisted before metadata was threaded.
        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == "slack":
                return DeliveryReceipt.skipped(
                    "slack skips own-origin user message (echo prevention)"
                )
            actor = getattr(msg, "actor", None)
            actor_id = getattr(actor, "id", "") or "" if actor is not None else ""
            if actor_id.startswith("slack:"):
                return DeliveryReceipt.skipped(
                    "slack skips own-origin user message (echo prevention)"
                )

        # Use the message's actor for display attribution. Bot
        # messages get bot_attribution; user messages get the user's
        # display name. The legacy mirror path used the same pattern.
        actor = getattr(msg, "actor", None)
        attrs: dict = {}
        if actor is not None and getattr(actor, "kind", "") == "bot":
            attrs = bot_attribution(getattr(actor, "id", ""))
        elif actor is not None:
            display_name = getattr(actor, "display_name", None)
            if display_name:
                attrs["username"] = display_name

        text = getattr(msg, "content", "") or ""
        if not text.strip():
            return DeliveryReceipt.skipped("new_message with empty content")
        slack_text = markdown_to_slack_mrkdwn(text)
        chunks = split_for_slack(slack_text) or [slack_text]

        # If a thinking placeholder exists for this turn, update it
        # with the first chunk instead of posting a new message. This
        # is the handoff from the streaming path (TURN_ENDED updated
        # the placeholder best-effort) to the durable outbox path.
        # The update is idempotent — if TURN_ENDED already wrote the
        # same text, this is a no-op from Slack's perspective.
        correlation_id = str(getattr(msg, "correlation_id", "") or "")
        ctx_info = (
            slack_render_contexts.find_by_turn_id(correlation_id)
            if correlation_id else None
        )
        placeholder_used = False
        # The thinking placeholder is the bot's response slot — it was posted
        # with bot_attribution and Slack's chat.update cannot change username/
        # icon. Reusing it for a user message would stamp the user's text onto
        # a message that's permanently branded as the bot.
        if ctx_info is not None and role != "user":
            ctx_channel_id, ctx = ctx_info
            if ctx.thinking_ts and ctx.thinking_channel:
                update_body: dict = {
                    "channel": ctx.thinking_channel,
                    "ts": ctx.thinking_ts,
                    "text": chunks[0],
                    **attrs,
                }
                update_result = await self._call_slack(
                    "chat.update", target.token, update_body
                )
                if update_result.success:
                    placeholder_used = True
                    chunks = chunks[1:]
                # If update failed (placeholder deleted, etc.), fall
                # through to posting all chunks as new messages.
            # Context cleanup — NEW_MESSAGE owns this.
            slack_render_contexts.discard(ctx_channel_id, correlation_id)

        # Post chunks as new messages (all of them if no placeholder,
        # or remaining overflow chunks if the placeholder took the first).
        for chunk in chunks:
            body: dict = {
                "channel": target.channel_id,
                "text": chunk,
                **attrs,
            }
            if target.thread_ts and target.reply_in_thread:
                body["thread_ts"] = target.thread_ts
            result = await self._call_slack("chat.postMessage", target.token, body)
            if not result.success:
                return result

        # Render tool-call results per the channel's tool_output_display
        # setting: compact (default) posts a single tiny context line per
        # tool invocation; full posts the rich Block Kit widget; none
        # skips entirely. The raw widget JSON always remains in the
        # persisted Message.metadata, so the web UI is unaffected.
        msg_metadata = getattr(msg, "metadata", None) or {}
        tool_results = msg_metadata.get("tool_results") or []
        if tool_results:
            display_mode = await _resolve_tool_output_display(target.channel_id)
            tool_blocks: list[dict] = []
            if display_mode == ToolOutputDisplay.FULL:
                tool_blocks = _components_to_blocks(tool_results)
            elif display_mode == ToolOutputDisplay.COMPACT:
                badges = extract_tool_badges(tool_results)
                ctx_block = _badges_to_context_block(badges)
                if ctx_block is not None:
                    tool_blocks = [ctx_block]
            if tool_blocks:
                block_body: dict = {
                    "channel": target.channel_id,
                    "text": "(tool results)",
                    "blocks": tool_blocks[:50],
                    **attrs,
                }
                if target.thread_ts and target.reply_in_thread:
                    block_body["thread_ts"] = target.thread_ts
                await self._call_slack("chat.postMessage", target.token, block_body)

        return DeliveryReceipt.ok()

    async def _handle_message_updated(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        # Slack's chat.update needs a message ts to address. The legacy
        # path stored that on dispatch_config; the new flow expects it
        # on the typed payload. Until upstream publishers thread the
        # external_id through MessageUpdatedPayload, treat this as a
        # no-op skip.
        return DeliveryReceipt.skipped(
            "message_updated needs an external_id slack ts (not yet wired)"
        )

    async def _handle_approval_requested(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        approval_id = getattr(payload, "approval_id", "") or ""
        bot_id = getattr(payload, "bot_id", "") or ""
        tool_name = getattr(payload, "tool_name", "") or ""
        arguments = getattr(payload, "arguments", {}) or {}
        reason = getattr(payload, "reason", None)
        capability = getattr(payload, "capability", None)

        attrs = bot_attribution(bot_id) if bot_id else {}
        if capability:
            blocks = _build_capability_approval_blocks(
                approval_id, bot_id, capability,
            )
            fallback = (
                f"Capability activation: {capability.get('name', 'unknown')} "
                f"(approval {approval_id})"
            )
        else:
            blocks = _build_tool_approval_blocks(
                approval_id, bot_id, tool_name, arguments, reason,
            )
            fallback = (
                f"Tool approval required: {tool_name} (approval {approval_id})"
            )

        body: dict = {
            "channel": target.channel_id,
            "text": fallback,
            "blocks": blocks,
            **attrs,
        }
        if target.thread_ts and target.reply_in_thread:
            body["thread_ts"] = target.thread_ts

        return (await self._call_slack(
            "chat.postMessage", target.token, body
        )).to_receipt()

    async def _handle_attachment_deleted(
        self, event: ChannelEvent, target: SlackTarget
    ) -> DeliveryReceipt:
        payload = event.payload
        metadata = getattr(payload, "metadata", {}) or {}
        slack_file_id = metadata.get("slack_file_id")
        if not slack_file_id:
            return DeliveryReceipt.skipped("attachment_deleted without slack_file_id")
        try:
            from integrations.slack.uploads import delete_slack_file
            ok = await delete_slack_file(target.token, slack_file_id)
        except Exception as exc:
            logger.exception("SlackRenderer: file delete failed for %s", slack_file_id)
            return DeliveryReceipt.failed(str(exc), retryable=True)
        return DeliveryReceipt.ok() if ok else DeliveryReceipt.failed(
            "delete_slack_file returned False", retryable=True,
        )

    # ------------------------------------------------------------------
    # Streaming flush helpers — the original-bug fix
    # ------------------------------------------------------------------

    async def _maybe_flush(
        self, ctx: TurnContext, target: SlackTarget
    ) -> DeliveryReceipt:
        """Flush ``ctx.accumulated_text`` if the debounce window has elapsed.

        Otherwise queue the latest text in ``ctx.pending_text`` so the
        in-flight flush will pick it up via the safety pass.
        """
        now = time.monotonic()
        if now - ctx.last_flush_at < STREAM_FLUSH_INTERVAL:
            ctx.pending_text = ctx.accumulated_text
            return DeliveryReceipt.ok()

        if ctx.flush_lock.locked():
            # Another flush is in flight; queue and let it pick this up.
            ctx.pending_text = ctx.accumulated_text
            return DeliveryReceipt.ok()

        return await self._do_flush(ctx, target)

    async def _force_flush(
        self, event: ChannelEvent, target: SlackTarget
    ) -> None:
        payload = event.payload
        turn_id = str(getattr(payload, "turn_id", "") or "")
        ctx = slack_render_contexts.get(target.channel_id, turn_id)
        if ctx is None or not ctx.accumulated_text:
            return
        await self._do_flush(ctx, target)

    async def _do_flush(
        self, ctx: TurnContext, target: SlackTarget
    ) -> DeliveryReceipt:
        async with ctx.flush_lock:
            if ctx.thinking_ts is None or ctx.thinking_channel is None:
                # No placeholder yet — fall through to TURN_ENDED.
                return DeliveryReceipt.ok()

            text = _truncate_for_stream(ctx.accumulated_text)
            attrs = bot_attribution(ctx.bot_id) if ctx.bot_id else {}
            body: dict = {
                "channel": ctx.thinking_channel,
                "ts": ctx.thinking_ts,
                "text": text,
                **attrs,
            }
            result = await self._call_slack("chat.update", target.token, body)
            ctx.last_flush_at = time.monotonic()

            # Safety pass: if more tokens arrived during the flush,
            # fire one more update with the queued text. This is the
            # critical fix for the rapid-edit race that broke Slack
            # mobile cache refreshes.
            if (
                ctx.pending_text is not None
                and ctx.pending_text != ctx.accumulated_text
            ):
                queued = ctx.pending_text
                ctx.pending_text = None
                queued_text = _truncate_for_stream(queued)
                queued_body = {**body, "text": queued_text}
                await self._call_slack("chat.update", target.token, queued_body)
                ctx.last_flush_at = time.monotonic()
            else:
                ctx.pending_text = None

            return result.to_receipt()

    # ------------------------------------------------------------------
    # HTTP / rate-limit plumbing
    # ------------------------------------------------------------------

    async def _call_slack(
        self,
        method: str,
        token: str,
        body: dict,
    ) -> "_SlackCallResult":
        """Make a single rate-limited Slack web-API call.

        Returns a ``_SlackCallResult`` so callers can read both the
        DeliveryReceipt-equivalent state AND the raw response data
        (needed by ``_handle_turn_started`` to capture the placeholder
        ts).
        """
        await slack_rate_limiter.acquire(method)
        url = f"https://slack.com/api/{method}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await _http.post(url, json=body, headers=headers)
        except httpx.RequestError as exc:
            logger.warning("SlackRenderer: %s connection error: %s", method, exc)
            return _SlackCallResult.failed(f"connection error: {exc}", retryable=True)

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            slack_rate_limiter.record_429(method, retry_after)
            return _SlackCallResult.failed(
                f"slack 429 (Retry-After={retry_after}s)", retryable=True,
            )

        try:
            data = response.json()
        except ValueError:
            return _SlackCallResult.failed(
                f"slack {method} returned non-JSON status={response.status_code}",
                retryable=response.status_code >= 500,
            )

        if not response.is_success:
            return _SlackCallResult.failed(
                f"slack {method} HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )

        if not data.get("ok"):
            error = data.get("error", "unknown")
            # Slack-side errors that are clearly fatal — bad token,
            # missing channel — are non-retryable. Everything else
            # gets a retry.
            non_retryable = {
                "invalid_auth", "not_authed", "channel_not_found",
                "is_archived", "msg_too_long", "no_text",
            }
            retryable = error not in non_retryable
            return _SlackCallResult.failed(
                f"slack {method} error: {error}", retryable=retryable,
            )

        return _SlackCallResult.ok(data)

    async def _upload_actions(
        self,
        target: SlackTarget,
        attrs: dict,
        actions: list,
    ) -> None:
        """Upload images / files attached to a TurnEndedPayload.

        Imports lazily because the upload helper pulls in the slack
        SDK and we don't want it loaded for every chat.update flush.
        """
        try:
            from integrations.slack.uploads import upload_image
        except Exception:
            logger.exception("SlackRenderer: failed to import upload helper")
            return

        for action in actions:
            action_dict = (
                action if isinstance(action, dict) else _action_to_dict(action)
            )
            if action_dict.get("type") not in ("upload_image", "upload_file"):
                continue
            try:
                await upload_image(
                    token=target.token,
                    channel_id=target.channel_id,
                    thread_ts=target.thread_ts,
                    reply_in_thread=target.reply_in_thread,
                    action=action_dict,
                    username=attrs.get("username"),
                    icon_emoji=attrs.get("icon_emoji"),
                )
            except Exception:
                logger.exception("SlackRenderer: upload_image failed for action")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate_for_stream(text: str) -> str:
    """Mirror the legacy ``SlackStreamBuffer._build_display`` truncation."""
    text = (text or "").lstrip()
    if not text:
        return ""
    if len(text) > STREAM_MAX_CHARS - 4:
        return text[:STREAM_MAX_CHARS - 4] + " ..."
    return text + " ..."


def _action_to_dict(action) -> dict:
    """Best-effort conversion of an OutboundAction dataclass into a dict."""
    if isinstance(action, dict):
        return action
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(action) and not isinstance(action, type):
            return asdict(action)
    except Exception:
        pass
    return {}


def _build_capability_approval_blocks(
    approval_id: str, bot_id: str, cap: dict,
) -> list:
    """Block Kit layout for capability activation approvals.

    Ported from ``SlackDispatcher._build_capability_approval_blocks``.
    """
    import json as _json

    cap_name = cap.get("name", "Unknown")
    cap_desc = cap.get("description", "")
    cap_id = cap.get("id", "")
    tools_count = cap.get("tools_count", 0)
    skills_count = cap.get("skills_count", 0)

    header_lines = [f":sparkles: *Capability activation — {cap_name}*"]
    if cap_desc:
        header_lines.append(cap_desc)
    header_lines.append(
        f"Provides: {tools_count} tool"
        f"{'s' if tools_count != 1 else ''}, "
        f"{skills_count} skill{'s' if skills_count != 1 else ''}"
    )
    header_lines.append(f"Bot: `{bot_id}`")

    primary_actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Allow"},
            "action_id": "approve_tool_call",
            "value": approval_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Allow & Pin"},
            "style": "primary",
            "action_id": "pin_capability",
            "value": _json.dumps({
                "approval_id": approval_id,
                "capability_id": cap_id,
                "capability_name": cap_name,
            }),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Deny"},
            "style": "danger",
            "action_id": "deny_tool_call",
            "value": approval_id,
        },
    ]

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(header_lines)},
        },
        {"type": "actions", "elements": primary_actions},
    ]


def _build_tool_approval_blocks(
    approval_id: str,
    bot_id: str,
    tool_name: str,
    arguments: dict,
    reason: str | None,
) -> list:
    """Block Kit layout for regular tool approvals.

    Ported from ``SlackDispatcher._build_tool_approval_blocks``.
    """
    import json as _json

    args_preview = _json.dumps(arguments, indent=2)[:500]

    from app.services.approval_suggestions import build_suggestions
    suggestions = build_suggestions(tool_name, arguments)

    primary_actions = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"Allow {tool_name}"},
            "style": "primary",
            "action_id": "allow_rule_always",
            "value": _json.dumps({
                "approval_id": approval_id,
                "bot_id": bot_id,
                "tool_name": tool_name,
                "conditions": {},
                "scope": "bot",
                "label": f"Allow {tool_name} always",
            }),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Approve this run"},
            "action_id": "approve_tool_call",
            "value": approval_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Deny"},
            "style": "danger",
            "action_id": "deny_tool_call",
            "value": approval_id,
        },
    ]

    suggestion_actions: list = []
    if suggestions and suggestions[0].scope == "global":
        sug = suggestions[0]
        suggestion_actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": sug.label[:75]},
            "action_id": "allow_rule_0",
            "value": _json.dumps({
                "approval_id": approval_id,
                "bot_id": bot_id,
                "tool_name": sug.tool_name,
                "conditions": sug.conditions,
                "scope": sug.scope,
                "label": sug.label,
            }),
        })
    narrow_start = next(
        (i for i, s in enumerate(suggestions) if s.conditions),
        len(suggestions),
    )
    for i, sug in enumerate(suggestions[narrow_start:narrow_start + 4]):
        if len(suggestion_actions) >= 5:
            break
        suggestion_actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": sug.label[:75]},
            "action_id": f"allow_rule_{narrow_start + i}",
            "value": _json.dumps({
                "approval_id": approval_id,
                "bot_id": bot_id,
                "tool_name": sug.tool_name,
                "conditions": sug.conditions,
                "scope": getattr(sug, "scope", "bot"),
                "label": sug.label,
            }),
        })

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":lock: *Tool approval required*\n"
                    f"*Bot:* `{bot_id}` | *Tool:* `{tool_name}`\n"
                    f"*Reason:* {reason or 'Policy requires approval'}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```\n{args_preview}\n```"},
        },
        {"type": "actions", "elements": primary_actions},
    ]
    if suggestion_actions:
        blocks.append({"type": "actions", "elements": suggestion_actions})
    return blocks


# ---------------------------------------------------------------------------
# Component vocabulary → Slack Block Kit conversion
# ---------------------------------------------------------------------------

# Semantic color slot → emoji prefix for Slack (no color in mrkdwn text).
_SLOT_EMOJI = {
    "success": ":large_green_circle:",
    "warning": ":large_yellow_circle:",
    "danger": ":red_circle:",
    "info": ":large_purple_circle:",
    "accent": ":large_blue_circle:",
}

_LINK_EMOJI = {
    "github": ":github:",
    "web": ":globe_with_meridians:",
    "email": ":email:",
    "file": ":page_facing_up:",
}


async def _resolve_tool_output_display(slack_channel_id: str) -> str:
    """Look up the channel's ``tool_output_display`` setting.

    Queries the ``channels`` table directly (keeps the renderer in-process
    and avoids the HTTP-self-call path that ``slack_settings`` uses for
    the out-of-process bot subprocess). Falls back to ``compact`` when the
    channel can't be resolved.
    """
    from app.db.engine import async_session
    from app.db.models import Channel, ChannelIntegration
    from sqlalchemy import select

    client_id = f"slack:{slack_channel_id}"
    try:
        async with async_session() as db:
            # Legacy direct binding on Channel.client_id.
            row = (await db.execute(
                select(Channel.tool_output_display).where(
                    Channel.integration == "slack",
                    Channel.client_id == client_id,
                )
            )).scalar_one_or_none()
            if row is not None:
                return ToolOutputDisplay.normalize(row)
            # Modern ChannelIntegration binding.
            row = (await db.execute(
                select(Channel.tool_output_display)
                .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
                .where(
                    ChannelIntegration.integration_type == "slack",
                    ChannelIntegration.client_id == client_id,
                )
            )).scalar_one_or_none()
            if row is not None:
                return ToolOutputDisplay.normalize(row)
    except Exception:
        logger.debug("tool_output_display lookup failed, using default", exc_info=True)
    return ToolOutputDisplay.COMPACT


def _badges_to_context_block(badges: list[ToolBadge]) -> dict | None:
    """Render a list of ``ToolBadge`` into a single Slack context block.

    Each badge becomes one mrkdwn element ``:wrench: *<tool>* — <label>``.
    Returns None when the badge list is empty. Slack caps context
    elements at 10 per block — if a turn somehow fired more tools, the
    overflow is silently dropped (these are compact hints, not the
    canonical record — the web UI still shows everything).
    """
    if not badges:
        return None
    elements = []
    for badge in badges[:10]:
        name = _escape_mrkdwn(badge.tool_name) or "tool"
        text = f":wrench:  *{name}*"
        if badge.display_label:
            text += f"  —  {_escape_mrkdwn(badge.display_label)}"
        elements.append({"type": "mrkdwn", "text": text})
    return {"type": "context", "elements": elements}


def _components_to_blocks(envelopes: list[dict]) -> list[dict]:
    """Convert component-vocabulary envelopes to Slack Block Kit blocks.

    Only processes envelopes with content_type
    ``application/vnd.spindrel.components+json``. Other types are skipped
    (the text content is already in the main message body).
    """
    import json as _json

    blocks: list[dict] = []
    for env in envelopes:
        ct = env.get("content_type", "")
        if ct != "application/vnd.spindrel.components+json":
            continue
        body_raw = env.get("body")
        if not body_raw:
            continue
        try:
            parsed = _json.loads(body_raw) if isinstance(body_raw, str) else body_raw
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict) or parsed.get("v") != 1:
            continue
        components = parsed.get("components", [])
        for node in components:
            result = _node_to_block(node)
            if isinstance(result, list):
                blocks.extend(result)
            elif result:
                blocks.append(result)
    return blocks


def _node_to_block(node: dict) -> dict | None:
    """Map a single component node to a Slack block."""
    ntype = node.get("type")

    if ntype == "heading":
        text = node.get("text", "")
        level = node.get("level", 2)
        if level == 1:
            return {"type": "header", "text": {"type": "plain_text", "text": text[:150]}}
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{_escape_mrkdwn(text)}*"},
        }

    if ntype == "text":
        content = node.get("content", "")
        style = node.get("style", "default")
        if node.get("markdown"):
            return {
                "type": "section",
                "text": {"type": "mrkdwn", "text": markdown_to_slack_mrkdwn(content)},
            }
        if style == "code":
            return {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"`{_escape_mrkdwn(content)}`"},
            }
        if style == "bold":
            return {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{_escape_mrkdwn(content)}*"},
            }
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _escape_mrkdwn(content)},
        }

    if ntype == "properties":
        items = node.get("items", [])
        # Use Slack's fields layout (2-column grid, max 10 fields)
        fields = []
        for item in items[:10]:
            label = _escape_mrkdwn(item.get("label", ""))
            value = _escape_mrkdwn(item.get("value", ""))
            color = item.get("color")
            emoji = _SLOT_EMOJI.get(color, "")
            prefix = f"{emoji} " if emoji else ""
            fields.append({
                "type": "mrkdwn",
                "text": f"*{label}*\n{prefix}{value}",
            })
        if fields:
            return {"type": "section", "fields": fields}
        return None

    if ntype == "table":
        columns = node.get("columns", [])
        rows = node.get("rows", [])
        if not columns or not rows:
            return None
        # Slack has no native table — render as a code block
        # Compute column widths
        widths = [len(c) for c in columns]
        for row in rows[:20]:  # cap to avoid huge blocks
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(str(cell)))
        header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
        sep = "-+-".join("-" * w for w in widths)
        lines = [header, sep]
        for row in rows[:20]:
            line = " | ".join(
                str(row[i] if i < len(row) else "").ljust(widths[i])
                for i in range(len(columns))
            )
            lines.append(line)
        if len(rows) > 20:
            lines.append(f"... ({len(rows) - 20} more rows)")
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```\n{chr(10).join(lines)}\n```"},
        }

    if ntype == "links":
        items = node.get("items", [])
        lines = []
        for item in items[:10]:
            url = item.get("url", "")
            title = _escape_mrkdwn(item.get("title", url))
            subtitle = item.get("subtitle", "")
            icon = item.get("icon", "link")
            emoji = _LINK_EMOJI.get(icon, ":link:")
            line = f"{emoji} <{url}|{title}>"
            if subtitle:
                line += f"\n    {_escape_mrkdwn(subtitle[:120])}"
            lines.append(line)
        if lines:
            return {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)},
            }
        return None

    if ntype == "code":
        content = node.get("content", "")
        lang = node.get("language", "")
        label = f"_{lang}_\n" if lang else ""
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{label}```\n{content[:2900]}\n```"},
        }

    if ntype == "image":
        url = node.get("url", "")
        alt = node.get("alt", "image")
        if url:
            return {
                "type": "image",
                "image_url": url,
                "alt_text": alt or "image",
            }
        return None

    if ntype == "status":
        text = node.get("text", "")
        color = node.get("color", "default")
        emoji = _SLOT_EMOJI.get(color, "")
        prefix = f"{emoji} " if emoji else ""
        return {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"{prefix}*{_escape_mrkdwn(text)}*"}],
        }

    if ntype == "divider":
        return {"type": "divider"}

    if ntype == "section":
        # Flatten children into blocks (Slack has no nested sections)
        children = node.get("children", [])
        label = node.get("label")
        child_blocks: list[dict] = []
        if label:
            child_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*{_escape_mrkdwn(label)}*"}],
            })
        for child in children:
            result = _node_to_block(child)
            if isinstance(result, list):
                child_blocks.extend(result)
            elif result:
                child_blocks.append(result)
        return child_blocks

    return None


def _escape_mrkdwn(text: str) -> str:
    """Escape Slack mrkdwn special characters in user-provided text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Internal Slack call result type
# ---------------------------------------------------------------------------


class _SlackCallResult:
    """Carrier object for ``_call_slack``: success/failure + raw data."""

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
    def ok(cls, data: dict) -> "_SlackCallResult":
        return cls(True, data=data)

    @classmethod
    def failed(cls, error: str, *, retryable: bool) -> "_SlackCallResult":
        return cls(False, error=error, retryable=retryable)

    def to_receipt(self) -> DeliveryReceipt:
        if self.success:
            return DeliveryReceipt.ok(
                external_id=(self.data or {}).get("ts") if self.data else None,
            )
        return DeliveryReceipt.failed(self.error or "unknown", retryable=self.retryable)


# ---------------------------------------------------------------------------
# Self-registration — same idempotent pattern as core_renderers.py
# ---------------------------------------------------------------------------


def _register() -> None:
    from app.integrations import renderer_registry
    if renderer_registry.get(SlackRenderer.integration_id) is None:
        renderer_registry.register(SlackRenderer())


_register()
