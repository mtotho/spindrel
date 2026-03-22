"""Layer 4 — Typed envelope models for the ingestion pipeline."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class RawMessage(BaseModel):
    """Inbound message before any processing."""

    source: str  # "gmail", "webhook", etc.
    source_id: str  # dedupe key
    raw_content: str
    metadata: dict = Field(default_factory=dict)


class RiskMetadata(BaseModel):
    """Security assessment attached to every processed message."""

    layer2_flags: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"]
    classifier_reason: str


class ExternalMessage(BaseModel):
    """Sanitized message ready for delivery to the agent."""

    source: str
    source_id: str
    body: str  # sanitized plain text
    metadata: dict = Field(default_factory=dict)
    risk: RiskMetadata
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
