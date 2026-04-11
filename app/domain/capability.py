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

    THREADING = "threading"
    """Slack-style threaded replies. (Currently unused — see ActorRef and
    Slack-thread-vs-channel discussion in vault Track.)"""

    REACTIONS = "reactions"
    """Emoji reactions on messages."""

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
