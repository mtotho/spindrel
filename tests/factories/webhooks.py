"""Factories for app.db.models.WebhookEndpoint."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.models import WebhookEndpoint


def build_webhook_endpoint(**overrides) -> WebhookEndpoint:
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        name=f"Webhook {suffix}",
        url="https://example.com/webhook",
        secret="test-secret-plaintext",  # no ENCRYPTION_KEY in tests → passthrough
        events=["after_response"],
        is_active=True,
        description="",
        created_at=now,
        updated_at=now,
    )
    return WebhookEndpoint(**{**defaults, **overrides})
