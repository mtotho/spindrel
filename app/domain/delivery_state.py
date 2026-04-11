"""DeliveryState — per-target outbox row lifecycle.

Each outbox row (one per (channel, seq, integration) tuple, introduced in
Phase D) carries a DeliveryState that tracks whether the event has been
successfully delivered to that integration's renderer.

State transitions:

    PENDING ──► IN_FLIGHT ──► DELIVERED
                    │
                    ├──► FAILED_RETRYABLE ──► PENDING (after backoff)
                    │                     └─► DEAD_LETTER (after max attempts)
                    │
                    └──► FAILED_PERMANENT ──► DEAD_LETTER

Phase A only defines the enum. Phase D uses it.
"""
from __future__ import annotations

from enum import StrEnum


class DeliveryState(StrEnum):
    PENDING = "pending"
    """Row inserted, not yet picked up by the drainer."""

    IN_FLIGHT = "in_flight"
    """Drainer locked the row and is calling the renderer."""

    DELIVERED = "delivered"
    """Renderer returned successfully (or row was capability-skipped)."""

    FAILED_RETRYABLE = "failed_retryable"
    """Transient error (5xx, 429, connection error). Retry with backoff."""

    FAILED_PERMANENT = "failed_permanent"
    """Non-retryable error (4xx other than 429, malformed payload).
    Will move to DEAD_LETTER on next sweep."""

    DEAD_LETTER = "dead_letter"
    """Exhausted retries or hit a permanent error. Surfaces via admin
    endpoint and publishes a `delivery_failed` event so the web UI can
    show a red indicator."""
