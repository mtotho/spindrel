"""ContentFeed — base class for content source connectors.

Subclasses implement fetch_items() to pull raw content from a source
(IMAP, RSS, webhooks, etc.) and optionally format_item() to convert
pipeline-processed envelopes into delivery-ready FeedItems.

run_cycle() handles the full fetch → pipeline → format loop with
per-item error isolation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field as PydanticField

from integrations.ingestion.envelope import ExternalMessage, RawMessage
from integrations.ingestion.pipeline import IngestionPipeline
from integrations.ingestion.store import IngestionStore

logger = logging.getLogger(__name__)


class FeedItem(BaseModel):
    """Delivery-ready content item produced by a feed."""

    title: str
    body: str  # markdown
    source_id: str
    metadata: dict = PydanticField(default_factory=dict)
    suggested_path: str = ""  # e.g. "data/gmail/2026-03-30-meeting-notes.md"
    risk_level: Literal["low", "medium", "high"] = "low"


@dataclass
class CycleResult:
    """Summary of a single feed poll cycle."""

    fetched: int = 0
    passed: int = 0
    quarantined: int = 0
    skipped: int = 0  # duplicates
    items: list[FeedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ContentFeed(ABC):
    """Abstract base for content source connectors.

    Subclasses must implement:
        fetch_items() -> list[RawMessage]

    Subclasses may override:
        format_item(envelope: ExternalMessage) -> FeedItem
    """

    source: str  # e.g. "gmail", "rss"

    def __init__(self, pipeline: IngestionPipeline, store: IngestionStore) -> None:
        self.pipeline = pipeline
        self.store = store

    @abstractmethod
    async def fetch_items(self) -> list[RawMessage]:
        """Fetch raw items from the external source."""
        ...

    def format_item(self, envelope: ExternalMessage) -> FeedItem:
        """Convert a processed envelope into a FeedItem.

        Default implementation passes through body and metadata.
        Override for source-specific formatting (e.g. email → markdown).
        """
        return FeedItem(
            title=envelope.metadata.get("subject", envelope.source_id),
            body=envelope.body,
            source_id=envelope.source_id,
            metadata=envelope.metadata,
            risk_level=envelope.risk.risk_level,
        )

    async def run_cycle(self) -> CycleResult:
        """Execute one poll cycle: fetch → pipeline → format.

        Per-item errors are caught and recorded in CycleResult.errors
        without aborting the cycle.
        """
        result = CycleResult()

        # Fetch
        try:
            raw_items = await self.fetch_items()
        except Exception as exc:
            result.errors.append(f"fetch error: {exc}")
            return result

        result.fetched = len(raw_items)

        # Process each item through the pipeline
        for raw in raw_items:
            try:
                # Check duplicate before pipeline (pipeline also checks,
                # but we want accurate skip counts)
                if self.store.already_processed(raw.source, raw.source_id):
                    result.skipped += 1
                    continue

                envelope = await self.pipeline.process(raw)

                if envelope is None:
                    # Quarantined (pipeline handles the storage)
                    result.quarantined += 1
                    continue

                # Format into a FeedItem
                item = self.format_item(envelope)
                result.items.append(item)
                result.passed += 1

            except Exception as exc:
                result.errors.append(f"item {raw.source_id}: {exc}")

        return result

    # -- cursor helpers (delegate to store) --------------------------------

    def get_cursor(self, key: str | None = None) -> str | None:
        """Get the cursor value for this feed. Defaults to source name as key."""
        return self.store.get_cursor(key or self.source)

    def set_cursor(self, value: str, key: str | None = None) -> None:
        """Set the cursor value for this feed."""
        self.store.set_cursor(key or self.source, value)
