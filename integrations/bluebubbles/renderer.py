"""BlueBubblesRenderer — iMessage delivery via BlueBubbles.

Non-streaming renderer: ``NEW_MESSAGE`` (outbox-durable) is the **only**
text delivery path. ``TURN_ENDED`` is a no-op because iMessage has no
edit/update API — there's no streaming placeholder to finalize.

See ``docs/integrations/design.md`` §Delivery Contract for background.

iMessage specifics:

- No ``STREAMING_EDIT`` — no ``message.update`` equivalent.
- No interactive buttons — ``APPROVAL_REQUESTED`` is delivered as
  plain text; the user approves via the web UI.
- No edit/delete API — ``ATTACHMENT_DELETED`` is a no-op.

Echo-tracker wiring is load-bearing: ``track_sent`` + ``save_to_db``
MUST run BEFORE the network send so an inbound webhook arriving while
the bot's reply is still in flight doesn't see our reply as a human
input. ``EchoTracker.is_own_content`` (the primary defense in
``router.py``'s inbound path) reads from the same ``_sent_content``
dict that ``track_sent`` populates.

Self-registers via ``_register()`` at module import time.
"""
from __future__ import annotations

import logging
import uuid
from typing import ClassVar

import httpx

from integrations.sdk import (
    Capability, ChannelEvent, ChannelEventKind,
    DispatchTarget, OutboundAction, DeliveryReceipt,
    UploadFile, UploadImage,
    renderer_registry,
)
from integrations.bluebubbles.bb_api import send_attachment, send_text, set_typing
from integrations.bluebubbles.echo_tracker import shared_tracker
from integrations.bluebubbles.target import BlueBubblesTarget

logger = logging.getLogger(__name__)


# Max iMessage text length per bubble. Apple doesn't hard-enforce this
# but very long messages get split client-side; 20k is a safe single
# bubble. Same value as the legacy dispatcher.
_MAX_MSG_LEN = 20000


# Module-level shared httpx client. Created at import time; the renderer
# never closes it explicitly because it lives for the process lifetime.
_http = httpx.AsyncClient(timeout=90.0)


def _split_text(text: str, max_len: int = _MAX_MSG_LEN) -> list[str]:
    """Split text into chunks that fit in a single iMessage bubble.

    Ported verbatim from the legacy dispatcher. Prefers a newline split
    near the boundary so chunks break cleanly on paragraph edges.
    """
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def _bb_send(
    target: BlueBubblesTarget, text: str,
) -> bool:
    """Send a single chunk via the BB API with echo-tracking.

    The ``track_sent`` + ``save_to_db`` calls MUST happen BEFORE the
    network send. If they happened after, an inbound webhook arriving
    while we're mid-send would see the bot's reply as a human input
    and re-trigger the agent — the exact echo loop the tracker exists
    to prevent.
    """
    temp_guid = str(uuid.uuid4())
    shared_tracker.track_sent(temp_guid, text, chat_guid=target.chat_guid)
    # Persist immediately so a process crash between this point and the
    # send doesn't lose the suppression record.
    await shared_tracker.save_to_db()

    result = await send_text(
        _http, target.server_url, target.password,
        target.chat_guid, text,
        temp_guid=temp_guid,
        method=target.send_method,
    )
    return result is not None


def _apply_footer(text: str, target: BlueBubblesTarget) -> str:
    """Append the per-target text footer if configured.

    Footer is applied BEFORE chunking so it appears on every chunk —
    matches the legacy dispatcher's behavior. The footer is a per-binding
    setting (e.g. ``-- via Spindrel``) and users expect it on every
    bubble.
    """
    if target.text_footer:
        return f"{text}\n{target.text_footer}"
    return text


