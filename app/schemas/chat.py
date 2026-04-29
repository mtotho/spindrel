"""Pydantic request/response models for chat endpoints."""
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    """Multimedia attachment (vision). Slack sends type=image with base64 content."""
    type: str = "image"
    content: str  # base64-encoded bytes
    mime_type: str = "image/jpeg"
    name: str = ""


class IngestMessageMetadata(BaseModel):
    """Canonical shape for the ``msg_metadata`` blob on an inbound user message.

    This is the contract every integration follows. ``Message.content`` stores
    the raw text the human typed — no prefixes, no thread summaries, no
    platform tokens. All routing, identity, and platform-native data lives
    here. See ``docs/integrations/message-ingest-contract.md`` for the full
    rule and a worked Slack example.

    Integrations may include extra keys beyond these (forward-compat); only
    the fields declared below are validated.
    """

    model_config = ConfigDict(extra="allow")

    source: str = Field(
        ...,
        description="Integration identifier: 'slack', 'discord', 'bluebubbles', 'web', ...",
    )
    sender_id: str = Field(
        ...,
        description="Namespaced external ID, e.g. 'slack:U06STGBF4Q0', 'discord:123', 'bb:+15551234567'.",
    )
    sender_display_name: str = Field(
        ...,
        description="Human-readable name used by the UI and the LLM attribution prefix.",
    )
    sender_type: Literal["human", "bot"] = Field(
        ...,
        description="Whether the sender is a person or another bot (for cross-bot relay).",
    )
    channel_external_id: Optional[str] = Field(
        default=None,
        description="Platform-native channel/chat identifier (Slack 'C…', Discord channel ID, BB chat GUID).",
    )
    mention_token: Optional[str] = Field(
        default=None,
        description=(
            "Platform-native token the agent must echo back verbatim to tag this "
            "user in a reply (e.g. Slack '<@U06STGBF4Q0>', Discord '<@123>'). "
            "None for platforms that resolve mentions by display name or have no "
            "mention concept (iMessage, email, web)."
        ),
    )
    thread_context: Optional[str] = Field(
        default=None,
        description=(
            "Multi-line LLM-ready summary of prior messages in this thread. "
            "Injected by the assembly layer as a system message adjacent to "
            "the user turn; never concatenated into content."
        ),
    )
    is_from_me: Optional[bool] = Field(
        default=None,
        description="BlueBubbles: true when the message came from the local user's own handle.",
    )
    passive: Optional[bool] = Field(
        default=None,
        description="Store-only; skip the agent run.",
    )
    trigger_rag: Optional[bool] = Field(
        default=None,
        description="Whether retrieval should consider this turn.",
    )
    recipient_id: Optional[str] = Field(
        default=None,
        description="Namespaced identifier of the intended recipient (e.g. 'bot:calc-bot').",
    )


class FileMetadata(BaseModel):
    """Metadata about an attached file for server-side attachment tracking."""
    url: str | None = None
    filename: str = "attachment"
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    posted_by: str | None = None
    file_data: str | None = None  # base64-encoded file bytes


class ChatRequest(BaseModel):
    message: str = Field(
        default="",
        description=(
            "The raw user-authored text. Integrations MUST pass it verbatim — no "
            "prefixes like '[Slack channel:... user:...]', no thread summaries, no "
            "'[Name]:' attribution. LLM context that depends on the integration "
            "goes in ``msg_metadata`` (see ``IngestMessageMetadata``); the assembly "
            "layer turns metadata into LLM-facing prefixes + system blocks."
        ),
    )
    channel_id: Optional[uuid.UUID] = None  # Preferred for channel targeting
    session_id: Optional[uuid.UUID] = None  # backward compat; resolves to channel
    client_id: str = "default"
    bot_id: str = "default"
    audio_data: Optional[str] = None  # base64-encoded audio
    audio_format: Optional[str] = None  # e.g. "m4a", "wav", "webm"
    audio_native: Optional[bool] = None  # True/False overrides VOICE_INPUT_MODE for this request
    attachments: list[Attachment] = Field(default_factory=list)
    file_metadata: list[FileMetadata] = Field(default_factory=list)  # server-side attachment tracking
    dispatch_type: Optional[str] = None  # "slack" | "webhook" | "internal" | "none"
    dispatch_config: Optional[dict] = None  # type-specific routing config
    model_override: Optional[str] = None  # Per-turn model override (highest priority)
    model_provider_id_override: Optional[str] = None  # Per-turn provider override (paired with model_override)
    external_delivery: Literal["channel", "none"] = Field(
        default="channel",
        description=(
            "Controls integration fanout for explicit channel-session sends. "
            "'channel' is the normal primary-session behavior; 'none' keeps "
            "the turn web-only for split/secondary sessions."
        ),
    )
    passive: bool = False  # If True, store message but skip agent run
    msg_metadata: Optional[dict] = Field(
        default=None,
        description=(
            "Metadata attached to the user message row. For integration-sourced "
            "messages, should conform to ``IngestMessageMetadata`` — "
            "source/sender_id/sender_display_name/sender_type required; "
            "mention_token, channel_external_id, thread_context optional."
        ),
    )


class CancelRequest(BaseModel):
    client_id: str
    bot_id: str
    session_id: Optional[uuid.UUID] = None
    channel_id: Optional[uuid.UUID] = None


class CancelResponse(BaseModel):
    cancelled: bool
    queued_tasks_cancelled: int = 0


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    response: str
    transcript: str = ""
    client_actions: list[dict] = []


class SecretCheckRequest(BaseModel):
    message: str


class SecretCheckResponse(BaseModel):
    has_secrets: bool
    exact_matches: int = 0
    pattern_matches: list[dict] = Field(default_factory=list)


class ToolResultRequest(BaseModel):
    request_id: str
    result: str
