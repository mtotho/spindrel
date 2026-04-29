"""Compatibility adapter for chat schema imports.

Canonical chat request/response models live in ``app.schemas.chat``.
"""
from app.schemas.chat import (  # noqa: F401
    Attachment,
    CancelRequest,
    CancelResponse,
    ChatRequest,
    ChatResponse,
    FileMetadata,
    IngestMessageMetadata,
    SecretCheckRequest,
    SecretCheckResponse,
    ToolResultRequest,
)
