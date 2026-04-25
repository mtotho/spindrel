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

import logging
from typing import ClassVar

from integrations.sdk import (
    Capability, ChannelEvent, ChannelEventKind,
    DispatchTarget, OutboundAction, DeliveryReceipt,
    ToolBadge, ToolResultRenderingSupport,
    renderer_registry,
)
from integrations.slack.approval_delivery import SlackApprovalDelivery
from integrations.slack.client import bot_attribution
from integrations.slack.ephemeral_delivery import SlackEphemeralDelivery
from integrations.slack.formatting import markdown_to_slack_mrkdwn
from integrations.slack.message_delivery import SlackMessageDelivery
from integrations.slack.streaming import STREAMING_KINDS, SlackStreamingDelivery
from integrations.slack.target import SlackTarget
from integrations.slack.tool_result_adapter import badges_to_context_block
from integrations.slack.transport import call_slack

logger = logging.getLogger(__name__)


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
        Capability.RICH_TOOL_RESULTS,
        Capability.APPROVAL_BUTTONS,
        Capability.DISPLAY_NAMES,
        Capability.MENTIONS,
        Capability.EPHEMERAL,
        Capability.MODALS,
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
                "max_blocks": 50,
                "max_table_rows": 20,
                "max_links": 10,
                "max_code_chars": 2900,
            },
        })
    )

    def __init__(self) -> None:
        self._streaming = SlackStreamingDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
        )
        self._messages = SlackMessageDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
            tool_result_rendering=self.tool_result_rendering,
        )
        self._approvals = SlackApprovalDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
        )
        self._ephemeral = SlackEphemeralDelivery(
            call_slack=call_slack,
            bot_attribution=bot_attribution,
        )

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
            if kind in STREAMING_KINDS:
                return await self._streaming.render(event, target)
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._messages.render(event, target)
            if kind == ChannelEventKind.MESSAGE_UPDATED:
                return await self._handle_message_updated(event, target)
            if kind == ChannelEventKind.APPROVAL_REQUESTED:
                return await self._approvals.render(event, target)
            if kind == ChannelEventKind.EPHEMERAL_MESSAGE:
                return await self._ephemeral.render(event, target)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _badges_to_context_block(badges: list[ToolBadge]) -> dict | None:
    """Render a list of ``ToolBadge`` into a single Slack context block.

    Each badge becomes one mrkdwn element ``:wrench: *<tool>* — <label>``.
    Returns None when the badge list is empty. Slack caps context
    elements at 10 per block — if a turn somehow fired more tools, the
    overflow is silently dropped (these are compact hints, not the
    canonical record — the web UI still shows everything).
    """
    return badges_to_context_block(badges)


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
# Self-registration — same idempotent pattern as core_renderers.py
# ---------------------------------------------------------------------------


def _register() -> None:
    if renderer_registry.get(SlackRenderer.integration_id) is None:
        renderer_registry.register(SlackRenderer())


_register()
