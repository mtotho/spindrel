"""Shared ingestion pipeline for external content integrations.

4-layer security pipeline:
  Layer 1 — Structural extraction (HTML strip, MIME decode, UTF-8 norm, truncation)
  Layer 2 — Deterministic injection filter (regex + zero-width chars)
  Layer 3 — AI safety classifier (isolated HTTP call, fails closed)
  Layer 4 — Typed envelope (Pydantic validation)
"""

from integrations.ingestion.envelope import ExternalMessage, RawMessage, RiskMetadata
from integrations.ingestion.pipeline import IngestionPipeline

__all__ = [
    "ExternalMessage",
    "IngestionPipeline",
    "RawMessage",
    "RiskMetadata",
]
