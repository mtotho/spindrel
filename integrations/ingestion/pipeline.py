"""Ingestion pipeline — orchestrates Layers 1-4."""

import html.parser
import io
import logging
import unicodedata

from integrations.ingestion.classifier import classify
from integrations.ingestion.config import IngestionConfig
from integrations.ingestion.envelope import ExternalMessage, RawMessage, RiskMetadata
from integrations.ingestion.filters import run_filters
from integrations.ingestion.store import IngestionStore

logger = logging.getLogger(__name__)


class _HTMLTextExtractor(html.parser.HTMLParser):
    """Simple HTML-to-text extractor using stdlib html.parser."""

    def __init__(self) -> None:
        super().__init__()
        self._buf = io.StringIO()
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.write(data)

    def get_text(self) -> str:
        return self._buf.getvalue()


def _extract_text(raw: str) -> str:
    """Layer 1 — structural extraction: strip HTML, normalize UTF-8, truncate."""
    extractor = _HTMLTextExtractor()
    extractor.feed(raw)
    text = extractor.get_text()
    # NFKC normalize
    text = unicodedata.normalize("NFKC", text)
    return text


class IngestionPipeline:
    """Stateful pipeline bound to a config and SQLite store."""

    def __init__(self, config: IngestionConfig, store: IngestionStore) -> None:
        self.config = config
        self.store = store
        self.last_classifier_error: bool = False

    async def process(self, msg: RawMessage) -> ExternalMessage | None:
        """Run a RawMessage through all 4 layers.

        Returns ExternalMessage on success, None if quarantined or duplicate.
        """
        # Idempotency check
        if self.store.already_processed(msg.source, msg.source_id):
            logger.debug("Skipping duplicate: %s/%s", msg.source, msg.source_id)
            return None

        # Layer 1 — structural extraction + truncation
        body = _extract_text(msg.raw_content)
        body = body[: self.config.max_body_bytes]

        # Layer 2 — deterministic filters
        flags = run_filters(body)

        # Layer 3 — AI classifier (always runs; Layer 2 flags inform but don't skip)
        result = await classify(
            body,
            base_url=self.config.agent_base_url,
            model=self.config.classifier_model,
            timeout=self.config.classifier_timeout,
            api_key=self.config.agent_api_key,
            max_retries=self.config.classifier_max_retries,
            retry_delay=self.config.classifier_retry_delay,
        )

        risk = RiskMetadata(
            layer2_flags=flags,
            risk_level=result.risk_level,
            classifier_reason=result.reason,
        )

        self.last_classifier_error = result.classifier_error

        # Quarantine unsafe messages
        if not result.safe:
            self.store.quarantine(
                source=msg.source,
                source_id=msg.source_id,
                raw_content=msg.raw_content,
                risk_level=result.risk_level,
                flags=flags,
                reason=result.reason,
            )
            self.store.audit(msg.source, msg.source_id, "quarantined", result.risk_level)
            self.store.mark_processed(msg.source, msg.source_id)
            logger.info("Quarantined %s/%s: %s", msg.source, msg.source_id, result.reason)
            return None

        # Layer 4 — build typed envelope
        envelope = ExternalMessage(
            source=msg.source,
            source_id=msg.source_id,
            body=body,
            metadata=msg.metadata,
            risk=risk,
        )

        self.store.audit(msg.source, msg.source_id, "passed", result.risk_level)
        self.store.mark_processed(msg.source, msg.source_id)
        logger.info("Passed %s/%s (risk=%s)", msg.source, msg.source_id, result.risk_level)
        return envelope
