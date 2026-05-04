"""Capability — what an integration's renderer can render.

Each ChannelRenderer declares a `frozenset[Capability]` of features it
supports. The outbox drainer (Phase D) checks the event's required
capabilities against the renderer's declared capabilities and silently
skips events the renderer cannot handle (marking them DELIVERED with a
skip reason). This is how a text-only integration like BlueBubbles can
gracefully ignore `turn_stream_token` events without anyone in `app/`
knowing about it.
"""
from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    """A feature an integration can or cannot render."""

    TEXT = "text"
    """Plain text messages."""

    RICH_TEXT = "rich_text"
    """Markdown/mrkdwn/Block Kit / embeds — formatted text."""

    RICH_TOOL_RESULTS = "rich_tool_results"
    """The renderer can turn structured tool-result envelopes into native,
    read-only platform presentation. This is advisory for NEW_MESSAGE
    delivery; text fallback remains the durable baseline."""

    THREADING = "threading"
    """Slack-style threaded replies. (Currently unused — see ActorRef and
    Slack-thread-vs-channel discussion in vault Track.)"""

    REACTIONS = "reactions"
    """Emoji reactions on messages."""

    MESSAGE_FEEDBACK = "message_feedback"
    """The renderer can map external user reactions to Spindrel turn-feedback
    votes. Slack maps :+1: / :-1: on bot messages to up/down votes. Other
    integrations opt in by mapping their native reaction surface to the
    canonical vote enum (`"up"` / `"down"`)."""

    INLINE_BUTTONS = "inline_buttons"
    """Block Kit-style interactive buttons attached to messages."""

    ATTACHMENTS = "attachments"
    """File / image attachments referenced by Message.attachments."""

    IMAGE_UPLOAD = "image_upload"
    """The renderer can upload images created by the agent (UploadImage action)."""

    FILE_UPLOAD = "file_upload"
    """The renderer can upload arbitrary files (UploadFile action)."""

    FILE_DELETE = "file_delete"
    """The renderer can delete previously uploaded files."""

    STREAMING_EDIT = "streaming_edit"
    """The renderer can edit a message in place as the agent streams tokens.
    Slack/Discord support this (chat.update); BlueBubbles/iMessage do not."""

    TYPING_INDICATOR = "typing_indicator"
    """Show a 'typing…' indicator while the agent is working."""

    DISPLAY_NAMES = "display_names"
    """The renderer can override the display name on a per-message basis
    (Slack username override, BB sender attribution, etc.)."""

    APPROVAL_BUTTONS = "approval_buttons"
    """The renderer can render Approve/Deny buttons for tool approval gates."""

    MENTIONS = "mentions"
    """The renderer can convert @-mentions to platform-native mentions."""

    CANCELLATION = "cancellation"
    """The renderer surfaces a Cancel/STOP affordance to the user."""

    EPHEMERAL = "ephemeral"
    """The renderer can deliver a message visible only to one recipient
    (Slack chat.postEphemeral, Discord interaction flag=64). Integrations
    without this capability receive an ``EPHEMERAL_MESSAGE`` event as a
    regular ``NEW_MESSAGE`` with a leading visibility marker."""

    MODALS = "modals"
    """The renderer can open a modal/form UI and deliver the user's
    structured submission back to the agent via ``MODAL_SUBMITTED``.
    Slack: ``views.open`` + Block Kit modal; Discord: modal with inputs
    (requires originating interaction). Integrations without this
    capability fall back to a conversational Q&A loop in the
    ``open_modal`` tool."""