class BlueBubblesRenderer:
    """Channel renderer for BlueBubbles / iMessage delivery.

    Non-streaming: ``NEW_MESSAGE`` is the sole text delivery path.
    ``TURN_ENDED`` is skipped (no placeholder to finalize). See the
    delivery contract in ``docs/integrations/design.md``.
    """

    integration_id: ClassVar[str] = "bluebubbles"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.TEXT,
        Capability.ATTACHMENTS,
        Capability.APPROVAL_BUTTONS,  # text-only approval — see _handle_approval_requested
        Capability.DISPLAY_NAMES,
        Capability.MENTIONS,
    })
    # Notably absent:
    # - STREAMING_EDIT: iMessage has no ``message.update`` equivalent
    # - RICH_TEXT / INLINE_BUTTONS: no interactive components in iMessage
    # - IMAGE_UPLOAD / FILE_UPLOAD: handled via send_attachment but not
    #   wired to the renderer event flow yet (Phase H/I follow-up)
    # - FILE_DELETE / REACTIONS: no API surface

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, BlueBubblesTarget):
            return DeliveryReceipt.failed(
                f"BlueBubblesRenderer received non-bluebubbles target: "
                f"{type(target).__name__}",
                retryable=False,
            )

        kind = event.kind
        try:
            if kind == ChannelEventKind.TURN_STARTED:
                return await self._handle_turn_started(event, target)
            if kind == ChannelEventKind.TURN_ENDED:
                return await self._handle_turn_ended(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._handle_new_message(event, target)
            if kind == ChannelEventKind.APPROVAL_REQUESTED:
                return await self._handle_approval_requested(event, target)
        except Exception as exc:
            logger.exception(
                "BlueBubblesRenderer.render: unexpected failure for %s",
                kind.value,
            )
            return DeliveryReceipt.failed(f"unexpected: {exc}", retryable=True)

        # TURN_STREAM_*, ATTACHMENT_DELETED, MESSAGE_UPDATED
        # silently skip — iMessage can't render any of them.
        return DeliveryReceipt.skipped(
            f"bluebubbles does not handle {kind.value}"
        )

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, BlueBubblesTarget):
            return DeliveryReceipt.skipped("not a bluebubbles target")

        if isinstance(action, UploadImage):
            return await self._handle_upload(action, target)
        if isinstance(action, UploadFile):
            return await self._handle_upload(action, target)

        return DeliveryReceipt.skipped(
            f"bluebubbles does not handle outbound action {action.type}"
        )

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        # iMessage exposes no server-side delete-attachment API. The
        # legacy dispatcher returned False here too.
        return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_turn_started(
        self, event: ChannelEvent, target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        """Send a typing indicator when the agent begins processing.

        Shows the "..." typing bubble in iMessage. The indicator
        auto-expires after ~10s and is implicitly cleared when the
        bot's actual reply is sent. Fire-and-forget — failures are
        silently swallowed since this is a cosmetic UX enhancement.

        Controlled by the per-binding ``typing_indicator`` config
        (default: enabled).
        """
        if not target.typing_indicator:
            return DeliveryReceipt.skipped("typing indicator disabled for this binding")
        await set_typing(_http, target.server_url, target.password, target.chat_guid)
        return DeliveryReceipt.skipped("typing indicator sent (fire-and-forget)")

    async def _handle_turn_ended(
        self, event: ChannelEvent, target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        """No-op — iMessage has no streaming placeholder to finalize.

        Response delivery is ``NEW_MESSAGE``'s responsibility (the
        outbox-durable path). Posting text here would duplicate every
        response because iMessage has no edit/update API to make it
        idempotent. See ``docs/integrations/design.md`` §Anti-pattern.
        """
        return DeliveryReceipt.skipped(
            "non-streaming renderer — delivery via NEW_MESSAGE"
        )

    async def _handle_new_message(
        self, event: ChannelEvent, target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        """Deliver a message to the iMessage chat (the durable path).

        This is the **sole** text delivery path for BB. All assistant
        responses arrive here via the outbox drainer after
        ``persist_turn`` enqueues them. Delegation fanout and cross-
        integration mirrors also use this path.
        """
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(f"bb skips internal role={role}")

        # Echo prevention — BB-origin user messages reach the outbox via
        # turn_worker's _persist_and_publish_user_message. Without this
        # guard every inbound iMessage is re-sent as a bot reply.
        if role == "user":
            msg_metadata = getattr(msg, "metadata", None) or {}
            if msg_metadata.get("source") == "bluebubbles":
                return DeliveryReceipt.skipped(
                    "bb skips own-origin user message (echo prevention)"
                )

        text = (getattr(msg, "content", "") or "").strip()
        if not text:
            return DeliveryReceipt.skipped("new_message with empty content")

        text = _apply_footer(text, target)
        for chunk in _split_text(text):
            if not await _bb_send(target, chunk):
                return DeliveryReceipt.failed(
                    f"BB send_text failed for chat {target.chat_guid}",
                    retryable=True,
                )
        return DeliveryReceipt.ok()

    async def _handle_approval_requested(
        self, event: ChannelEvent, target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        """Send a text-based approval request.

        iMessage has no interactive buttons, so we render the approval
        as a plain-text description with the approval id and a pointer
        to the web UI. Ported from the legacy dispatcher's
        ``request_approval``.
        """
        import json as _json

        payload = event.payload
        approval_id = getattr(payload, "approval_id", "") or ""
        bot_id = getattr(payload, "bot_id", "") or ""
        tool_name = getattr(payload, "tool_name", "") or ""
        arguments = getattr(payload, "arguments", {}) or {}
        reason = getattr(payload, "reason", None)

        args_preview = _json.dumps(arguments, indent=2)[:500]
        text = (
            f"Tool approval required\n"
            f"Bot: {bot_id} | Tool: {tool_name}\n"
            f"Reason: {reason or 'Policy requires approval'}\n"
            f"Args: {args_preview}\n\n"
            f"Approve via the web UI (approval ID: {approval_id})"
        )
        text = _apply_footer(text, target)
        if not await _bb_send(target, text):
            return DeliveryReceipt.failed(
                f"BB approval send failed for chat {target.chat_guid}",
                retryable=True,
            )
        return DeliveryReceipt.ok()


    async def _handle_upload(
        self,
        action: UploadImage | UploadFile,
        target: BlueBubblesTarget,
    ) -> DeliveryReceipt:
        """Send an image or file attachment via the BB API.

        Decodes the base64 payload to a temp file and sends via
        ``send_attachment``. The echo tracker is NOT wired here
        because attachments don't echo back as text content.
        """
        import base64
        import os
        import tempfile

        data_b64 = getattr(action, "image_data_b64", None) or getattr(action, "file_data_b64", "")
        if not data_b64:
            return DeliveryReceipt.skipped("upload action with no data")

        filename = action.filename
        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return DeliveryReceipt.failed("invalid base64 data", retryable=False)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
                tmp.write(raw)
                tmp_path = tmp.name

            result = await send_attachment(
                _http, target.server_url, target.password,
                target.chat_guid, tmp_path, filename,
            )
            if result:
                # If there's a description, send it as a follow-up text
                desc = getattr(action, "description", None)
                if desc:
                    await _bb_send(target, desc)
                return DeliveryReceipt.ok()
            return DeliveryReceipt.failed(
                f"BB send_attachment failed for chat {target.chat_guid}",
                retryable=True,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Self-registration — same idempotent pattern as the Slack/Discord renderers
# ---------------------------------------------------------------------------


def _register() -> None:
    if renderer_registry.get(BlueBubblesRenderer.integration_id) is None:
        renderer_registry.register(BlueBubblesRenderer())


_register()
