"""Pydantic request/response models for chat endpoints."""
import uuid
from typing import Optional

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    """Multimedia attachment (vision). Slack sends type=image with base64 content."""
    type: str = "image"
    content: str  # base64-encoded bytes
    mime_type: str = "image/jpeg"
    name: str = ""


class FileMetadata(BaseModel):
    """Metadata about an attached file for server-side attachment tracking."""
    url: str | None = None
    filename: str = "attachment"
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0
    posted_by: str | None = None
    file_data: str | None = None  # base64-encoded file bytes


class ChatRequest(BaseModel):
    message: str = ""
    channel_id: Optional[uuid.UUID] = None  # Preferred for channel targeting
    session_id: Optional[uuid.UUID] = None  # backward compat; resolves to channel
    client_id: str = "default"
    bot_id: str = "default"
    audio_data: Optional[str] = None  # base64-encoded audio
    audio_format: Optional[str] = None  # e.g. "m4a", "wav", "webm"
    audio_native: Optional[bool] = None  # True/False overrides bot default; None = use bot setting
    attachments: list[Attachment] = Field(default_factory=list)
    file_metadata: list[FileMetadata] = Field(default_factory=list)  # server-side attachment tracking
    dispatch_type: Optional[str] = None  # "slack" | "webhook" | "internal" | "none"
    dispatch_config: Optional[dict] = None  # type-specific routing config
    model_override: Optional[str] = None  # Per-turn model override (highest priority)
    model_provider_id_override: Optional[str] = None  # Per-turn provider override (paired with model_override)
    passive: bool = False  # If True, store message but skip agent run
    msg_metadata: Optional[dict] = None  # Metadata to attach to the user message row


class CancelRequest(BaseModel):
    client_id: str
    bot_id: str


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
